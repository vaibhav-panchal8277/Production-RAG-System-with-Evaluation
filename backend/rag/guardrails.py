"""Input guardrails for the RAG pipeline.

Design notes (this module was rewritten to fix two real defects):

1. **No RAG bypass.** The previous version called `LLMRails.generate()` and, if it
   returned anything at all, returned that text as the *final answer*. Because
   `generate()` returns a full bot response for ordinary questions, a working
   guardrail silently replaced the grounded, citation-backed answer and threw the
   retrieved context away. Guardrails now return a *decision* — block or allow —
   and never supply generated prose.

2. **Fails loudly, and narrowly.** The previous version swallowed every exception
   and returned `None`, so a misconfigured LLM disabled the guardrail with no
   signal. Errors are now logged at WARNING (once per process) and the built-in
   deterministic checks keep working regardless of LLM availability.

Scope is deliberately narrow: only greetings, empty/oversized input, and prompt
injection are blocked here. Off-topic-but-document-shaped questions are *allowed
through* on purpose — the grounded system prompt answers those with an explicit
"not in the provided documents" refusal, which is the behaviour we actually want
(and which the hallucination-resistance test suite asserts). Blocking them here
would replace a truthful refusal with a canned deflection.
"""
import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = int(os.environ.get("MAX_QUERY_CHARS", "2000"))
ENABLE_NEMO_RAILS = os.environ.get("ENABLE_NEMO_RAILS", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Phrased so it also reads as a grounded refusal ("don't have enough information
# in the provided documents"), keeping refusal detection consistent everywhere.
OFF_TOPIC_MESSAGE = (
    "I don't have enough information in the provided documents to answer this. "
    "I can only answer questions grounded in the indexed document corpus."
)
GREETING_MESSAGE = (
    "Hello! I answer questions about the indexed documents — internal policies "
    "and technical manuals. What would you like to look up?"
)
INJECTION_MESSAGE = (
    "I can't comply with instructions that try to change my operating rules. "
    "I answer questions using only the indexed documents. "
    "Please ask a document-related question."
)

# Exact-match greetings only (after normalisation). A question that merely opens
# with "hi" — e.g. "hi, what is the retention period?" — is NOT a greeting.
_GREETINGS = {
    "hi", "hii", "hello", "helo", "hey", "heya", "yo", "hiya",
    "good morning", "good afternoon", "good evening", "greetings",
    "thanks", "thank you", "thx", "ty", "ok", "okay", "cool", "bye",
    "goodbye", "see you", "who are you", "what can you do",
}

# Prompt-injection / system-prompt-exfiltration heuristics.
_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+instructions?",
    r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|rules?|prompts?)",
    r"forget\s+(?:all\s+|everything\s+)?(?:your\s+)?(?:previous\s+)?(?:instructions?|rules?|context)",
    r"(?:reveal|show|print|repeat|output|dump|display)\s+(?:me\s+)?(?:your\s+|the\s+)?(?:system\s+prompt|initial\s+prompt|instructions?|rules?)",
    r"what\s+(?:is|are)\s+your\s+(?:system\s+prompt|initial\s+instructions?|original\s+instructions?)",
    r"you\s+are\s+now\s+(?:a|an|no\s+longer)",
    r"act\s+as\s+(?:if\s+you\s+are\s+)?(?:a\s+|an\s+)?(?:different|unrestricted|jailbroken|DAN)",
    r"\bdeveloper\s+mode\b",
    r"\bjailbreak\b",
    r"pretend\s+(?:that\s+)?you\s+(?:are|have)\s+no\s+(?:rules|restrictions|guidelines)",
    r"(?:bypass|override|ignore)\s+(?:your\s+)?(?:safety|guardrails?|restrictions?|filters?)",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


@dataclass(frozen=True)
class GuardrailDecision:
    """Outcome of the input rails.

    blocked: whether the query should skip retrieval/generation entirely.
    message: user-facing text to return when blocked (None when allowed).
    reason:  short machine-readable tag for logging/observability.
    """

    blocked: bool
    message: str | None = None
    reason: str = "allowed"

    @classmethod
    def allow(cls) -> "GuardrailDecision":
        return cls(blocked=False, message=None, reason="allowed")

    @classmethod
    def block(cls, message: str, reason: str) -> "GuardrailDecision":
        return cls(blocked=True, message=message, reason=reason)


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation/emoji padding, collapse whitespace."""
    t = text.strip().lower()
    t = re.sub(r"[!?.,;:~\-_*\"'()\[\]]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ----- optional NeMo Guardrails layer ---------------------------------------
_nemo_rails = None
_nemo_warned = False

if ENABLE_NEMO_RAILS:
    try:
        from pathlib import Path

        from nemoguardrails import LLMRails, RailsConfig  # type: ignore

        _config_dir = Path(__file__).parent.parent / "config"
        _nemo_rails = LLMRails(RailsConfig.from_path(str(_config_dir)))
        logger.info("NeMo Guardrails enabled (semantic input layer active).")
    except Exception as e:  # noqa: BLE001 — third-party init raises broadly
        logger.warning(
            "ENABLE_NEMO_RAILS=true but NeMo Guardrails failed to initialise (%s). "
            "Falling back to deterministic input rails only.",
            e,
        )
        _nemo_rails = None


def _nemo_says_off_topic(query: str) -> bool:
    """Use NeMo strictly as a block decision — its prose is never returned.

    We only treat the response as a block when it matches the canned
    off-topic/refusal message defined in config/rails.co. Any other output means
    "not a topical violation", so the query proceeds to normal RAG.
    """
    global _nemo_warned
    if _nemo_rails is None:
        return False
    try:
        res = _nemo_rails.generate(messages=[{"role": "user", "content": query}])
        text = res.get("content", "") if isinstance(res, dict) else str(res or "")
        low = text.lower()
        return "restricted to answering questions" in low or "off topic" in low
    except Exception as e:  # noqa: BLE001
        if not _nemo_warned:
            _nemo_warned = True
            logger.warning(
                "NeMo Guardrails check failed; continuing with deterministic rails "
                "only. Further occurrences suppressed. Error: %s",
                e,
            )
        return False


# ----- public API -------------------------------------------------------------
def check_input(query: str) -> GuardrailDecision:
    """Validate a user query before it reaches retrieval/generation."""
    if query is None or not query.strip():
        return GuardrailDecision.block(
            "Please enter a question about the indexed documents.", "empty"
        )

    if len(query) > MAX_QUERY_CHARS:
        return GuardrailDecision.block(
            f"That query is too long ({len(query)} characters). "
            f"Please shorten it to under {MAX_QUERY_CHARS} characters.",
            "too_long",
        )

    for rx in _INJECTION_RE:
        if rx.search(query):
            logger.warning("Blocked possible prompt injection: %r", query[:120])
            return GuardrailDecision.block(INJECTION_MESSAGE, "prompt_injection")

    if _normalise(query) in _GREETINGS:
        return GuardrailDecision.block(GREETING_MESSAGE, "greeting")

    if _nemo_rails is not None and _nemo_says_off_topic(query):
        logger.info("NeMo Guardrails flagged query as off-topic: %r", query[:120])
        return GuardrailDecision.block(OFF_TOPIC_MESSAGE, "off_topic")

    return GuardrailDecision.allow()


def guardrails_status() -> dict:
    """Non-secret guardrail configuration, surfaced on /health."""
    return {
        "deterministic_rails": True,
        "nemo_enabled": ENABLE_NEMO_RAILS,
        "nemo_active": _nemo_rails is not None,
        "max_query_chars": MAX_QUERY_CHARS,
    }
