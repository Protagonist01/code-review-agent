from __future__ import annotations

import pytest

from src.agent import llm_backend
from src.config import settings


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChat:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return FakeResponse("review response")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backend_cls", "chat_attr"),
    [
        (llm_backend.GroqBackend, "ChatGroq"),
        (llm_backend.OllamaBackend, "ChatOllama"),
        (llm_backend.OpenAIBackend, "ChatOpenAI"),
        (llm_backend.OpenRouterBackend, "ChatOpenAI"),
        (llm_backend.AnthropicBackend, "ChatAnthropic"),
    ],
)
async def test_backend_complete_uses_system_and_human_messages(
    monkeypatch,
    backend_cls,
    chat_attr: str,
) -> None:
    monkeypatch.setattr(llm_backend, chat_attr, FakeChat)

    backend = backend_cls()
    result = await backend.complete("review this hunk", "be precise")

    assert result == "review response"
    assert backend._client.messages[0].content == "be precise"
    assert backend._client.messages[1].content == "review this hunk"
    assert backend._client.kwargs["temperature"] == 0


def test_openrouter_backend_uses_openrouter_settings(monkeypatch) -> None:
    monkeypatch.setattr(llm_backend, "ChatOpenAI", FakeChat)
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-openrouter-test-key")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "openrouter_model", "cohere/north-mini-code:free")
    monkeypatch.setattr(settings, "openrouter_site_url", "https://example.com")
    monkeypatch.setattr(settings, "openrouter_app_name", "Code Review Agent")

    backend = llm_backend.OpenRouterBackend()

    assert backend._client.kwargs["api_key"] == "fake-openrouter-test-key"
    assert backend._client.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert backend._client.kwargs["model"] == "cohere/north-mini-code:free"
    assert backend._client.kwargs["default_headers"] == {
        "HTTP-Referer": "https://example.com",
        "X-Title": "Code Review Agent",
    }


def test_get_llm_backend_instantiates_configured_provider(monkeypatch) -> None:
    class DummyBackend:
        async def complete(self, prompt: str, system: str) -> str:
            return f"{system}: {prompt}"

    monkeypatch.setitem(llm_backend._BACKENDS, "dummy", DummyBackend)
    monkeypatch.setattr(settings, "llm_provider", "dummy")

    assert isinstance(llm_backend.get_llm_backend(), DummyBackend)


def test_get_llm_backend_rejects_unknown_provider(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "missing")

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        llm_backend.get_llm_backend()
