"""Offline tests for answer post-processing in the generator."""
from types import SimpleNamespace

import pytest

from rag import generator
from rag.generator import normalize_citations


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Seen live from openai/gpt-oss-120b on Groq:
        ("Confidential data is retained for 7 years from creation【chunk 2】.",
         "Confidential data is retained for 7 years from creation[chunk 2]."),
        ("A【chunk 1, 3】 and B【chunk 4†L2-L9】", "A[chunk 1, 3] and B[chunk 4]"),
        ("Mixed【chunk 1，chunk 2】", "Mixed[chunk 1, 2]"),
        ("Already fine [chunk 2].", "Already fine [chunk 2]."),
        ("Not a citation【note】 stays", "Not a citation【note】 stays"),
    ],
)
def test_normalize_citations(raw, expected):
    assert normalize_citations(raw) == expected


def test_generate_answer_normalizes_model_output(monkeypatch):
    reply = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Seven years【chunk 1】."))]
    )
    monkeypatch.setattr(generator, "chat_completion", lambda messages: reply)
    answer, _ = generator.generate_answer("How long?", [{"text": "7 years", "source": "a.md"}])
    assert answer == "Seven years[chunk 1]."
