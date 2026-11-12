"""Central factory for the Groq LLM client + local HuggingFace embeddings.

Groq exposes an OpenAI-compatible REST API, so we keep using the `openai` SDK
(and `langchain_openai.ChatOpenAI` for RAGAS) and simply point `base_url` at
Groq. That keeps the rest of the codebase provider-agnostic.

Embeddings are computed locally with sentence-transformers (MiniLM, dim 384)
because Groq does not serve an embeddings endpoint.
"""
import logging
import os
import threading
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from openai import BadRequestError, OpenAI
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


def _required(name: str, *, fallbacks: tuple[str, ...] = ()) -> str:
    """Read a required env var, with optional legacy fallbacks, failing loudly."""
    for key in (name, *fallbacks):
        val = os.environ.get(key)
        if val and val.strip():
            if key != name:
                logger.warning(
                    "Using deprecated env var %s; please rename it to %s.", key, name
                )
            return val.strip()
    raise RuntimeError(
        f"Missing required environment variable {name}. "
        f"Copy backend/env.example.txt to backend/.env and fill it in."
    )


# --- Groq configuration -------------------------------------------------------
GROQ_API_KEY = _required("GROQ_API_KEY")
# Groq's OpenAI-compatible endpoint.
GROQ_API_BASE = os.environ.get(
    "GROQ_API_BASE", "https://api.groq.com/openai/v1"
).strip().rstrip("/")

# Chat model served by Groq. Override via env; list valid IDs with:
#   curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b").strip()

# Separate judge model for RAGAS. Defaults to the generator, but grading a model
# with itself tends to inflate scores, so point this at a different model when
# you can.
EVAL_LLM_MODEL = (os.environ.get("EVAL_LLM_MODEL") or "").strip() or LLM_MODEL

# --- Reasoning-model knobs ----------------------------------------------------
# Reasoning models can put chain-of-thought into `message.content`, where it
# would be spliced into the answer we hand to the user AND to RAGAS (wrecking
# faithfulness scoring and the refusal strings the tests match on).
#
# Groq's knobs differ per model family:
# * gpt-oss: `reasoning_format` is NOT supported. Reasoning already goes to a
#   separate `message.reasoning` field by default; `include_reasoning=false`
#   drops it from the response entirely.
# * qwen3 / deepseek-r1 style models: `reasoning_format` = parsed|raw|hidden.
# * `reasoning_effort` (low|medium|high) is sent only when set.
#
# These are Groq-specific body fields, so they travel in `extra_body`: the
# openai SDK raises TypeError for unknown keyword arguments, which used to fail
# every query before a request was even made.
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "").strip().lower()
LLM_REASONING_FORMAT = os.environ.get("LLM_REASONING_FORMAT", "hidden").strip().lower()

# Models whose provider rejected the reasoning params (learned from a 400 that
# names them), so we stop paying for a failed request on every call.
_reasoning_rejected: set[str] = set()


def _is_gpt_oss(model: str) -> bool:
    return "gpt-oss" in model.lower()


def reasoning_kwargs(model: str | None = None) -> dict:
    """Groq reasoning body params for `model`; empty when none apply."""
    model = model or LLM_MODEL
    if model in _reasoning_rejected:
        return {}
    extra: dict = {}
    if LLM_REASONING_EFFORT:
        extra["reasoning_effort"] = LLM_REASONING_EFFORT
    if _is_gpt_oss(model):
        if LLM_REASONING_FORMAT == "hidden":
            extra["include_reasoning"] = False
    elif LLM_REASONING_FORMAT:
        extra["reasoning_format"] = LLM_REASONING_FORMAT
    return extra


def _rejects_reasoning_params(err: BadRequestError) -> bool:
    """True only for a 400 about the reasoning params themselves.

    Any other 400 (context too long, bad message format, ...) must surface as
    an error: disabling the params on it would let chain-of-thought leak into
    answers for the rest of the process.
    """
    text = f"{err} {getattr(err, 'body', '') or ''}".lower()
    return "reasoning" in text


