"""Central factory for the Groq LLM client + local HuggingFace embeddings.

Groq exposes an OpenAI-compatible REST API, so we keep using the `openai` SDK
(and `langchain_openai.ChatOpenAI` for RAGAS) and simply point `base_url` at
Groq. That keeps the rest of the codebase provider-agnostic.

Embeddings are computed locally with sentence-transformers (MiniLM, dim 384)
because Groq does not serve an embeddings endpoint.
"""
import logging
import os
from functools import lru_cache

from langchain_community.embeddings import HuggingFaceEmbeddings
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

# --- Reasoning-model knobs ----------------------------------------------------
# gpt-oss models expose chain-of-thought. Groq accepts `reasoning_effort`
# (low|medium|high) and `reasoning_format` (parsed|raw|hidden) for them.
#
# `reasoning_format` matters for correctness, not just cost: if the CoT lands in
# `message.content` it is spliced into the answer we hand to the user AND to
# RAGAS, which wrecks faithfulness scoring and pollutes the refusal strings the
# test suite matches on. Defaulting to "hidden" keeps `content` to the final
# answer only.
#
# Both are sent ONLY when non-empty, and `chat_completion` below retries without
# them if the upstream model rejects them — so pointing LLM_MODEL at a
# non-reasoning model (e.g. llama-3.3-70b-versatile) stays safe with no edits.
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "").strip().lower()
LLM_REASONING_FORMAT = os.environ.get("LLM_REASONING_FORMAT", "hidden").strip().lower()


def reasoning_kwargs() -> dict:
    """Extra completion params for reasoning models; empty dict when unset."""
    extra: dict = {}
    if LLM_REASONING_EFFORT:
        extra["reasoning_effort"] = LLM_REASONING_EFFORT
    if LLM_REASONING_FORMAT:
        extra["reasoning_format"] = LLM_REASONING_FORMAT
    return extra


# Flipped to False the first time the upstream model 400s on a reasoning param,
# so we stop paying for a failed request on every subsequent call.
_reasoning_supported = True

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
    """LangChain chat model pointed at Groq (used by RAGAS metrics)."""
    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=GROQ_API_KEY,
        base_url=GROQ_API_BASE,
        temperature=0,
        timeout=LLM_TIMEOUT_S,
        max_retries=LLM_MAX_RETRIES,
        # RAGAS parses structured output from `content`; leaked chain-of-thought
        # makes those parsers return None and the metric silently becomes NaN.
        model_kwargs=reasoning_kwargs() if _reasoning_supported else {},
    )


def chat_completion(messages: list[dict], **overrides):
    """Chat completion against Groq, tolerant of unsupported reasoning params.

    Reasoning params are model-specific and this codebase cannot probe the
    provider at import time, so a rejected param must not take generation down:
    on a 400 we drop them and retry once, then remember not to send them again.
    """
    global _reasoning_supported
    client = get_openai()
    kwargs = {"model": LLM_MODEL, "temperature": 0, "messages": messages, **overrides}

    extra = reasoning_kwargs() if _reasoning_supported else {}
    try:
        return client.chat.completions.create(**kwargs, **extra)
    except BadRequestError:
        if not extra:
            raise
        logger.warning(
            "Model %s rejected reasoning params %s; retrying without them and "
            "disabling them for this process.",
            LLM_MODEL,
            sorted(extra),
        )
        _reasoning_supported = False
        # get_chat_llm() is cached and would otherwise keep handing RAGAS a
        # client carrying the rejected params, so generation would self-heal
        # while evaluation kept failing.
        get_chat_llm.cache_clear()
        return client.chat.completions.create(**kwargs)


@lru_cache(maxsize=1)
def _st_model() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    # LangChain wrapper used by RAGAS
    return HuggingFaceEmbeddings(model_name=EMBED_MODEL)


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
        "embed_model": EMBED_MODEL,
        "embed_dim": EMBED_DIM,
        "timeout_s": LLM_TIMEOUT_S,
        "reasoning": reasoning_kwargs() if _reasoning_supported else {},
    }
