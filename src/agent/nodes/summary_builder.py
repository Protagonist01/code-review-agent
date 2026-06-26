"""Summary builder node for the LangGraph review pipeline.

Aggregates all :class:`~src.agent.models.ReviewComment` objects from
``state["review_comments"]`` into a human-readable markdown summary and
determines the overall review severity.
"""

from __future__ import annotations

import structlog

from src.agent.models import ReviewComment
from src.agent.state import ReviewState
from src.config import settings

log = structlog.get_logger()

# Severity levels in descending order of importance
_SEVERITY_RANK: dict[str, int] = {"error": 2, "warning": 1, "info": 0}

# Emoji badges for overall severity
_SEVERITY_BADGE: dict[str, str] = {
    "error": "❌",
    "warning": "⚠️",
    "clean": "✅",
}


def _provider_label() -> str:
    """Return a human-readable label for the active LLM provider and model."""
    provider = settings.llm_provider
    provider_names = {
        "groq": "Groq",
        "ollama": "Ollama",
        "openai": "OpenAI",
        "openrouter": "OpenRouter",
        "anthropic": "Anthropic",
    }
    model_map: dict[str, str] = {
        "groq": settings.groq_model,
        "ollama": settings.ollama_model,
        "openai": settings.openai_model,
        "openrouter": settings.openrouter_model,
        "anthropic": settings.anthropic_model,
    }
    model = model_map.get(provider, "unknown model")
    return f"{provider_names.get(provider, provider.capitalize())} / {model}"


def _build_markdown(
    comments: list[ReviewComment],
    overall_severity: str,
    counts: dict[str, int],
) -> str:
    """Render the markdown summary string.

    Args:
        comments: All (already-filtered) review comments.
        overall_severity: One of ``"clean"``, ``"warning"``, ``"error"``.
        counts: Mapping of severity → count.

    Returns:
        A formatted markdown string suitable for posting as a PR comment.
    """
    badge = _SEVERITY_BADGE.get(overall_severity, "ℹ️")
    lines: list[str] = [
        "## 🤖 AI Code Review",
        "",
        f"{badge} **Overall status: {overall_severity.upper()}**",
        "",
        "| Severity | Count |",
        "| -------- | ----- |",
        f"| 🔴 Error   | {counts.get('error', 0)} |",
        f"| 🟡 Warning | {counts.get('warning', 0)} |",
        f"| 🔵 Info    | {counts.get('info', 0)} |",
        "",
    ]

    if not comments:
        lines.append("No issues found. 🎉")
    else:
        # Show top 10 most severe comments (errors first, then warnings, then info)
        top_comments = sorted(
            comments,
            key=lambda c: _SEVERITY_RANK.get(c.severity, 0),
            reverse=True,
        )[:10]

        lines.append("### Top findings")
        lines.append("")
        for c in top_comments:
            icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(c.severity, "•")
            lines.append(
                f"- {icon} **{c.severity.upper()}** `{c.file_path}:{c.line}` — {c.message}"
            )

        if len(comments) > 10:
            lines.append(f"- *… and {len(comments) - 10} more issue(s) (see inline comments)*")

    lines.append("")
    lines.append(f"*Reviewed by {_provider_label()}*")

    return "\n".join(lines)


async def summary_builder(state: ReviewState) -> dict[str, str]:
    """LangGraph node: build the markdown PR comment and determine overall severity.

    Reads ``state["review_comments"]``, counts issues by severity, chooses
    the overall severity level, and renders a structured markdown summary.

    Args:
        state: The current :class:`~src.agent.state.ReviewState`.

    Returns:
        A partial state update::

            {
                "summary": "<markdown string>",
                "severity": "clean" | "warning" | "error",
            }
    """
    comments: list[ReviewComment] = state.get("review_comments", [])

    # Count by severity
    counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for c in comments:
        if c.severity in counts:
            counts[c.severity] += 1

    # Determine overall severity
    if counts["error"] > 0:
        overall_severity = "error"
    elif counts["warning"] > 0:
        overall_severity = "warning"
    else:
        overall_severity = "clean"

    summary = _build_markdown(comments, overall_severity, counts)

    log.info(
        "summary_builder.complete",
        overall_severity=overall_severity,
        error_count=counts["error"],
        warning_count=counts["warning"],
        info_count=counts["info"],
        owner=state.get("owner"),
        repo=state.get("repo"),
        pr_number=state.get("pr_number"),
    )

    return {
        "summary": summary,
        "severity": overall_severity,
    }
