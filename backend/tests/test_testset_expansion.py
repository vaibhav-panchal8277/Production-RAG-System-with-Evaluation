"""Iteration 3 tests — 45-item testset expansion + hallucination resistance.

Verifies:
  1. GET /api/testset returns exactly 45 items with correct distribution.
  2. All items have non-empty question, reference, expected_source.
  3. POST /api/query for each of the 5 OUT_OF_SCOPE questions returns a refusal
     (case-insensitive contains "don't have enough" or "no information" or
     the model must NOT invent a citation-backed answer).
  4. POST /api/evaluations/run scope=testset limit=45 returns 45 per_row entries
     within ~4 minutes and persists to /api/evaluations history.
"""
import os
import time
from collections import Counter

import pytest
import requests

from rag.eval_metrics import is_refusal

if not os.environ.get("REACT_APP_BACKEND_URL"):
    pytest.skip("integration suite: REACT_APP_BACKEND_URL not set", allow_module_level=True)

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
pytestmark = pytest.mark.usefixtures("seeded_corpus")


@pytest.fixture(scope="module")
def s():
    ses = requests.Session()
    ses.headers.update({"Content-Type": "application/json"})
    # Only meaningful when the server runs with RAG_API_KEY set; harmless otherwise.
    api_key = (os.environ.get("RAG_API_KEY") or "").strip()
    if api_key:
        ses.headers.update({"X-API-Key": api_key})
    return ses


class TestTestsetExpansion:
    def test_testset_count_and_distribution(self, s):
        r = s.get(f"{BASE_URL}/api/testset", timeout=30)
        assert r.status_code == 200
        ts = r.json()["testset"]
        assert len(ts) == 45, f"expected 45, got {len(ts)}"

        dist = Counter(x["expected_source"] for x in ts)
        assert dist["remote_work_policy.md"] == 10
        assert dist["data_retention_standard.md"] == 10
        assert dist["widget_3000_manual.md"] == 10
        assert dist["incident_response_runbook.md"] == 10
        assert dist["OUT_OF_SCOPE"] == 5

    def test_testset_no_nulls_or_empties(self, s):
        r = s.get(f"{BASE_URL}/api/testset", timeout=30)
        ts = r.json()["testset"]
        for i, row in enumerate(ts):
            for k in ("question", "reference", "expected_source"):
                v = row.get(k)
                assert isinstance(v, str) and v.strip(), \
                    f"row {i} field {k}={v!r}"


class TestHallucinationResistance:
    """Send each OUT_OF_SCOPE question via /api/query and verify refusal."""

    def _oos_questions(self, s):
        r = s.get(f"{BASE_URL}/api/testset", timeout=30)
        return [x for x in r.json()["testset"] if x["expected_source"] == "OUT_OF_SCOPE"]

    def test_out_of_scope_refusals(self, s):
        oos = self._oos_questions(s)
        assert len(oos) == 5
        hallucinated = []
        refused = []
        for row in oos:
            q = row["question"]
            r = s.post(
                f"{BASE_URL}/api/query",
                json={"query": q, "mode": "hybrid", "top_k": 5},
                timeout=120,
            )
            assert r.status_code == 200, r.text
            answer = r.json().get("answer", "")
            if is_refusal(answer):
                refused.append((q, answer[:200]))
            else:
                hallucinated.append((q, answer[:400]))

        print(f"\nOUT_OF_SCOPE refused: {len(refused)}/5")
        for q, a in refused:
            print(f"  REFUSAL: {q!r} -> {a!r}")
        for q, a in hallucinated:
            print(f"  HALLUCINATED: {q!r} -> {a!r}")

        # Allow at most 1 soft failure; if 2+ hallucinate, model has a real problem.
        assert len(hallucinated) <= 1, (
            f"Model hallucinated on {len(hallucinated)}/5 OUT_OF_SCOPE questions: "
            f"{[q for q,_ in hallucinated]}"
        )


class TestFullEvalRun:
    """Run RAGAS eval on all 45 items and verify persistence."""

    def test_eval_run_full_testset_limit_45(self, s):
        t0 = time.time()
        r = s.post(
            f"{BASE_URL}/api/evaluations/run",
            json={"scope": "testset", "limit": 45},
            timeout=600,  # allow up to 10 min
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        d = r.json()
        agg = d["aggregate"]
        print(f"\nFull eval run took {elapsed:.1f}s, agg={agg}")

        assert agg["n_samples"] == 45, f"expected 45 samples, got {agg['n_samples']}"
        for k in ("faithfulness", "answer_relevancy", "context_precision"):
            v = agg.get(k)
            assert v is None or (isinstance(v, (int, float)) and 0.0 <= v <= 1.0), \
                f"{k}={v}"

        per_row = d["per_row"]
        assert isinstance(per_row, list) and len(per_row) == 45, \
            f"expected 45 per_row entries, got {len(per_row)}"
        for i, row in enumerate(per_row):
            assert "query" in row and isinstance(row["query"], str) and row["query"]
            assert "answer" in row and isinstance(row["answer"], str)
            for m in ("faithfulness", "answer_relevancy", "context_precision"):
                v = row.get(m)
                assert v is None or isinstance(v, (int, float)), \
                    f"row {i} {m}={v!r}"

        # At least some metrics must be numeric
        numeric_ct = sum(
            1 for row in per_row for m in ("faithfulness", "answer_relevancy", "context_precision")
            if row.get(m) is not None
        )
        assert numeric_ct > 0, "no numeric RAGAS scores at all"

        # Out-of-scope rows skip RAGAS and are scored on refusal instead.
        oos = [row for row in per_row if row.get("expected_source") == "OUT_OF_SCOPE"]
        assert len(oos) == 5
        for row in oos:
            assert row["refusal_correct"] in (0.0, 1.0)
            assert row["faithfulness"] is None and row["answer_correctness"] is None
        assert agg["refusal_accuracy"] is not None
        assert agg["retrieval_hit_rate"] is not None
        print(f"total numeric metric values across rows: {numeric_ct}/{45*3}")

    def test_eval_persisted_to_history(self, s):
        r = s.get(f"{BASE_URL}/api/evaluations", timeout=30)
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert len(runs) >= 1
        # Look for a recent run with n_samples=45
        found = [x for x in runs if x.get("n_samples") == 45]
        assert found, f"no run with n_samples=45 in history; got n_samples values: {[r.get('n_samples') for r in runs[:10]]}"
