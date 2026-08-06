"""NeMo Guardrails wrapper for semantic input/output validation."""
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
    """Run semantic input guardrails via NeMo Guardrails."""
    if not rails:
        return None
    try:
        messages = [{"role": "user", "content": query}]
        res = rails.generate(messages=messages)
        if isinstance(res, dict) and "content" in res:
            return res["content"]
        if isinstance(res, str) and res.strip():
            return res
    except (ValueError, RuntimeError, ConnectionError) as e:
        logger.debug("NeMo Guardrails evaluation failed: %s", e)
    return None
