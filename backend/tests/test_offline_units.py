"""Offline unit tests — no backend, API keys or network needed."""
import asyncio
import os

import pytest

from rag.chunk_ids import legacy_id_prefix, make_chunk_id, source_id_prefix
from rag.eval_metrics import (
    OUT_OF_SCOPE,
    is_refusal,
    refusal_score,
    retrieval_scores,
)


# ---------- chunk IDs ----------
class TestChunkIds:
    def test_deterministic(self):
        assert make_chunk_id("a.md", 3) == make_chunk_id("a.md", 3)

    def test_grouped_under_source_prefix(self):
        prefix = source_id_prefix("a.md")
        assert all(make_chunk_id("a.md", i).startswith(prefix) for i in range(20))
        assert not make_chunk_id("b.md", 0).startswith(prefix)

    def test_ascii_and_bounded_for_any_filename(self):
        cid = make_chunk_id("relatório_ünïcode_" + "x" * 600 + ".pdf", 7)
        assert cid.isascii()
        assert len(cid) < 64

    def test_legacy_prefix(self):
        assert legacy_id_prefix("a.md") == "a.md::"
        assert legacy_id_prefix("relatório.md") is None


# ---------- deterministic eval metrics ----------
def _ctx(source):
    return {"source": source, "text": "..."}


class TestRetrievalScores:
    def test_hit_at_rank_one(self):
        assert retrieval_scores([_ctx("a.md"), _ctx("b.md")], "a.md") == {
            "retrieval_hit": 1.0,
            "reciprocal_rank": 1.0,
        }

    def test_hit_at_rank_three(self):
        s = retrieval_scores([_ctx("x"), _ctx("y"), _ctx("a.md")], "a.md")
        assert s == {"retrieval_hit": 1.0, "reciprocal_rank": 0.3333}

    def test_source_in_metadata_only(self):
        s = retrieval_scores([{"metadata": {"source": "a.md"}}], "a.md")
        assert s["retrieval_hit"] == 1.0

    def test_miss(self):
        assert retrieval_scores([_ctx("x")], "a.md") == {
            "retrieval_hit": 0.0,
            "reciprocal_rank": 0.0,
        }

    def test_not_applicable(self):
        for expected in (None, "", OUT_OF_SCOPE):
            assert retrieval_scores([_ctx("a.md")], expected) == {
                "retrieval_hit": None,
                "reciprocal_rank": None,
            }


class TestRefusal:
    def test_canonical_refusal(self):
        assert is_refusal(
            "I don't have enough information in the provided documents to answer this."
        )

    def test_answer_is_not_refusal(self):
        assert not is_refusal("Six (6) months of continuous employment [chunk 1].")
        assert not is_refusal("")
        assert not is_refusal(None)

    def test_refusal_score_only_for_out_of_scope(self):
        refusal = "The documents do not contain this information."
        assert refusal_score(refusal, OUT_OF_SCOPE) == 1.0
        assert refusal_score("The CEO earns $1M [chunk 2].", OUT_OF_SCOPE) == 0.0
        assert refusal_score(refusal, "a.md") is None
        assert refusal_score(refusal, None) is None


# ---------- evaluator routing (RAGAS stubbed out) ----------
class TestEvaluatorRouting:
    @pytest.fixture
    def evaluator(self, monkeypatch):
        pytest.importorskip("ragas")
        # llm_client requires a key at import; it is never used here.
        monkeypatch.setenv("GROQ_API_KEY", os.environ.get("GROQ_API_KEY") or "test-dummy")
        from rag import evaluator

        calls = []

        async def fake_run_ragas(rows, with_reference):
            calls.append(([r["query"] for r in rows], with_reference))
            keys = evaluator.RAGAS_METRICS if with_reference else evaluator.REFERENCE_FREE_METRICS
            return [dict.fromkeys(keys, 0.5) for _ in rows]

        monkeypatch.setattr(evaluator, "_run_ragas", fake_run_ragas)
        evaluator.calls = calls
        return evaluator

    def test_rows_routed_by_reference_and_scope(self, evaluator):
        rows = [
            {"query": "q1", "answer": "a [chunk 1]", "contexts": [_ctx("a.md")],
             "reference": "ref", "expected_source": "a.md"},
            {"query": "q2", "answer": "I don't have enough information.", "contexts": [],
             "reference": "should refuse", "expected_source": OUT_OF_SCOPE},
            {"query": "q3", "answer": "b", "contexts": [_ctx("b.md")]},
        ]
        out = asyncio.run(evaluator.evaluate_conversations(rows))

        # Out-of-scope row never reaches RAGAS; others batched by reference.
        assert sorted(evaluator.calls, key=lambda c: c[1]) == [(["q3"], False), (["q1"], True)]

        golden, oos, recent = out
        assert all(k in row for row in out for k in evaluator.ALL_METRICS)

        assert golden["answer_correctness"] == 0.5 and golden["context_recall"] == 0.5
        assert golden["retrieval_hit"] == 1.0 and golden["refusal_correct"] is None

        assert oos["refusal_correct"] == 1.0
        assert oos["faithfulness"] is None and oos["answer_correctness"] is None
        assert oos["retrieval_hit"] is None

        assert recent["faithfulness"] == 0.5
        assert recent["answer_correctness"] is None and recent["retrieval_hit"] is None

    def test_column_resolution_never_crosses_metrics(self, evaluator):
        cols = ["user_input", "response", "faithfulness", "context_recall"]
        resolved = evaluator._resolve_columns(cols, evaluator.RAGAS_METRICS)
        assert resolved["context_recall"] == "context_recall"
        assert resolved["context_precision"] is None  # must not fall back to recall
