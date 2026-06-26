"""LLM backend abstraction for the AI Code Review Agent.

Defines a Protocol for LLM backends and concrete implementations
backed by LangChain integrations (OpenRouter, Groq, Ollama, OpenAI,
Anthropic).
"""

from __future__ import annotations

from typing import Protocol, cast, runtime_checkable

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from src.config import settings

log = structlog.get_logger()


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol that every LLM backend must satisfy."""

    async def complete(self, prompt: str, system: str) -> str:
        """Send a prompt to the LLM and return its text response.

        Args:
            prompt: The user-facing prompt (human message).
            system: The system instruction message.

        Returns:
            The model's text response as a plain string.
        """
        ...


class GroqBackend:
    """LangChain-backed Groq LLM client."""

    def __init__(self) -> None:
        """Initialise ChatGroq with settings from config."""
        self._client = ChatGroq(
            api_key=settings.groq_api_key,  # type: ignore[arg-type]
            model=settings.groq_model,
            temperature=0,
        )

    async def complete(self, prompt: str, system: str) -> str:
        """Send messages to Groq and return the response text."""
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        response = await self._client.ainvoke(messages)
        return str(response.content)


class OllamaBackend:
    """LangChain-backed Ollama LLM client (local inference)."""

    def __init__(self) -> None:
        """Initialise ChatOllama with settings from config."""
        self._client = ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0,
        )

    async def complete(self, prompt: str, system: str) -> str:
        """Send messages to Ollama and return the response text."""
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        response = await self._client.ainvoke(messages)
        return str(response.content)


class OpenAIBackend:
    """LangChain-backed OpenAI LLM client."""

    def __init__(self) -> None:
        """Initialise ChatOpenAI with settings from config."""
        self._client = ChatOpenAI(
            api_key=settings.openai_api_key,  # type: ignore[arg-type]
            model=settings.openai_model,
            temperature=0,
        )

    async def complete(self, prompt: str, system: str) -> str:
        """Send messages to OpenAI and return the response text."""
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        response = await self._client.ainvoke(messages)
        return str(response.content)


class OpenRouterBackend:
    """OpenAI-compatible OpenRouter LLM client."""

    def __init__(self) -> None:
        """Initialise ChatOpenAI against OpenRouter's OpenAI-compatible API."""
        headers = {"X-Title": settings.openrouter_app_name}
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url

        self._client = ChatOpenAI(
            api_key=settings.openrouter_api_key,  # type: ignore[arg-type]
            base_url=settings.openrouter_base_url,
            default_headers=headers,
            model=settings.openrouter_model,
            temperature=0,
        )

    async def complete(self, prompt: str, system: str) -> str:
        """Send messages to OpenRouter and return the response text."""
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        response = await self._client.ainvoke(messages)
        return str(response.content)


class AnthropicBackend:
    """LangChain-backed Anthropic (Claude) LLM client."""

    def __init__(self) -> None:
        """Initialise ChatAnthropic with settings from config."""
        self._client = ChatAnthropic(  # type: ignore[call-arg]
            api_key=settings.anthropic_api_key,  # type: ignore[arg-type]
            model=settings.anthropic_model,
            temperature=0,
        )

    async def complete(self, prompt: str, system: str) -> str:
        """Send messages to Anthropic and return the response text."""
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        response = await self._client.ainvoke(messages)
        return str(response.content)


# Registry mapping provider name → backend class
_BACKENDS: dict[str, type] = {
    "groq": GroqBackend,
    "ollama": OllamaBackend,
    "openai": OpenAIBackend,
    "openrouter": OpenRouterBackend,
    "anthropic": AnthropicBackend,
}


def get_llm_backend() -> LLMBackend:
    """Instantiate and return the configured LLM backend.

    Reads ``settings.llm_provider`` to decide which concrete backend
    to construct.

    Returns:
        A ready-to-use :class:`LLMBackend` instance.

    Raises:
        ValueError: If the configured provider name is not recognised.
    """
    cls = _BACKENDS.get(settings.llm_provider)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider!r}")
    log.info("llm_backend.init", provider=settings.llm_provider)
    return cast(LLMBackend, cls())
