"""NeMo Guardrails wrapper for semantic input/output validation with robust fallback."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from nemoguardrails import LLMRails, RailsConfig
    CONFIG_DIR = Path(__file__).parent.parent / "config"
    config = RailsConfig.from_path(str(CONFIG_DIR))
    rails = LLMRails(config)
except (ImportError, ValueError, RuntimeError, OSError) as e:
    logger.warning("NeMo Guardrails initialization skipped or failed: %s", e)
    rails = None


def check_input_rails(query: str) -> str | None:
    """Run semantic input guardrails via NeMo Guardrails with graceful fallback."""
    if not rails:
        return None
    try:
        messages = [{"role": "user", "content": query}]
        res = rails.generate(messages=messages)
        if isinstance(res, dict) and "content" in res:
            return res["content"]
        if isinstance(res, str) and res.strip():
            return res
    except Exception as e:  # noqa: BLE001
        # Catch any guardrails / LLM auth exceptions during guardrails check and fall back gracefully
        logger.debug("NeMo Guardrails evaluation skipped/bypassed: %s", e)
    return None
