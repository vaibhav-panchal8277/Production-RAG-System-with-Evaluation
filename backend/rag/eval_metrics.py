"""Deterministic, LLM-free metrics scored against the golden test set.

These need no judge model, so they are cheap, exactly reproducible, and immune
to the self-grading bias of using the generator as its own RAGAS judge. They
complement the RAGAS scores in `rag.evaluator`:

* retrieval hit / reciprocal rank — did a chunk from the document the golden
  set names (`expected_source`) make it into the retrieved contexts, and how
  high did it rank?
* refusal correctness — for out-of-scope questions the right answer is a
  refusal; reference-based RAGAS metrics are meaningless there.

Kept free of heavy imports so it can be unit-tested without the RAG stack.
"""
import re

OUT_OF_SCOPE = "OUT_OF_SCOPE"

# Phrasings that count as declining to answer. Generation is instructed to use
# one exact sentence, but judge refusals by pattern so a reworded refusal is not
# misreported as a hallucination.
_REFUSAL_PATTERNS = [
    r"don'?t have enough",
    r"do not have enough",
    r"not (?:enough |contain|mentioned|specified|available|described|include)",
    r"no information",
    r"cannot (?:answer|find|determine|provide)",
    r"can'?t (?:answer|find|determine|provide)",
    r"not (?:in|found in|present in) the (?:provided )?documents?",
    r"documents? (?:do not|don'?t) (?:contain|mention|include)",
    r"insufficient (?:information|context)",
    r"unable to (?:answer|find|determine)",
]
_REFUSAL_RE = [re.compile(p, re.IGNORECASE) for p in _REFUSAL_PATTERNS]


def is_refusal(text: str | None) -> bool:
    if not text:
        return False
    return any(rx.search(text) for rx in _REFUSAL_RE)


def is_out_of_scope(row: dict) -> bool:
    return (row.get("expected_source") or "") == OUT_OF_SCOPE


def _context_source(context: dict) -> str | None:
    return context.get("source") or (context.get("metadata") or {}).get("source")


def retrieval_scores(contexts: list[dict] | None, expected_source: str | None) -> dict:
    """Hit (0/1) and reciprocal rank of the first chunk from `expected_source`.

    Both are None when there is no expected source to compare against (recent
    user queries, or out-of-scope questions where nothing *should* match).
    """
    if not expected_source or expected_source == OUT_OF_SCOPE:
        return {"retrieval_hit": None, "reciprocal_rank": None}
    for rank, ctx in enumerate(contexts or [], 1):
        if _context_source(ctx) == expected_source:
            return {"retrieval_hit": 1.0, "reciprocal_rank": round(1.0 / rank, 4)}
    return {"retrieval_hit": 0.0, "reciprocal_rank": 0.0}


def refusal_score(answer: str | None, expected_source: str | None) -> float | None:
    """1.0 if an out-of-scope question was refused, 0.0 if answered; else None."""
    if expected_source != OUT_OF_SCOPE:
        return None
    return 1.0 if is_refusal(answer) else 0.0
