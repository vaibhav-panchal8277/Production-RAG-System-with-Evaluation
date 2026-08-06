"""LLM Guardrails for input validation and output safety checks."""
import logging
import re

logger = logging.getLogger(__name__)

# Common prompt injection / jailbreak indicators
INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all previous instructions",
    r"disregard all previous instructions",
    r"you are now a",
    r"system prompt",
    r"reveal your prompt",
    r"print your instructions",
]

# Sensitive PII patterns (API keys, credit cards, emails, SSN)
PII_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",  # OpenAI keys
    r"AKIA[0-9A-Z]{16}",     # AWS keys
    r"\b\d{3}-\d{2}-\d{4}\b", # SSN
]


def validate_input(query: str) -> tuple[bool, str]:
    """Check user query for prompt injection or malicious patterns."""
    if not query or not query.strip():
        return False, "Query cannot be empty."
    
    if len(query) > 2000:
        return False, "Query exceeds maximum allowed length of 2000 characters."

    query_lower = query.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, query_lower):
            logger.warning("Guardrail triggered: Potential prompt injection detected: '%s'", pattern)
            return False, "Query flagged by guardrails: potential prompt injection detected."

    return True, ""


def sanitize_output(answer: str) -> str:
    """Mask PII or sensitive patterns in generated responses."""
    sanitized = answer
    for pattern in PII_PATTERNS:
        sanitized = re.sub(pattern, "[FILTERED_SENSITIVE_DATA]", sanitized)
    return sanitized
