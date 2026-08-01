"""Langfuse tracing wrapper — degrades gracefully if not configured."""
import os
from functools import lru_cache

try:
    from langfuse import Langfuse
except Exception:
    Langfuse = None  # type: ignore


@lru_cache(maxsize=1)
def get_langfuse():
    if not Langfuse:
        return None
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    if not pk or not sk:
        return None
    try:
        return Langfuse(public_key=pk, secret_key=sk, host=host)
    except Exception:
        return None


def trace_rag(query: str, contexts: list[dict], answer: str, model: str, latency_ms: int) -> str | None:
    lf = get_langfuse()
    if not lf:
        return None
    try:
        trace = lf.trace(
            name="rag-query",
            input={"query": query},
            output={"answer": answer},
            metadata={"latency_ms": latency_ms, "n_contexts": len(contexts)},
        )
        trace.span(
            name="retrieve",
            input={"query": query},
            output={"contexts": [{"source": c.get("metadata", {}).get("source"), "text": c["text"][:200]} for c in contexts]},
        )
        trace.generation(
            name="generate",
            model=model,
            input={"query": query, "n_contexts": len(contexts)},
            output=answer,
        )
        lf.flush()
        return trace.id
    except Exception:
        return None


def score_trace(trace_id: str, name: str, value: float, comment: str = ""):
    lf = get_langfuse()
    if not lf or not trace_id:
        return
    try:
        lf.score(trace_id=trace_id, name=name, value=float(value), comment=comment)
        lf.flush()
    except Exception:
        pass
