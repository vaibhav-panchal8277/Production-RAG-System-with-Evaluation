"""Langfuse tracing wrapper — degrades gracefully if not configured.

`lf.flush()` is a blocking network call. It used to run on every single query,
adding upstream latency to the request path, so tracing is now fire-and-forget:
the Langfuse SDK batches in a background thread and we only force a flush at
shutdown (see `shutdown_tracing`).
"""
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse
except ImportError:
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
    except (ValueError, RuntimeError, ConnectionError) as e:
        logger.warning("Failed to initialize Langfuse client: %s", e)
        return None


def trace_rag(
    query: str, contexts: list[dict], answer: str, model: str, latency_ms: int
) -> str | None:
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
            output={
                "contexts": [
                    {
                        "source": c.get("source")
                        or (c.get("metadata") or {}).get("source"),
                        "text": (c.get("text") or "")[:200],
                    }
                    for c in contexts
                ]
            },
        )
        trace.generation(
            name="generate",
            model=model,
            input={"query": query, "n_contexts": len(contexts)},
            output=answer,
        )
        # No flush here — the SDK batches asynchronously.
        return trace.id
    except (RuntimeError, ConnectionError, ValueError, AttributeError) as e:
        logger.debug("Langfuse trace failed: %s", e)
        return None


def score_trace(trace_id: str, name: str, value: float, comment: str = ""):
    lf = get_langfuse()
    if not lf or not trace_id:
        return
    try:
        lf.score(trace_id=trace_id, name=name, value=float(value), comment=comment)
    except (RuntimeError, ConnectionError, ValueError, AttributeError) as e:
        logger.debug("Langfuse score failed for trace %s: %s", trace_id, e)


def shutdown_tracing():
    """Flush any buffered Langfuse events at process shutdown."""
    lf = get_langfuse()
    if not lf:
        return
    try:
        lf.flush()
    except (RuntimeError, ConnectionError, AttributeError) as e:
        logger.debug("Langfuse flush on shutdown failed: %s", e)
