"""Pinecone client + hybrid dense/BM25 retriever."""
import logging
import os
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

INDEX_NAME = os.environ["PINECONE_INDEX"]
PC_CLOUD = os.environ["PINECONE_CLOUD"]
PC_REGION = os.environ["PINECONE_REGION"]

_pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
_index = None
_bm25: BM25Okapi | None = None
_bm25_ids: list[str] = []
_bm25_texts: list[str] = []


def _ensure_index():
    global _index
    if _index is not None:
        return _index
    names = [x["name"] for x in _pc.list_indexes()]
    if INDEX_NAME not in names:
        _pc.create_index(
            name=INDEX_NAME,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud=PC_CLOUD, region=PC_REGION),
        )
        # wait for index to be ready
        for _ in range(30):
            desc = _pc.describe_index(INDEX_NAME)
            if desc.status.get("ready"):
                break
            time.sleep(2)
    _index = _pc.Index(INDEX_NAME)
    return _index


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in text.replace("\n", " ").split() if t]


def rebuild_bm25(records: list[dict]):
    """records = [{'id':..,'text':..}, ...]"""
    global _bm25, _bm25_ids, _bm25_texts
    _bm25_ids = [r["id"] for r in records]
    _bm25_texts = [r["text"] for r in records]
    if _bm25_texts:
        _bm25 = BM25Okapi([_tokenize(t) for t in _bm25_texts])
    else:
        _bm25 = None


def upsert_chunks(chunks: list[dict], batch_size: int = 64):
    """chunks: [{'id','text','metadata':{...}}, ...]"""
    idx = _ensure_index()
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
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


def delete_by_source(source: str):
    idx = _ensure_index()
    try:
        idx.delete(filter={"source": {"$eq": source}})
    except (PineconeException, TypeError, AttributeError) as e:
        logger.debug("Pinecone delete by source '%s' skipped: %s", source, e)


def delete_by_ids(ids: list[str]):
    if not ids:
        return
    idx = _ensure_index()
    try:
        idx.delete(ids=ids)
    except (PineconeException, TypeError, AttributeError) as e:
        logger.debug("Pinecone delete by ids failed: %s", e)


def dense_search(query: str, top_k: int = 8) -> list[dict]:
    idx = _ensure_index()
    qv = embed_text(query)
    res = idx.query(vector=qv, top_k=top_k, include_metadata=True)
    out = []
    for m in res.matches:
        out.append(
            {
                "id": m.id,
                "score": float(m.score),
                "text": m.metadata.get("text", ""),
                "metadata": {k: v for k, v in m.metadata.items() if k != "text"},
            }
        )
    return out


def bm25_search(query: str, top_k: int = 8) -> list[dict]:
    if _bm25 is None or not _bm25_texts:
        return []
    scores = _bm25.get_scores(_tokenize(query))
    top = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
    return [
        {
            "id": _bm25_ids[i],
            "score": float(scores[i]),
            "text": _bm25_texts[i],
            "metadata": {},
        }
        for i in top
        if scores[i] > 0
    ]


def hybrid_search(query: str, top_k: int = 5, alpha: float = 0.6) -> list[dict]:
    """Reciprocal rank fusion of dense + BM25."""
    dense = dense_search(query, top_k=top_k * 3)
    keyword = bm25_search(query, top_k=top_k * 3)

    ranks: dict[str, dict] = {}
    k_rrf = 60

    for r, hit in enumerate(dense):
        ranks.setdefault(hit["id"], {"hit": hit, "score": 0.0})
        ranks[hit["id"]]["score"] += alpha * (1.0 / (k_rrf + r + 1))

    for r, hit in enumerate(keyword):
        ranks.setdefault(hit["id"], {"hit": hit, "score": 0.0})
        # if we already have the hit from dense, keep its metadata (has text+source)
        ranks[hit["id"]]["score"] += (1 - alpha) * (1.0 / (k_rrf + r + 1))

    fused = sorted(ranks.values(), key=lambda x: -x["score"])[:top_k]
    return [
        {**item["hit"], "fused_score": item["score"]} for item in fused
    ]


def make_chunk_id(source: str, chunk_idx: int) -> str:
    return f"{source}::{chunk_idx}::{uuid.uuid4().hex[:8]}"


def index_stats() -> dict:
    try:
        idx = _ensure_index()
        s = idx.describe_index_stats()
        return {
            "total_vectors": s.get("total_vector_count", 0),
            "dimension": s.get("dimension", EMBED_DIM),
            "namespaces": list((s.get("namespaces") or {}).keys()),
        }
    except (PineconeException, RuntimeError) as e:
        return {"error": str(e)}
