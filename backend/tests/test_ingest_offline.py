"""Offline tests for ingest / delete against in-memory Mongo and Pinecone fakes."""
import asyncio

import pytest

from rag import ingest
from rag import vector_store as vs
from rag.chunk_ids import make_chunk_id


def _para(word: str) -> str:
    # ~700 chars: two of these exceed the real splitter's 800-char chunk size,
    # so each paragraph becomes its own chunk.
    return " ".join([word] * 100)


DOC = "\n\n".join(_para(w) for w in ("one", "two", "three")).encode()
MULTI = "\n\n".join(_para(w) for w in ("alpha", "gamma", "other")).encode()


def _ingest(db, source="a.md", content=DOC):
    return ingest.ingest_document(db, source, content, "text/markdown")


def test_ingest_writes_vectors_chunks_and_bm25(fake_db, fake_index):
    r = asyncio.run(_ingest(fake_db))
    assert r["n_chunks"] >= 1 and "warning" not in r
    assert len(fake_index.vectors) == r["n_chunks"]
    assert len(fake_db.chunks.rows) == r["n_chunks"]
    assert vs.bm25_size() == r["n_chunks"]
    # Embedding + upsert ran in a worker thread, not on the event loop.
    assert "MainThread" not in fake_index.upsert_threads


def test_reingest_is_idempotent_even_without_mongo_records(fake_db, fake_index):
    n = asyncio.run(_ingest(fake_db))["n_chunks"]
    fake_db.chunks.rows.clear()  # e.g. fresh CI database, shared index
    asyncio.run(_ingest(fake_db))
    assert len(fake_index.vectors) == n


def test_reingest_removes_legacy_and_extra_vectors(fake_db, fake_index):
    fake_index.vectors["a.md::0::deadbeef"] = {"id": "a.md::0::deadbeef"}
    fake_index.vectors[make_chunk_id("a.md", 99)] = {"id": "stale tail"}
    n = asyncio.run(_ingest(fake_db))["n_chunks"]
    assert sorted(fake_index.vectors) == sorted(make_chunk_id("a.md", i) for i in range(n))


def test_concurrent_ingests_of_same_source_serialise(fake_db, fake_index):
    async def many():
        await asyncio.gather(*(_ingest(fake_db) for _ in range(5)))

    asyncio.run(many())
    n = len(fake_index.vectors)
    assert len(fake_db.chunks.rows) == n
    assert vs.bm25_size() == n


def test_delete_failure_leaves_everything_intact(fake_db, fake_index):
    asyncio.run(_ingest(fake_db))
    before = (len(fake_index.vectors), len(fake_db.chunks.rows), len(fake_db.documents.rows))
    fake_index.fail_delete = True
    with pytest.raises(vs.VectorStoreError):
        asyncio.run(ingest.delete_document(fake_db, "a.md"))
    after = (len(fake_index.vectors), len(fake_db.chunks.rows), len(fake_db.documents.rows))
    assert after == before


def test_delete_finds_vectors_without_mongo_ids(fake_db, fake_index):
    asyncio.run(_ingest(fake_db))
    # Several chunks, so BM25 IDF is positive for a term in just one of them.
    asyncio.run(_ingest(fake_db, "b.md", MULTI))
    fake_db.chunks.rows = [r for r in fake_db.chunks.rows if r["source"] != "a.md"]
    out = asyncio.run(ingest.delete_document(fake_db, "a.md"))
    assert out == {"deleted": 1, "source": "a.md"}
    assert all(not i.startswith(make_chunk_id("a.md", 0)[:-1]) for i in fake_index.vectors)
    assert [c["source"] for c in vs.bm25_search("other", 5)] == ["b.md"]


def test_delete_without_pinecone_configured(fake_db, fake_index, monkeypatch):
    asyncio.run(_ingest(fake_db))
    monkeypatch.setattr(vs, "_pc", None)  # keyword-only mode
    out = asyncio.run(ingest.delete_document(fake_db, "a.md"))
    assert out["deleted"] == 1 and vs.bm25_size() == 0
