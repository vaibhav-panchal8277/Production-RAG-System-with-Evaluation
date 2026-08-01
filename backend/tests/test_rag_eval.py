"""Backend integration tests for RAG Evaluation System.

Covers:
  - /api/health (Pinecone + Mongo + Langfuse config)
  - /api/documents (list, seed, delete + rebuild BM25)
  - /api/query in hybrid, dense, keyword modes
  - /api/conversations list + persistence
  - /api/testset
  - /api/evaluations/run scope=testset limit=3
  - /api/evaluations/run scope=recent
  - /api/evaluations list
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def s():
    ses = requests.Session()
    ses.headers.update({"Content-Type": "application/json"})
    return ses


# ---------- health ----------
class TestHealth:
    def test_health(self, s):
        r = s.get(f"{BASE_URL}/api/health", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("langfuse_configured") is True
        assert "pinecone" in d
        assert isinstance(d["pinecone"].get("total_vectors"), int)
        assert d["pinecone"]["dimension"] == 384
        assert isinstance(d.get("mongo_docs"), int)
        assert isinstance(d.get("mongo_conversations"), int)


# ---------- documents ----------
class TestDocuments:
    def test_seed_documents(self, s):
        r = s.post(f"{BASE_URL}/api/documents/seed", timeout=300)
        assert r.status_code == 200
        d = r.json()
        ingested = d["ingested"]
        assert len(ingested) == 4, f"expected 4 seed docs, got {ingested}"
        for item in ingested:
            assert "error" not in item, f"seed error: {item}"
            assert item.get("n_chunks", 0) > 0, f"no chunks for {item}"

    def test_list_documents(self, s):
        r = s.get(f"{BASE_URL}/api/documents", timeout=30)
        assert r.status_code == 200
        docs = r.json()["documents"]
        assert len(docs) >= 4
        sources = {d["source"] for d in docs}
        expected = {
            "remote_work_policy.md",
            "data_retention_standard.md",
            "widget_3000_manual.md",
            "incident_response_runbook.md",
        }
        assert expected.issubset(sources), f"missing sources; got {sources}"
        for d in docs:
            if d["source"] in expected:
                assert d.get("kind") == "markdown"
                assert d.get("n_chunks", 0) > 0
                assert d.get("title")


# ---------- query modes ----------
class TestQuery:
    def test_query_hybrid_with_citations(self, s):
        r = s.post(
            f"{BASE_URL}/api/query",
            json={"query": "What is the retention period for Confidential-tier data?", "mode": "hybrid", "top_k": 5},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("answer")
        assert isinstance(d["contexts"], list) and len(d["contexts"]) >= 1
        # inline citations present
        assert "[chunk" in d["answer"].lower() or "chunk " in d["answer"].lower(), \
            f"expected [chunk N] citation in answer: {d['answer'][:400]}"
        # topic-source alignment
        sources = [c.get("source") for c in d["contexts"]]
        assert "data_retention_standard.md" in sources, f"retrieved sources: {sources}"
        assert d.get("mode") == "hybrid"
        assert d.get("model")
        assert isinstance(d.get("latency_ms"), int) and d["latency_ms"] > 0
        # trace_id may be null (soft failure) but key must exist
        assert "trace_id" in d

    def test_query_dense(self, s):
        r = s.post(
            f"{BASE_URL}/api/query",
            json={"query": "How do I reset a Widget-3000?", "mode": "dense", "top_k": 5},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["contexts"]
        assert d["mode"] == "dense"

    def test_query_keyword_bm25_sources(self, s):
        r = s.post(
            f"{BASE_URL}/api/query",
            json={"query": "incident response severity", "mode": "keyword", "top_k": 5},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["contexts"], "BM25 returned no contexts"
        for c in d["contexts"]:
            assert c.get("source"), f"BM25 context missing source: {c}"

    def test_conversation_persisted(self, s):
        # perform a query
        r = s.post(
            f"{BASE_URL}/api/query",
            json={"query": "TEST_persist remote work eligibility", "mode": "hybrid", "top_k": 3},
            timeout=120,
        )
        assert r.status_code == 200
        cid = r.json()["id"]
        # fetch via detail endpoint
        r2 = s.get(f"{BASE_URL}/api/conversations/{cid}", timeout=30)
        assert r2.status_code == 200
        conv = r2.json()
        assert conv["query"].startswith("TEST_persist")
        assert conv.get("model")
        assert conv.get("latency_ms", 0) > 0

    def test_conversations_list(self, s):
        r = s.get(f"{BASE_URL}/api/conversations", params={"limit": 30}, timeout=30)
        assert r.status_code == 200
        convs = r.json()["conversations"]
        assert len(convs) >= 1
        c0 = convs[0]
        for k in ("model", "latency_ms", "mode"):
            assert k in c0, f"missing {k} in conversation summary"
        # trace_id key present (value may be None)
        assert "trace_id" in c0


# ---------- test set ----------
class TestTestset:
    def test_testset_len(self, s):
        r = s.get(f"{BASE_URL}/api/testset", timeout=30)
        assert r.status_code == 200
        ts = r.json()["testset"]
        assert len(ts) == 8, f"expected 8 items, got {len(ts)}"
        for row in ts:
            for k in ("question", "reference", "expected_source"):
                assert k in row and row[k], f"missing {k}: {row}"


# ---------- evaluation ----------
class TestEvaluation:
    def test_eval_run_testset_limit3(self, s):
        t0 = time.time()
        r = s.post(
            f"{BASE_URL}/api/evaluations/run",
            json={"scope": "testset", "limit": 3},
            timeout=180,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        agg = d["aggregate"]
        assert agg["n_samples"] >= 1
        # aggregate values are float in [0,1] OR null
        for k in ("faithfulness", "answer_relevancy", "context_precision"):
            v = agg.get(k)
            assert v is None or (isinstance(v, (int, float)) and 0.0 <= v <= 1.0), \
                f"{k}={v}"
        assert isinstance(d.get("per_row"), list) and len(d["per_row"]) == agg["n_samples"]
        # at least one metric must be numeric across the run
        numeric_any = any(
            (row.get(m) is not None) for row in d["per_row"]
            for m in ("faithfulness", "answer_relevancy", "context_precision")
        )
        assert numeric_any, f"no numeric RAGAS scores at all in {d['per_row']}"
        print(f"eval-testset ran in {time.time()-t0:.1f}s -> agg={agg}")

    def test_eval_run_recent(self, s):
        r = s.post(
            f"{BASE_URL}/api/evaluations/run",
            json={"scope": "recent", "limit": 2},
            timeout=180,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["aggregate"]["scope"] == "recent"
        assert d["aggregate"]["n_samples"] >= 1

    def test_eval_list(self, s):
        r = s.get(f"{BASE_URL}/api/evaluations", timeout=30)
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert isinstance(runs, list)
        assert len(runs) >= 1
        # summary fields
        r0 = runs[0]
        for k in ("scope", "n_samples", "created_at"):
            assert k in r0


# ---------- delete + rebuild ----------
class TestDeleteDoc:
    def test_delete_and_reseed(self, s):
        # delete one doc
        r = s.delete(f"{BASE_URL}/api/documents/incident_response_runbook.md", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["deleted"] >= 1
        # confirm gone
        r2 = s.get(f"{BASE_URL}/api/documents", timeout=30)
        sources = {x["source"] for x in r2.json()["documents"]}
        assert "incident_response_runbook.md" not in sources
        # BM25 rebuilt: keyword search should not return that doc as source
        r3 = s.post(
            f"{BASE_URL}/api/query",
            json={"query": "incident response runbook severity", "mode": "keyword", "top_k": 5},
            timeout=120,
        )
        # It's ok if 404 (nothing left matching); the delete-and-rebuild path is the point
        if r3.status_code == 200:
            src_hit = [c.get("source") for c in r3.json()["contexts"]]
            assert "incident_response_runbook.md" not in src_hit
        # re-seed to restore state for follow-on tests
        s.post(f"{BASE_URL}/api/documents/seed", timeout=300)
