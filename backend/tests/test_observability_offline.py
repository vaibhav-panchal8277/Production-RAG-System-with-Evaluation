"""Offline tests for pushing eval metrics to Langfuse traces."""
import pytest
from fastapi.testclient import TestClient

import server
from rag import observability


class FakeLangfuse:
    def __init__(self):
        self.scores = []

    def score(self, trace_id, name, value, comment=""):
        self.scores.append((trace_id, name, value, comment))


@pytest.fixture
def fake_lf(monkeypatch):
    lf = FakeLangfuse()
    monkeypatch.setattr(observability, "get_langfuse", lambda: lf)
    return lf


def test_score_eval_rows_skips_untraced_rows_and_missing_metrics(fake_lf):
    rows = [
        {"trace_id": "t1", "faithfulness": 0.9, "context_recall": None},
        {"trace_id": None, "faithfulness": 0.5},
    ]
    sent = observability.score_eval_rows(rows, ("faithfulness", "context_recall"), "run-1")
    assert sent == 1
    assert fake_lf.scores == [("t1", "faithfulness", 0.9, "eval run run-1")]


def test_score_eval_rows_noop_without_langfuse(monkeypatch):
    monkeypatch.setattr(observability, "get_langfuse", lambda: None)
    assert observability.score_eval_rows([{"trace_id": "t", "faithfulness": 1.0}], ("faithfulness",), "r") == 0


def test_testset_run_traces_items_and_scores_them(monkeypatch, fake_db, fake_lf):
    traced = []

    def fake_trace(query, contexts, answer, model, latency_ms, name="rag-query"):
        traced.append(name)
        return f"trace:{query}"

    async def fake_eval(rows):
        return [
            {"query": r["query"], "answer": r["answer"], "trace_id": r["trace_id"], "faithfulness": 0.8}
            for r in rows
        ]

    monkeypatch.setattr(server, "db", fake_db)
    monkeypatch.setattr(server, "API_KEY", "")
    monkeypatch.setattr(server, "_retrieve", lambda *a: [])
    monkeypatch.setattr(server, "generate_answer", lambda q, c: ("answer", "m"))
    monkeypatch.setattr(server, "trace_rag", fake_trace)
    monkeypatch.setattr(server, "evaluate_conversations", fake_eval)

    r = TestClient(server.app).post("/api/evaluations/run", json={"scope": "testset", "limit": 2})
    assert r.status_code == 200, r.text
    assert traced == ["rag-eval-testset", "rag-eval-testset"]
    # Each score lands on the trace of the question it graded.
    expected = {(f"trace:{item['question']}", "faithfulness", 0.8) for item in server.TEST_SET[:2]}
    assert {(t, n, v) for t, n, v, _ in fake_lf.scores} == expected
