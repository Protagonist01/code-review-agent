from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── GitHub App ─────────────────────────────────────────────────────────────
    github_app_id: int | None = None
    github_private_key_path: str = "keys/private-key.pem"
    github_webhook_secret: str = ""
    # Simple PAT for local dev (alternative to full App auth)
    github_token: str | None = None

    # ── LLM Backend ────────────────────────────────────────────────────────────
    llm_provider: Literal["groq", "ollama", "openai", "anthropic", "openrouter"] = (
        "openrouter"
    )

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "codellama:7b"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "cohere/north-mini-code:free"
    openrouter_site_url: str | None = None
    openrouter_app_name: str = "code-review-agent"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"

    # ── Redis ──────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── API ────────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Review Policy ──────────────────────────────────────────────────────────
    # Diffs larger than this are summarised and skipped
    max_diff_lines: int = 1500
    # Comments below this severity threshold are not posted
    min_comment_severity: Literal["info", "warning", "error"] = "warning"

    # ── Observability ──────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("github_webhook_secret", mode="before")
    @classmethod
    def _coerce_none_to_empty(cls, v: object) -> str:
        """Allow None / unset; runtime validation happens in the HMAC verifier."""
        return str(v) if v is not None else ""


# Module-level singleton — import this everywhere
settings = Settings()
