"""LangGraph state definition for the review pipeline."""

from __future__ import annotations

from typing import Literal, TypedDict

from src.agent.models import DiffHunk, RepoContext, ReviewComment


class ReviewState(TypedDict, total=False):
    """
    Typed state dict that flows through every node in the LangGraph pipeline.

    All fields are optional (total=False) so each node can safely add its
    outputs without needing to initialise unrelated keys.
    """

    # ── Inputs (set by the Celery task before graph invocation) ───────────────
    owner: str
    repo: str
    pr_number: int
    pr_sha: str
    installation_id: int | None  # None when using a PAT instead of GitHub App

    # ── diff_parser output ────────────────────────────────────────────────────
    raw_diff: str
    hunks: list[DiffHunk]

    # ── context_fetcher output ────────────────────────────────────────────────
    repo_context: RepoContext

    # ── llm_reviewer output ───────────────────────────────────────────────────
    review_comments: list[ReviewComment]

    # ── summary_builder output ────────────────────────────────────────────────
    summary: str
    severity: Literal["clean", "warning", "error"]

    # ── error handling ────────────────────────────────────────────────────────
    error: str | None
    retry_count: int
