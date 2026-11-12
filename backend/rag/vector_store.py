"""Pinecone client + hybrid dense/BM25 retriever with graceful fallback.

Context dicts returned by every search function share one shape:

    {
      "id": str,
      "score": float,
      "text": str,
      "source": str,          # flattened for API consumers/UIs
      "section": str,         # flattened for API consumers/UIs
      "metadata": {...},      # full metadata, minus the duplicated text
    }

`source`/`section` are duplicated at the top level because the API contract (and
both frontends) read them there, while `metadata` is kept for richer consumers.
"""
import logging
import os
import re
import threading
import time

from pinecone import Pinecone, ServerlessSpec
from urllib3.exceptions import HTTPError as Urllib3HTTPError

try:
    from pinecone.exceptions import PineconeException
except ImportError:
    PineconeException = Exception  # type: ignore
from rank_bm25 import BM25Okapi

from rag.chunk_ids import legacy_id_prefix, source_id_prefix
from rag.llm_client import EMBED_DIM, embed_text, embed_texts

# Everything a Pinecone call can raise when the service is unhealthy. HTTP error
# responses arrive as PineconeException, but when Pinecone can't be reached at
# all (connection refused, DNS, timeout) the client raises urllib3 errors, which
# are NOT PineconeException — catching only the latter made /query return 500
# during an outage instead of falling back to keyword search.
_PC_ERRORS = (PineconeException, Urllib3HTTPError)

logger = logging.getLogger(__name__)

INDEX_NAME = os.environ.get("PINECONE_INDEX", "rag-eval-index")
PC_CLOUD = os.environ.get("PINECONE_CLOUD", "aws")
PC_REGION = os.environ.get("PINECONE_REGION", "us-east-1")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
# Bounded wait for a freshly created serverless index to become ready.
INDEX_READY_TIMEOUT_S = float(os.environ.get("PINECONE_READY_TIMEOUT_S", "60"))
# Optional namespace, so CI runs / separate environments can share one index
# without seeing or deleting each other's vectors. Blank = default namespace.
PINECONE_NAMESPACE = os.environ.get("PINECONE_NAMESPACE", "").strip()
_NS = {"namespace": PINECONE_NAMESPACE} if PINECONE_NAMESPACE else {}

# Pinecone delete accepts at most 1000 IDs per request.
_DELETE_BATCH = 1000

_PLACEHOLDER_KEYS = {"", "pc_test_key", "pcsk_test", "your_pinecone_api_key"}

_pc = None
try:
    if PINECONE_API_KEY and PINECONE_API_KEY not in _PLACEHOLDER_KEYS:
        _pc = Pinecone(api_key=PINECONE_API_KEY)
except (PineconeException, RuntimeError, ValueError) as e:
    logger.warning("Pinecone client initialization failed: %s", e)

class VectorStoreError(RuntimeError):
    """The vector store could not complete an operation the caller relies on."""


_index = None
_index_lock = threading.Lock()

# BM25 state is process-local. With a single uvicorn worker (the default here)
# that is correct; if you scale to multiple workers/replicas, each process keeps
# its own copy and an upload handled by one worker is not keyword-searchable in
# the others until they rebuild. Move to a shared store (or Pinecone sparse
# vectors) before scaling out. The lock keeps rebuilds atomic w.r.t. readers.
_bm25: BM25Okapi | None = None
_bm25_ids: list[str] = []
_bm25_texts: list[str] = []
_bm25_meta: list[dict] = []
_bm25_lock = threading.RLock()


def _ensure_index():
    """Return the Pinecone index handle, creating it if necessary.

    Thread-safe and bounded: never blocks longer than INDEX_READY_TIMEOUT_S.
    """
    global _index
    if _index is not None:
        return _index
    if not _pc:
        raise RuntimeError("Pinecone client is not initialized or API key is invalid.")

    with _index_lock:
        if _index is not None:  # another thread won the race
            return _index

        existing = _pc.list_indexes()
        # SDK versions differ: newer returns objects with .name, older dicts.
        names = set()
        for x in existing:
            name = x.get("name") if isinstance(x, dict) else getattr(x, "name", None)
            if name:
                names.add(name)

        if INDEX_NAME not in names:
            logger.info("Creating Pinecone index %s (dim=%d)", INDEX_NAME, EMBED_DIM)
            _pc.create_index(
                name=INDEX_NAME,
                dimension=EMBED_DIM,
                metric="cosine",
                spec=ServerlessSpec(cloud=PC_CLOUD, region=PC_REGION),
            )
            deadline = time.monotonic() + INDEX_READY_TIMEOUT_S
            while time.monotonic() < deadline:
                desc = _pc.describe_index(INDEX_NAME)
                status = getattr(desc, "status", None) or {}
                ready = status.get("ready") if isinstance(status, dict) else getattr(status, "ready", False)
                if ready:
                    break
                time.sleep(2)
            else:
                raise RuntimeError(
                    f"Pinecone index {INDEX_NAME} not ready after {INDEX_READY_TIMEOUT_S}s"
                )

        _index = _pc.Index(INDEX_NAME)
        return _index


