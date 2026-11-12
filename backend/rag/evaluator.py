"""Evaluation: RAGAS metrics plus deterministic golden-set checks.

Which metrics a row gets depends on what we know about it:

* every in-scope row — reference-free RAGAS: Faithfulness, Answer Relevancy,
  Context Precision (without reference);
* rows with a golden `reference` answer (the test set) — additionally
  Answer Correctness and Context Recall, which compare against that reference;
* rows with an `expected_source` — retrieval hit / reciprocal rank, no LLM;
* out-of-scope rows — only refusal correctness. They skip RAGAS entirely:
  faithfulness of a refusal is undefined and answer relevancy scores every
  correct refusal as ~0, which used to drag the run averages down.
"""
import asyncio
import logging
import math
import os

from datasets import Dataset
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    AnswerCorrectness,
    Faithfulness,
    LLMContextPrecisionWithoutReference,
    LLMContextRecall,
    ResponseRelevancy,
)
from ragas.run_config import RunConfig

from rag.eval_metrics import is_out_of_scope, refusal_score, retrieval_scores
from rag.llm_client import get_chat_llm, get_embeddings

logger = logging.getLogger(__name__)

# Parallel judge calls. RAGAS defaults to 16, which trips Groq's rate limits on
# a full test-set run and turns metrics into NaN.
EVAL_RAGAS_WORKERS = max(1, int(os.environ.get("EVAL_RAGAS_WORKERS", "4")))
EVAL_RAGAS_TIMEOUT_S = int(os.environ.get("EVAL_RAGAS_TIMEOUT_S", "180"))

REFERENCE_FREE_METRICS = ("faithfulness", "answer_relevancy", "context_precision")
REFERENCE_METRICS = ("answer_correctness", "context_recall")
RAGAS_METRICS = REFERENCE_FREE_METRICS + REFERENCE_METRICS
DETERMINISTIC_METRICS = ("retrieval_hit", "reciprocal_rank", "refusal_correct")
ALL_METRICS = RAGAS_METRICS + DETERMINISTIC_METRICS

# Result column names in the pinned RAGAS release (0.2.x), with older aliases.
_COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "faithfulness": ("faithfulness",),
    "answer_relevancy": ("answer_relevancy", "response_relevancy", "answer_relevance"),
    "context_precision": (
        "llm_context_precision_without_reference",
        "context_precision",
        "llm_context_precision",
    ),
    "answer_correctness": ("answer_correctness",),
    "context_recall": ("context_recall", "llm_context_recall"),
}


def _resolve_columns(columns: list[str], metrics: tuple[str, ...]) -> dict[str, str | None]:
    """Map our metric names onto whatever columns this RAGAS version produced.

    The fallback requires *every* token of the metric name to appear, so
    `context_precision` can never be mapped onto `context_recall`.
    """
    resolved: dict[str, str | None] = {}
    lowered = {c.lower(): c for c in columns}
    for metric in metrics:
        found = next((lowered[c] for c in _COLUMN_CANDIDATES[metric] if c in lowered), None)
        if found is None:
            tokens = metric.split("_")
            found = next(
                (orig for low, orig in lowered.items() if all(t in low for t in tokens)),
                None,
            )
        if found is None:
            logger.warning("RAGAS result has no column for %s (available: %s)", metric, columns)
        resolved[metric] = found
    return resolved


async def _run_ragas(rows: list[dict], with_reference: bool) -> list[dict]:
    """Score `rows` with RAGAS; one {metric: score|None} dict per row."""
    keys = RAGAS_METRICS if with_reference else REFERENCE_FREE_METRICS

    samples = []
    for r in rows:
        sample = {
            "user_input": r["query"],
            "response": r["answer"],
            "retrieved_contexts": [c.get("text", "") for c in (r.get("contexts") or [])],
        }
        if with_reference:
            sample["reference"] = r["reference"]
        samples.append(sample)

    llm = LangchainLLMWrapper(get_chat_llm())
    embeddings = LangchainEmbeddingsWrapper(get_embeddings())
    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=embeddings),
        LLMContextPrecisionWithoutReference(llm=llm),
    ]
    if with_reference:
        metrics += [
            AnswerCorrectness(llm=llm, embeddings=embeddings),
            LLMContextRecall(llm=llm),
        ]

    try:
        result = await asyncio.to_thread(
            evaluate,
            dataset=Dataset.from_list(samples),
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
            run_config=RunConfig(
                max_workers=EVAL_RAGAS_WORKERS, timeout=EVAL_RAGAS_TIMEOUT_S
            ),
        )
        df = result.to_pandas()
    except (RuntimeError, ValueError, TypeError, KeyError):
        logger.exception("RAGAS evaluation failed")
        return [dict.fromkeys(keys) for _ in rows]

    cols = _resolve_columns(list(df.columns), keys)
    out = []
    for i in range(len(rows)):
        # Guard against RAGAS returning fewer rows than we submitted.
        row = df.iloc[i] if i < len(df) else None
        out.append({k: _cell(row, cols[k]) for k in keys})
    return out


async def evaluate_conversations(rows: list[dict]) -> list[dict]:
    """Score each row; every row gets every key in ALL_METRICS (None = n/a).

    rows = [{'query', 'answer', 'contexts', optional 'reference',
             optional 'expected_source'}, ...]
    """
    if not rows:
        return []

    out = []
    for r in rows:
        expected = r.get("expected_source")
        scored = {
            "query": r["query"],
            "answer": r["answer"],
            "expected_source": expected,
            "trace_id": r.get("trace_id"),
            **dict.fromkeys(ALL_METRICS),
        }
        scored.update(retrieval_scores(r.get("contexts"), expected))
        scored["refusal_correct"] = refusal_score(r["answer"], expected)
        out.append(scored)

    # RAGAS needs a uniform schema per run, so rows with and without a golden
    # reference are scored in separate batches. Out-of-scope rows are skipped.
    batches: dict[bool, list[int]] = {True: [], False: []}
    for i, r in enumerate(rows):
        if not is_out_of_scope(r):
            batches[bool(r.get("reference"))].append(i)

    for with_reference, idxs in batches.items():
        if not idxs:
            continue
        scores = await _run_ragas([rows[i] for i in idxs], with_reference)
        for i, s in zip(idxs, scores):
            out[i].update(s)

    return out


def _cell(row, column: str | None):
    if row is None or not column:
        return None
    try:
        return _safe_float(row.get(column))
    except (AttributeError, KeyError):
        return None


def _safe_float(v):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    except (ValueError, TypeError):
        return None
