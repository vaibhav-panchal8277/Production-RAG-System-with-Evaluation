"""Offline tests for background evaluation jobs and bounded test-set fan-out."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def eval_env(monkeypatch, fake_db):
    async def fake_eval(rows):
        return [
            {"query": r["query"], "answer": r["answer"], "trace_id": None, "faithfulness": 0.9}
            for r in rows
        ]

    monkeypatch.setattr(server, "db", fake_db)
    monkeypatch.setattr(server, "API_KEY", "")
    monkeypatch.setattr(server, "_retrieve", lambda *a: [])
    monkeypatch.setattr(server, "generate_answer", lambda q, c: (f"answer to {q}", "m"))
    monkeypatch.setattr(server, "trace_rag", lambda *a, **k: None)
    monkeypatch.setattr(server, "evaluate_conversations", fake_eval)
    return fake_db


def _wait_for(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/evaluations/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


def test_background_job_returns_202_then_result(eval_env):
    with TestClient(server.app) as client:
        r = client.post("/api/evaluations/run", json={"scope": "testset", "limit": 3, "background": True})
        assert r.status_code == 202, r.text
        job = _wait_for(client, r.json()["job_id"])
    assert job["status"] == "done", job
    result = job["result"]
    assert result["aggregate"]["n_samples"] == 3
    assert result["aggregate"]["faithfulness"] == 0.9
    assert len(result["per_row"]) == 3
    # Same run is in history.
    assert eval_env.eval_runs.rows[0]["id"] == result["id"]


def test_background_job_records_failure(eval_env):
    with TestClient(server.app) as client:
        r = client.post("/api/evaluations/run", json={"scope": "recent", "background": True})
        job = _wait_for(client, r.json()["job_id"])
    assert job["status"] == "failed"
    assert "No recent conversations" in job["error"]


def test_unknown_job_is_404(eval_env):
    with TestClient(server.app) as client:
        assert client.get("/api/evaluations/jobs/nope").status_code == 404


def test_startup_fails_jobs_left_over_from_a_previous_process(eval_env):
    eval_env.eval_jobs.rows = [{"id": "old", "status": "running"}, {"id": "ok", "status": "done"}]
    with TestClient(server.app):
        pass
    statuses = {j["id"]: j["status"] for j in eval_env.eval_jobs.rows}
    assert statuses == {"old": "failed", "ok": "done"}


def test_blocking_run_still_supported(eval_env):
    r = TestClient(server.app).post("/api/evaluations/run", json={"scope": "testset", "limit": 2})
    assert r.status_code == 200
    assert r.json()["aggregate"]["n_samples"] == 2


def test_testset_generation_is_concurrent_but_bounded_and_ordered(eval_env, monkeypatch):
    monkeypatch.setattr(server, "EVAL_CONCURRENCY", 2)
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def slow_retrieve(*args):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return []

    monkeypatch.setattr(server, "_retrieve", slow_retrieve)
    r = TestClient(server.app).post("/api/evaluations/run", json={"scope": "testset", "limit": 6})
    assert r.status_code == 200, r.text
    assert state["max"] == 2
    queries = [row["query"] for row in r.json()["per_row"]]
    assert queries == [item["question"] for item in server.TEST_SET[:6]]
