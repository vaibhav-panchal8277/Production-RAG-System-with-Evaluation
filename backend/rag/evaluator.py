"""RAGAS evaluation wrapper — Faithfulness, Context Precision, Answer Relevancy."""
import asyncio
import logging
import math

from datasets import Dataset
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    Faithfulness,
    LLMContextPrecisionWithoutReference,
    ResponseRelevancy,
)

from rag.llm_client import get_chat_llm, get_embeddings

logger = logging.getLogger(__name__)

# RAGAS has renamed metric columns across releases, and a hard-coded name that no
# longer exists silently yields None for every row. Try each candidate in order
# and fall back to substring matching before giving up.
_COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "faithfulness": ("faithfulness",),
    "answer_relevancy": ("answer_relevancy", "response_relevancy", "answer_relevance"),
    "context_precision": (
        "llm_context_precision_without_reference",
        "context_precision",
        "llm_context_precision",
    ),
}


def _resolve_columns(columns: list[str]) -> dict[str, str | None]:
    """Map our metric names onto whatever columns this RAGAS version produced."""
    resolved: dict[str, str | None] = {}
    lowered = {c.lower(): c for c in columns}
    for metric, candidates in _COLUMN_CANDIDATES.items():
        found = next((lowered[c] for c in candidates if c in lowered), None)
        if found is None:
            # last resort: any column containing the core token
            token = metric.split("_")[0]
            found = next(
                (orig for low, orig in lowered.items()
                 if token in low and low not in ("user_input", "response")),
                None,
            )
        if found is None:
            logger.warning(
                "RAGAS result has no column for %s (available: %s)", metric, columns
            )
        resolved[metric] = found
    return resolved


async def evaluate_conversations(rows: list[dict]) -> list[dict]:
    """rows = [{'query':..., 'answer':..., 'contexts':[...]}, ...]"""
    if not rows:
        return []

    eval_dataset = [
        {
            "user_input": r["query"],
            "response": r["answer"],
            "retrieved_contexts": [
                c.get("text", "") for c in (r.get("contexts") or [])
            ],
        }
        for r in rows
    ]

    ds = Dataset.from_list(eval_dataset)
    llm = LangchainLLMWrapper(get_chat_llm())
    embeddings = LangchainEmbeddingsWrapper(get_embeddings())

    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=embeddings),
        LLMContextPrecisionWithoutReference(llm=llm),
    ]

    def _empty(reason: str) -> list[dict]:
        logger.error("RAGAS evaluation unavailable: %s", reason)
        return [
            {
                "query": r["query"],
                "answer": r["answer"],
                "faithfulness": None,
                "answer_relevancy": None,
                "context_precision": None,
            }
            for r in rows
        ]

    try:
        result = await asyncio.to_thread(
            evaluate, dataset=ds, metrics=metrics, llm=llm, embeddings=embeddings
        )
        df = result.to_pandas()
    except (RuntimeError, ValueError, TypeError, KeyError) as e:
        logger.exception("RAGAS evaluation failed")
        return _empty(str(e))

    cols = _resolve_columns(list(df.columns))

    out = []
    for i, r in enumerate(rows):
        # Guard against RAGAS returning fewer rows than we submitted.
        row = df.iloc[i] if i < len(df) else None
        out.append(
            {
                "query": r["query"],
                "answer": r["answer"],
                "faithfulness": _cell(row, cols["faithfulness"]),
                "answer_relevancy": _cell(row, cols["answer_relevancy"]),
                "context_precision": _cell(row, cols["context_precision"]),
            }
        )
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
