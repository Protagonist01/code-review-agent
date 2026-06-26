"""LLM reviewer node for the LangGraph review pipeline.

Calls the configured LLM backend for every :class:`~src.agent.models.DiffHunk`
concurrently (capped at 5 parallel requests) and immediately parses the raw
responses into :class:`~src.agent.models.ReviewComment` objects using
:func:`~src.agent.nodes.response_parser.parse_llm_response`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from src.agent.llm_backend import get_llm_backend
from src.agent.models import DiffHunk, ReviewComment
from src.agent.nodes.prompt_builder import build_hunk_prompt
from src.agent.nodes.response_parser import parse_llm_response
from src.agent.state import ReviewState

log = structlog.get_logger()

# Maximum number of concurrent LLM calls
_MAX_CONCURRENCY = 5

# Per-hunk LLM call timeout in seconds
_HUNK_TIMEOUT_SECONDS = 30.0


async def _review_hunk(
    hunk: DiffHunk,
    backend: Any,
    semaphore: asyncio.Semaphore,
    context: Any,
) -> list[ReviewComment]:
    """Review a single hunk via the LLM backend.

    Acquires ``semaphore`` before making the LLM call so we never exceed
    ``_MAX_CONCURRENCY`` parallel requests.  Times out after
    ``_HUNK_TIMEOUT_SECONDS`` and returns an empty list on timeout or any
    unexpected exception.

    Args:
        hunk: The :class:`~src.agent.models.DiffHunk` to review.
        backend: An :class:`~src.agent.llm_backend.LLMBackend` instance.
        semaphore: Concurrency limiter shared across all hunk tasks.
        context: The :class:`~src.agent.models.RepoContext` for prompt assembly.

    Returns:
        A list of :class:`~src.agent.models.ReviewComment` objects (may be empty).
    """
    async with semaphore:
        system_prompt, user_prompt = build_hunk_prompt(hunk, context)
        try:
            raw_response = await asyncio.wait_for(
                backend.complete(user_prompt, system_prompt),
                timeout=_HUNK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log.error(
                "llm_reviewer.hunk_timeout",
                file_path=hunk.file_path,
                hunk_header=hunk.hunk_header,
                timeout_seconds=_HUNK_TIMEOUT_SECONDS,
            )
            return []
        except Exception as exc:  # noqa: BLE001
            log.error(
                "llm_reviewer.hunk_error",
                file_path=hunk.file_path,
                hunk_header=hunk.hunk_header,
                error=str(exc),
                exc_info=True,
            )
            return []

        log.debug(
            "llm_reviewer.hunk_complete",
            file_path=hunk.file_path,
            response_chars=len(raw_response),
        )
        return parse_llm_response(raw_response, hunk)


async def llm_reviewer(state: ReviewState) -> dict[str, list[ReviewComment]]:
    """LangGraph node: review all diff hunks concurrently via the LLM backend.

    For each :class:`~src.agent.models.DiffHunk` in ``state["hunks"]``:

    1. Builds a prompt using :func:`~src.agent.nodes.prompt_builder.build_hunk_prompt`.
    2. Calls the backend with a 30-second timeout.
    3. Parses the raw response into :class:`~src.agent.models.ReviewComment` objects.

    All hunk tasks run concurrently but are throttled to at most 5 parallel
    LLM calls via an :class:`asyncio.Semaphore`.

    Args:
        state: The current :class:`~src.agent.state.ReviewState`.

    Returns:
        A partial state update: ``{"review_comments": list[ReviewComment]}``.
    """
    hunks: list[DiffHunk] = state.get("hunks", [])
    retry_count: int = state.get("retry_count", 0)

    if retry_count > 0:
        log.info(
            "llm_reviewer.retry",
            retry_count=retry_count,
            hunk_count=len(hunks),
        )

    if not hunks:
        log.info("llm_reviewer.no_hunks")
        return {"review_comments": []}

    from src.agent.models import RepoContext  # noqa: PLC0415

    context = state.get("repo_context", RepoContext())

    backend = get_llm_backend()
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    tasks = [
        _review_hunk(hunk, backend, semaphore, context)
        for hunk in hunks
    ]

    results: list[list[ReviewComment]] = await asyncio.gather(*tasks)

    all_comments: list[ReviewComment] = [
        comment
        for hunk_comments in results
        for comment in hunk_comments
    ]

    log.info(
        "llm_reviewer.complete",
        hunk_count=len(hunks),
        total_comments=len(all_comments),
        owner=state.get("owner"),
        repo=state.get("repo"),
        pr_number=state.get("pr_number"),
    )

    return {"review_comments": all_comments}
