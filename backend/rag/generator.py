"""Grounded answer generation with strict citations."""
from rag.llm_client import LLM_MODEL, get_openai

SYSTEM_PROMPT = """You are a Retrieval-Augmented QA assistant answering questions about internal policy and technical documentation.

STRICT GROUNDING RULES:
1. Answer ONLY using facts present in the provided CONTEXT chunks. Do not use outside knowledge.
2. Every factual claim in your answer MUST cite the chunk it comes from using inline markers like [chunk 1], [chunk 3]. Multiple citations allowed.
3. If the CONTEXT is insufficient to answer, reply exactly: "I don't have enough information in the provided documents to answer this."
4. Be concise. Do not restate the question. Do not add preambles like "Based on the context...".
5. Never invent policy numbers, codes, dates, names, or figures.
"""


def build_user_prompt(query: str, contexts: list[dict]) -> str:
    lines = ["CONTEXT:"]
    for i, c in enumerate(contexts, 1):
        src = c.get("metadata", {}).get("source", "unknown")
        section = c.get("metadata", {}).get("section", "")
        header = f"[chunk {i}] source={src}" + (f" | section={section}" if section else "")
        lines.append(header)
        lines.append(c["text"])
        lines.append("")
    lines.append(f"QUESTION: {query}")
    lines.append("\nAnswer with inline [chunk N] citations:")
    return "\n".join(lines)


def generate_answer(query: str, contexts: list[dict]) -> dict:
    client = get_openai()
    user_prompt = build_user_prompt(query, contexts)
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    answer = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    return {
        "answer": answer,
        "prompt": user_prompt,
        "model": LLM_MODEL,
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
    }
