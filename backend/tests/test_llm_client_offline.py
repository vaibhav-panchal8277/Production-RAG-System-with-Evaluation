"""Offline tests for reasoning-param handling in the Groq client."""
import httpx
import pytest
from openai import BadRequestError, OpenAI

from rag import llm_client


def _bad_request(message: str) -> BadRequestError:
    request = httpx.Request("POST", "http://test/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError(message, response=response, body={"error": {"message": message}})


class FakeCompletions:
    def __init__(self, errors=()):
        self.calls: list[dict] = []
        self._errors = list(errors)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._errors:
            raise self._errors.pop(0)
        return "ok"


@pytest.fixture
def fake_client(monkeypatch):
    def install(errors=()):
        completions = FakeCompletions(errors)
        client = type("C", (), {})()
        client.chat = type("Chat", (), {"completions": completions})()
        monkeypatch.setattr(llm_client, "get_openai", lambda: client)
        return completions.calls

    monkeypatch.setattr(llm_client, "_reasoning_rejected", set())
    return install


@pytest.fixture
def model(monkeypatch):
    def set_model(name, fmt="hidden", effort=""):
        monkeypatch.setattr(llm_client, "LLM_MODEL", name)
        monkeypatch.setattr(llm_client, "EVAL_LLM_MODEL", name)
        monkeypatch.setattr(llm_client, "LLM_REASONING_FORMAT", fmt)
        monkeypatch.setattr(llm_client, "LLM_REASONING_EFFORT", effort)

    return set_model


def test_gpt_oss_never_gets_reasoning_format(model):
    model("openai/gpt-oss-120b", effort="low")
    assert llm_client.reasoning_kwargs() == {"include_reasoning": False, "reasoning_effort": "low"}


def test_other_reasoning_models_get_reasoning_format(model):
    model("qwen/qwen3-32b")
    assert llm_client.reasoning_kwargs() == {"reasoning_format": "hidden"}
    model("llama-3.3-70b-versatile", fmt="")
    assert llm_client.reasoning_kwargs() == {}


def test_params_travel_in_extra_body(model, fake_client):
    model("qwen/qwen3-32b")
    calls = fake_client()
    llm_client.chat_completion([{"role": "user", "content": "hi"}])
    assert calls[0]["extra_body"] == {"reasoning_format": "hidden"}
    assert "reasoning_format" not in calls[0]


def test_real_sdk_accepts_the_request_shape(model, monkeypatch):
    """Regression: top-level reasoning_format made the SDK raise TypeError."""
    model("qwen/qwen3-32b")
    client = OpenAI(api_key="x", base_url="http://127.0.0.1:9/v1", max_retries=0, timeout=0.5)
    monkeypatch.setattr(llm_client, "get_openai", lambda: client)
    from openai import APIConnectionError

    with pytest.raises(APIConnectionError):  # reached the network layer, not TypeError
        llm_client.chat_completion([{"role": "user", "content": "hi"}])


def test_reasoning_rejection_retries_without_params(model, fake_client):
    model("qwen/qwen3-32b")
    calls = fake_client([_bad_request("'reasoning_format' is not supported with this model")])
    assert llm_client.chat_completion([{"role": "user", "content": "hi"}]) == "ok"
    assert calls[0]["extra_body"] and "extra_body" not in calls[1]
    assert llm_client.reasoning_kwargs() == {}  # remembered for this model


def test_unrelated_400_is_raised_and_params_kept(model, fake_client):
    model("qwen/qwen3-32b")
    fake_client([_bad_request("Please reduce the length of the messages")])
    with pytest.raises(BadRequestError):
        llm_client.chat_completion([{"role": "user", "content": "hi"}])
    assert llm_client.reasoning_kwargs() == {"reasoning_format": "hidden"}
