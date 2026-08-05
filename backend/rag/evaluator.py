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


async def evaluate_conversations(rows: list[dict]) -> list[dict]:
    """rows = [{'query':..., 'answer':..., 'contexts':[...]}, ...]"""
    if not rows:
        return []

    eval_dataset = []
    for r in rows:
        eval_dataset.append(
            {
                "user_input": r["query"],
                "response": r["answer"],
                "retrieved_contexts": [c["text"] for c in r.get("contexts", [])],
            }
        )

    ds = Dataset.from_list(eval_dataset)
    llm = LangchainLLMWrapper(get_chat_llm())
    embeddings = LangchainEmbeddingsWrapper(get_embeddings())

    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=embeddings),
        LLMContextPrecisionWithoutReference(llm=llm),
    ]

    try:
        result = await asyncio.to_thread(
            evaluate, dataset=ds, metrics=metrics, llm=llm, embeddings=embeddings
        )
        df = result.to_pandas()
    except (RuntimeError, ValueError, TypeError) as e:
        logger.error("RAGAS evaluation failed: %s", e)
        # Return base rows with None scores if evaluation fails
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

    out = []
    for i, r in enumerate(rows):
        row = df.iloc[i]
        out.append(
            {
                "query": r["query"],
                "answer": r["answer"],
                "faithfulness": _safe_float(row.get("faithfulness")),
                "answer_relevancy": _safe_float(row.get("answer_relevancy")),
                "context_precision": _safe_float(row.get("llm_context_precision_without_reference")),
            }
        )
    return out


def _safe_float(v):
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return round(f, 4)
    except (ValueError, TypeError):
        return None
