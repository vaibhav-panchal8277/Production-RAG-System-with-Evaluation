"""Grounded answer generation (Groq) with input guardrails."""
import logging

from openai import OpenAIError

from rag.guardrails import check_input
from rag.llm_client import LLM_MODEL, chat_completion

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Retrieval-Augmented QA assistant answering questions about internal policy and technical documentation.

STRICT GROUNDING RULES:
1. Answer ONLY using facts present in the provided CONTEXT chunks. Do not use outside knowledge.
2. Every factual claim in your answer MUST cite the chunk it comes from using inline markers like [chunk 1], [chunk 3]. Multiple citations allowed.
3. If the CONTEXT is insufficient to answer, reply exactly: "I don't have enough information in the provided documents to answer this."
4. Be concise. Do not restate the question. Do not add preambles like "Based on the context...".
5. Never invent policy numbers, codes, dates, names, or figures.
"""

# Returned verbatim when retrieval yields nothing, so we don't spend an LLM call
# proving we have no context. Matches rule 3 above.
NO_CONTEXT_ANSWER = (
    "I don't have enough information in the provided documents to answer this."
)


def build_user_prompt(query: str, contexts: list[dict]) -> str:
    lines = ["CONTEXT:"]
    for i, c in enumerate(contexts, 1):
        meta = c.get("metadata") or {}
        src = c.get("source") or meta.get("source") or "unknown"
        section = c.get("section") or meta.get("section") or ""
        header = f"[chunk {i}] source={src}" + (f" | section={section}" if section else "")
        lines.append(header)
        lines.append(c.get("text", ""))
        lines.append("")
    lines.append(f"QUESTION: {query}")
    lines.append("\nAnswer with inline [chunk N] citations:")
    return "\n".join(lines)


def generate_answer(query: str, contexts: list[dict]) -> tuple[str, str]:
    """Return (answer, model).

    Guardrails may short-circuit with a canned message; they never rewrite a
    successfully generated, grounded answer.
    """
    decision = check_input(query)
    if decision.blocked:
        logger.info("Guardrail blocked query (%s)", decision.reason)
        return decision.message or NO_CONTEXT_ANSWER, LLM_MODEL

    if not contexts:
        # Nothing retrieved — refuse honestly instead of inviting a hallucination.
        return NO_CONTEXT_ANSWER, LLM_MODEL

    user_prompt = build_user_prompt(query, contexts)

    try:
        resp = chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = (resp.choices[0].message.content or "").strip()
        if not answer:
            logger.warning("LLM returned an empty completion for query %r", query[:120])
            answer = NO_CONTEXT_ANSWER
    except (OpenAIError, RuntimeError, ConnectionError, ValueError, TimeoutError) as e:
        # Log the full error server-side (model name / auth issues show up here),
        # return a generic message to the caller.
        logger.exception("LLM generation failed (model=%s): %s", LLM_MODEL, e)
        answer = "I encountered an error while generating the answer. Please try again."

    return answer, LLM_MODEL
