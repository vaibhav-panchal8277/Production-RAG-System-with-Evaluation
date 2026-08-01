"""RAGAS evaluation wrapper — Faithfulness, Context Precision, Answer Relevancy."""
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    Faithfulness,
    ResponseRelevancy,
    LLMContextPrecisionWithoutReference,
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper

from rag.llm_client import get_chat_llm, get_embeddings


def _wrappers():
    return (
        LangchainLLMWrapper(get_chat_llm()),
        LangchainEmbeddingsWrapper(get_embeddings()),
    )


def evaluate_conversations(rows: list[dict]) -> list[dict]:
    """rows: [{query, answer, contexts:[str,...]}, ...] -> per-row metric dicts."""
    if not rows:
        return []
    llm_w, emb_w = _wrappers()
    ds = Dataset.from_list(
        [
            {
                "user_input": r["query"],
                "response": r["answer"],
                "retrieved_contexts": r["contexts"] or [""],
            }
            for r in rows
        ]
    )
    result = evaluate(
        ds,
        metrics=[
            Faithfulness(),
            ResponseRelevancy(),
            LLMContextPrecisionWithoutReference(),
        ],
        llm=llm_w,
        embeddings=emb_w,
        show_progress=False,
    )
    df = result.to_pandas()
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
        if f != f:  # NaN
            return None
        return round(f, 4)
    except Exception:
        return None