# A word, optionally joined to more words by - . / : (keeps "hr-rw-01",
# "widget-3000", "10:00", "v1.2" whole). Surrounding punctuation is dropped, so
# "work?" in a query matches "work" in a document — whitespace splitting used to
# keep it as the token "work?", which matched nothing.
_TOKEN_RE = re.compile(r"\w+(?:[-./:]\w+)*")
_SUBTOKEN_RE = re.compile(r"[-./:]")


def _tokenize(text: str) -> list[str]:
    """Lowercased word tokens; compounds also emit their parts.

    "Widget-3000" -> ["widget-3000", "widget", "3000"], so both the exact code
    and a query written "Widget 3000" match.
    """
    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        tokens.append(tok)
        if _SUBTOKEN_RE.search(tok):
            tokens.extend(p for p in _SUBTOKEN_RE.split(tok) if p)
    return tokens


def _shape(hit_id: str, score: float, text: str, metadata: dict) -> dict:
    """Build a context dict with source/section flattened for API consumers."""
    meta = dict(metadata or {})
    meta.pop("text", None)
    return {
        "id": hit_id,
        "score": float(score),
        "text": text,
        "source": meta.get("source") or "unknown",
        "section": meta.get("section") or "",
        "metadata": meta,
    }


def rebuild_bm25(records: list[dict]):
    """records = [{'id':..,'text':..,'metadata':{...}}, ...]"""
    global _bm25, _bm25_ids, _bm25_texts, _bm25_meta
    ids = [r["id"] for r in records]
    texts = [r.get("text") or "" for r in records]
    metas = [r.get("metadata") or {} for r in records]
    model = BM25Okapi([_tokenize(t) for t in texts]) if texts else None
    with _bm25_lock:
        _bm25_ids, _bm25_texts, _bm25_meta, _bm25 = ids, texts, metas, model
    logger.info("BM25 index rebuilt with %d chunks", len(ids))


