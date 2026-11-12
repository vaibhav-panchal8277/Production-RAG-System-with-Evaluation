"""Offline tests: an unreachable Pinecone degrades to keyword search, not a 500.

Uses the real Pinecone client pointed at a closed local port, so the exception
types are exactly what an outage produces (urllib3 errors, not PineconeException).
"""
import asyncio

import pytest
from pinecone import Pinecone

from rag import ingest
from rag import vector_store as vs


@pytest.fixture
def unreachable_index(monkeypatch):
    index = Pinecone(api_key="test").Index(host="http://127.0.0.1:9")
    index._vector_api.api_client.configuration.retries = 0  # fail fast
    monkeypatch.setattr(vs, "_pc", object())
    monkeypatch.setattr(vs, "_index", index)
    monkeypatch.setattr(vs, "embed_text", lambda text: [0.0] * 3)
    monkeypatch.setattr(vs, "embed_texts", lambda texts: [[0.0] * 3 for _ in texts])
    vs.rebuild_bm25(
        [
            {"id": "1", "text": "Remote work requires six months of tenure.", "metadata": {"source": "remote.md"}},
            {"id": "2", "text": "Reset the Widget-3000 by holding the button.", "metadata": {"source": "widget.md"}},
            {"id": "3", "text": "Confidential data is retained seven years.", "metadata": {"source": "data.md"}},
        ]
    )
    yield index
    vs.rebuild_bm25([])


def test_dense_search_returns_empty(unreachable_index):
    assert vs.dense_search("remote work tenure", top_k=3) == []


def test_hybrid_falls_back_to_keyword(unreachable_index):
    hits = vs.hybrid_search("How long is the remote work tenure?", top_k=1)
    assert hits and hits[0]["source"] == "remote.md"


def test_health_stats_report_error_instead_of_raising(unreachable_index):
    stats = vs.index_stats()
    assert stats["total_vectors"] == 0 and "error" in stats


def test_upsert_reports_failure(unreachable_index):
    r = vs.upsert_chunks([{"id": "x#0", "text": "t", "metadata": {"source": "x"}}])
    assert r["upserted"] == 0 and r["failed"] == 1 and r["error"]


def test_ingest_still_succeeds_keyword_only(unreachable_index, fake_db):
    r = asyncio.run(ingest.ingest_document(fake_db, "a.md", b"alpha\n\nbeta words", "text/markdown"))
    assert r["n_chunks"] >= 1 and "failed to index for dense search" in r["warning"]


def test_delete_refuses_rather_than_orphaning(unreachable_index, fake_db):
    with pytest.raises(vs.VectorStoreError):
        asyncio.run(ingest.delete_document(fake_db, "a.md"))