# Local embedding model (not served by Groq).
EMBED_MODEL = os.environ.get(
    "EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
).strip()
EMBED_DIM = int(os.environ.get("EMBED_DIM", "384"))

# Hard timeout (seconds) for any single LLM HTTP call, so a hung upstream
# request can never pin a worker indefinitely.
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "60"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))


@lru_cache(maxsize=1)
def get_openai() -> OpenAI:
    """Raw OpenAI-SDK client pointed at Groq (used for answer generation)."""
    return OpenAI(
        api_key=GROQ_API_KEY,
        base_url=GROQ_API_BASE,
        timeout=LLM_TIMEOUT_S,
        max_retries=LLM_MAX_RETRIES,
    )


@lru_cache(maxsize=1)
def get_chat_llm() -> ChatOpenAI:
    """LangChain chat model pointed at Groq (the RAGAS judge)."""
    return ChatOpenAI(
        model=EVAL_LLM_MODEL,
        api_key=GROQ_API_KEY,
        base_url=GROQ_API_BASE,
        temperature=0,
        timeout=LLM_TIMEOUT_S,
        max_retries=LLM_MAX_RETRIES,
        # RAGAS parses structured output from `content`; leaked chain-of-thought
        # makes those parsers return None and the metric silently becomes NaN.
        extra_body=reasoning_kwargs(EVAL_LLM_MODEL) or None,
    )


def chat_completion(messages: list[dict], **overrides):
    """Chat completion against Groq, tolerant of unsupported reasoning params.

    Reasoning params are model-specific and can't be probed at import time, so
    if the provider rejects *them* (a 400 naming them) we retry once without
    them and remember that for this model. Other errors propagate.
    """
    client = get_openai()
    kwargs = {"model": LLM_MODEL, "temperature": 0, "messages": messages, **overrides}

    extra = reasoning_kwargs(LLM_MODEL)
    try:
        return client.chat.completions.create(**kwargs, extra_body=extra or None)
    except BadRequestError as err:
        if not extra or not _rejects_reasoning_params(err):
            raise
        logger.warning(
            "Model %s rejected reasoning params %s (%s); retrying without them and "
            "disabling them for this model.",
            LLM_MODEL,
            sorted(extra),
            err,
        )
        _reasoning_rejected.add(LLM_MODEL)
        if EVAL_LLM_MODEL == LLM_MODEL:
            # get_chat_llm() is cached and would otherwise keep handing RAGAS a
            # client carrying the rejected params.
            get_chat_llm.cache_clear()
        return client.chat.completions.create(**kwargs)


_st_lock = threading.Lock()
_st_instance: SentenceTransformer | None = None


def _st_model() -> SentenceTransformer:
    """The process-wide MiniLM model, loaded once.

    Locked because concurrent first calls (e.g. parallel eval questions right
    after startup) would otherwise each load their own copy.
    """
    global _st_instance
    if _st_instance is None:
        with _st_lock:
            if _st_instance is None:
                _st_instance = SentenceTransformer(EMBED_MODEL)
    return _st_instance


class SharedEmbeddings(Embeddings):
    """LangChain embeddings (for RAGAS) backed by the same MiniLM instance.

    RAGAS used to get a separate `HuggingFaceEmbeddings`, which loaded a second
    copy of the model into memory.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return embed_text(text)


@lru_cache(maxsize=1)
def get_embeddings() -> SharedEmbeddings:
    return SharedEmbeddings()


def embed_text(text: str) -> list[float]:
    v = _st_model().encode([text], normalize_embeddings=True)[0]
    return v.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    v = _st_model().encode(list(texts), normalize_embeddings=True, batch_size=32)
    return [row.tolist() for row in v]


def provider_info() -> dict:
    """Non-secret description of the active LLM provider (for /health)."""
    return {
        "provider": "groq",
        "base_url": GROQ_API_BASE,
        "model": LLM_MODEL,
        "eval_model": EVAL_LLM_MODEL,
        "embed_model": EMBED_MODEL,
        "embed_dim": EMBED_DIM,
        "timeout_s": LLM_TIMEOUT_S,
        "reasoning": reasoning_kwargs(LLM_MODEL),
    }