def upsert_chunks(chunks: list[dict], batch_size: int = 64) -> dict:
    """Embed and upsert chunks. Returns a summary so callers can detect failure.

    Pinecone problems are reported (not silently swallowed) so ingestion can tell
    the user that dense search will be degraded.
    """
    if not chunks:
        return {"upserted": 0, "failed": 0, "available": True, "error": None}

    try:
        idx = _ensure_index()
    except (*_PC_ERRORS, RuntimeError) as e:
        logger.warning("Pinecone upsert skipped (index unavailable): %s", e)
        return {"upserted": 0, "failed": len(chunks), "available": False, "error": str(e)}

    upserted = failed = 0
    first_error: str | None = None
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        try:
            embeds = embed_texts([c["text"] for c in batch])
            vectors = [
                {
                    "id": c["id"],
                    "values": e,
                    "metadata": {**c["metadata"], "text": c["text"]},
                }
                for c, e in zip(batch, embeds)
            ]
            idx.upsert(vectors=vectors, **_NS)
            upserted += len(batch)
        except (*_PC_ERRORS, RuntimeError, ValueError) as err:
            failed += len(batch)
            first_error = first_error or str(err)
            logger.warning("Pinecone batch upsert failed (batch %d): %s", i // batch_size, err)

    return {
        "upserted": upserted,
        "failed": failed,
        "available": True,
        "error": first_error,
    }


def _list_ids(idx, prefix: str) -> list[str]:
    """All vector IDs under `prefix` (serverless indexes only).

    Collected fully before anything is deleted so deletes can't disturb the
    pagination.
    """
    ids: list[str] = []
    for page in idx.list(prefix=prefix, **_NS):
        ids.extend(page)
    return ids


def delete_source_vectors(source: str, known_ids: list[str] | tuple = ()) -> bool:
    """Delete every vector belonging to `source`. Returns False on failure.

    Vectors are found from Pinecone itself by ID prefix (current and legacy ID
    schemes), so this works even when Mongo has lost track of them — the old
    metadata-filter delete was not supported on serverless indexes and failed
    silently. `known_ids` (from Mongo) are deleted too, which covers pod-based
    indexes where listing by prefix is unavailable.

    With Pinecone not configured at all (keyword-only mode) there is nothing to
    delete, so that counts as success.
    """
    if _pc is None:
        return True
    try:
        idx = _ensure_index()
    except (*_PC_ERRORS, RuntimeError) as e:
        logger.warning("Pinecone unavailable; cannot delete vectors for '%s': %s", source, e)
        return False

    ids = set(known_ids)
    prefixes = [p for p in (source_id_prefix(source), legacy_id_prefix(source)) if p]
    try:
        for prefix in prefixes:
            ids.update(_list_ids(idx, prefix))
    except Urllib3HTTPError as e:
        # Unreachable: we can't see what exists, so we can't claim success.
        logger.warning("Pinecone unreachable; cannot delete vectors for '%s': %s", source, e)
        return False
    except PineconeException as e:
        # Pod-based indexes don't support list(); fall back to the known IDs.
        logger.warning(
            "Listing vectors by prefix failed for '%s' (%s); deleting the %d IDs "
            "recorded in Mongo only.",
            source,
            e,
            len(ids),
        )

    try:
        id_list = sorted(ids)
        for i in range(0, len(id_list), _DELETE_BATCH):
            idx.delete(ids=id_list[i : i + _DELETE_BATCH], **_NS)
        return True
    except _PC_ERRORS as e:
        logger.warning("Pinecone delete failed for '%s': %s", source, e)
        return False


def dense_search(query: str, top_k: int = 8) -> list[dict]:
    try:
        idx = _ensure_index()
        qv = embed_text(query)
        res = idx.query(vector=qv, top_k=top_k, include_metadata=True, **_NS)
        matches = getattr(res, "matches", None) or (
            res.get("matches", []) if isinstance(res, dict) else []
        )
        out = []
        for m in matches:
            meta = (m.get("metadata") if isinstance(m, dict) else m.metadata) or {}
            mid = m.get("id") if isinstance(m, dict) else m.id
            mscore = m.get("score") if isinstance(m, dict) else m.score
            out.append(_shape(mid, mscore or 0.0, meta.get("text", ""), meta))
        return out
    except (*_PC_ERRORS, RuntimeError, ValueError) as e:
        # Hybrid search then serves BM25 results alone.
        logger.warning("Dense search unavailable, using keyword search only: %s", e)
        return []


def bm25_search(query: str, top_k: int = 8) -> list[dict]:
    with _bm25_lock:
        if _bm25 is None or not _bm25_texts:
            return []
        scores = _bm25.get_scores(_tokenize(query))
        ids, texts, metas = _bm25_ids, _bm25_texts, _bm25_meta

    top = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
    return [
        _shape(ids[i], scores[i], texts[i], metas[i] if i < len(metas) else {})
        for i in top
        if scores[i] > 0
    ]


def hybrid_search(query: str, top_k: int = 5, alpha: float = 0.6) -> list[dict]:
    """Reciprocal rank fusion of dense + BM25."""
    dense = dense_search(query, top_k=top_k * 3)
    keyword = bm25_search(query, top_k=top_k * 3)

    # If dense is empty (e.g. Pinecone not configured), rely purely on BM25.
    if not dense:
        return keyword[:top_k]
    if not keyword:
        return dense[:top_k]

    ranks: dict[str, dict] = {}
    k_rrf = 60

    for r, hit in enumerate(dense):
        ranks.setdefault(hit["id"], {"hit": hit, "score": 0.0})
        ranks[hit["id"]]["score"] += alpha * (1.0 / (k_rrf + r + 1))

    for r, hit in enumerate(keyword):
        ranks.setdefault(hit["id"], {"hit": hit, "score": 0.0})
        ranks[hit["id"]]["score"] += (1 - alpha) * (1.0 / (k_rrf + r + 1))

    fused = sorted(ranks.values(), key=lambda x: -x["score"])[:top_k]
    return [{**item["hit"], "fused_score": item["score"]} for item in fused]


def bm25_size() -> int:
    with _bm25_lock:
        return len(_bm25_ids)


def index_stats() -> dict:
    try:
        idx = _ensure_index()
        s = idx.describe_index_stats()
        if not isinstance(s, dict):
            s = getattr(s, "_data_store", None) or dict(s)
        return {
            "namespace": PINECONE_NAMESPACE,
            "total_vectors": s.get("total_vector_count", 0) or 0,
            "dimension": s.get("dimension", EMBED_DIM) or EMBED_DIM,
            "namespaces": list((s.get("namespaces") or {}).keys()),
        }
    except (*_PC_ERRORS, RuntimeError, ValueError, TypeError) as e:
        # Keep the shape stable so /health consumers don't need branching.
        return {
            "namespace": PINECONE_NAMESPACE,
            "total_vectors": 0,
            "dimension": EMBED_DIM,
            "namespaces": [],
            "error": f"Pinecone unavailable ({e})",
        }
