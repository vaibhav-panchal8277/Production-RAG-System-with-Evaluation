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
import threading
import time
import uuid

from pinecone import Pinecone, ServerlessSpec

try:
    from pinecone.exceptions import PineconeException
except ImportError:
    PineconeException = Exception  # type: ignore
from rank_bm25 import BM25Okapi

from rag.llm_client import EMBED_DIM, embed_text, embed_texts

logger = logging.getLogger(__name__)

INDEX_NAME = os.environ.get("PINECONE_INDEX", "rag-eval-index")
PC_CLOUD = os.environ.get("PINECONE_CLOUD", "aws")
PC_REGION = os.environ.get("PINECONE_REGION", "us-east-1")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
# Bounded wait for a freshly created serverless index to become ready.
INDEX_READY_TIMEOUT_S = float(os.environ.get("PINECONE_READY_TIMEOUT_S", "60"))

_PLACEHOLDER_KEYS = {"", "pc_test_key", "pcsk_test", "your_pinecone_api_key"}

_pc = None
try:
    if PINECONE_API_KEY and PINECONE_API_KEY not in _PLACEHOLDER_KEYS:
        _pc = Pinecone(api_key=PINECONE_API_KEY)
except (PineconeException, RuntimeError, ValueError) as e:
    logger.warning("Pinecone client initialization failed: %s", e)

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


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in text.replace("\n", " ").split() if t]


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
    except (PineconeException, RuntimeError) as e:
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
            idx.upsert(vectors=vectors)
            upserted += len(batch)
        except (PineconeException, RuntimeError, ValueError) as err:
            failed += len(batch)
            first_error = first_error or str(err)
            logger.warning("Pinecone batch upsert failed (batch %d): %s", i // batch_size, err)

    return {
        "upserted": upserted,
        "failed": failed,
        "available": True,
        "error": first_error,
    }


def delete_by_source(source: str) -> bool:
    try:
        idx = _ensure_index()
        idx.delete(filter={"source": {"$eq": source}})
        return True
    except (PineconeException, TypeError, AttributeError, RuntimeError) as e:
        logger.warning("Pinecone delete by source '%s' failed: %s", source, e)
        return False


def delete_by_ids(ids: list[str], batch_size: int = 1000) -> bool:
    if not ids:
        return True
    try:
        idx = _ensure_index()
        for i in range(0, len(ids), batch_size):
            idx.delete(ids=ids[i : i + batch_size])
        return True
    except (PineconeException, TypeError, AttributeError, RuntimeError) as e:
        logger.warning("Pinecone delete by ids failed: %s", e)
        return False


def dense_search(query: str, top_k: int = 8) -> list[dict]:
    try:
        idx = _ensure_index()
        qv = embed_text(query)
        res = idx.query(vector=qv, top_k=top_k, include_metadata=True)
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
    except (PineconeException, RuntimeError, ValueError) as e:
        logger.debug("Dense search unavailable, falling back to empty: %s", e)
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


def make_chunk_id(source: str, chunk_idx: int) -> str:
    return f"{source}::{chunk_idx}::{uuid.uuid4().hex[:8]}"


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
            "total_vectors": s.get("total_vector_count", 0) or 0,
            "dimension": s.get("dimension", EMBED_DIM) or EMBED_DIM,
            "namespaces": list((s.get("namespaces") or {}).keys()),
        }
    except (PineconeException, RuntimeError, ValueError, TypeError) as e:
        # Keep the shape stable so /health consumers don't need branching.
        return {
            "total_vectors": 0,
            "dimension": EMBED_DIM,
            "namespaces": [],
            "error": f"Pinecone unavailable ({e})",
        }
