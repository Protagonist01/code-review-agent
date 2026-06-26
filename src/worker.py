"""Celery worker that drives the full AI code-review pipeline.

Architecture
------------
* The ``review_pr`` task is the single entry-point for all review jobs.
* It uses :func:`asyncio.run` to bridge Celery's synchronous task execution
  model into the async LangGraph pipeline.
* One task is processed per worker at a time (``worker_prefetch_multiplier=1``)
  to avoid saturating the LLM API or GitHub rate limits.
* Tasks are auto-retried up to 3 times with exponential back-off on any
  unhandled exception.

Running
-------
Start a worker from the project root::

    celery -A src.worker worker --loglevel=info -Q reviews

"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from celery import Celery

from src.config import settings

log = structlog.get_logger()

# ── Celery application ────────────────────────────────────────────────────────

celery_app = Celery(
    "code_review_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Only acknowledge a task after it has completed successfully.
    # This prevents message loss if a worker dies mid-execution.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Process one task at a time per worker to respect LLM/GitHub rate limits.
    worker_prefetch_multiplier=1,
    task_routes={
        "src.worker.review_pr": {"queue": "reviews"},
    },
)


# ── Task definition ───────────────────────────────────────────────────────────


@celery_app.task(  # type: ignore[untyped-decorator]
    name="src.worker.review_pr",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def review_pr(
    self: Any,
    owner: str,
    repo: str,
    pr_number: int,
    pr_sha: str,
    installation_id: int | None,
) -> dict[str, object]:
    """Celery task: run the full LangGraph review pipeline for a pull request.

    Uses :func:`asyncio.run` to bridge the synchronous Celery execution
    context into the async code path.

    Args:
        owner: Repository owner login (user or org).
        repo: Repository name.
        pr_number: Pull-request number.
        pr_sha: Head commit SHA of the PR.
        installation_id: GitHub App installation ID, or ``None`` when using
            a PAT (``GITHUB_TOKEN``).

    Returns:
        A dict with keys ``status``, ``severity``, and ``comment_count``.

    Raises:
        Exception: Any unhandled error is re-raised so Celery can retry the
            task according to the ``autoretry_for`` / ``max_retries`` config.
    """
    return asyncio.run(
        _run_review(owner, repo, pr_number, pr_sha, installation_id)
    )


# ── Async implementation ──────────────────────────────────────────────────────


async def _run_review(
    owner: str,
    repo: str,
    pr_number: int,
    pr_sha: str,
    installation_id: int | None,
) -> dict[str, object]:
    """Async core of the review pipeline.

    Steps
    ~~~~~
    1. Set the PR commit status to ``pending``.
    2. Fetch the unified diff via the GitHub API.
    3. Run the LangGraph ``review_graph`` pipeline.
    4. Post the generated review comments + summary back to GitHub.
    5. Update Prometheus metrics.
    6. Set the final commit status (``success`` / ``failure``).

    Args:
        owner: Repository owner login.
        repo: Repository name.
        pr_number: Pull-request number.
        pr_sha: Head commit SHA.
        installation_id: GitHub App installation ID (may be ``None``).

    Returns:
        Result dict with ``status``, ``severity``, and ``comment_count``.
    """
    # Defer heavy imports to keep worker startup fast.
    from src.agent.graph import review_graph  # noqa: PLC0415
    from src.api.metrics import ACTIVE_REVIEWS, COMMENTS_POSTED, REVIEW_DURATION  # noqa: PLC0415
    from src.github_client.client import GitHubClient  # noqa: PLC0415

    ACTIVE_REVIEWS.inc()
    start = time.perf_counter()

    try:
        async with GitHubClient(installation_id=installation_id) as client:
            log.info(
                "review.start",
                owner=owner,
                repo=repo,
                pr=pr_number,
                sha=pr_sha[:7],
            )

            # ── 1. Mark PR as under review ────────────────────────────────────
            await client.set_commit_status(
                owner, repo, pr_sha, "pending", "AI review in progress…"
            )

            # ── 2. Fetch diff ─────────────────────────────────────────────────
            raw_diff = await client.get_diff(owner, repo, pr_number)

            # ── 3. Run LangGraph pipeline ─────────────────────────────────────
            initial_state: dict[str, object] = {
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "pr_sha": pr_sha,
                "installation_id": installation_id,
                "raw_diff": raw_diff,
                "retry_count": 0,
                "error": None,
            }
            try:
                final_state: dict[str, Any] = await review_graph.ainvoke(initial_state)
            except Exception as pipeline_exc:
                log.exception(
                    "review.pipeline_failed",
                    owner=owner,
                    repo=repo,
                    pr=pr_number,
                    error=str(pipeline_exc),
                )
                await client.set_commit_status(
                    owner,
                    repo,
                    pr_sha,
                    "error",
                    "Review failed — see worker logs",
                )
                raise

            comments = final_state.get("review_comments", [])
            summary: str = final_state.get("summary", "No summary generated.")
            severity: str = final_state.get("severity", "clean")

            # ── 4. Post review to GitHub ──────────────────────────────────────
            if comments or summary:
                await client.post_review(
                    owner, repo, pr_number, pr_sha, comments, summary
                )

            # ── 5. Update Prometheus metrics ──────────────────────────────────
            for comment in comments:
                COMMENTS_POSTED.labels(severity=comment.severity).inc()

            # ── 6. Set final commit status ────────────────────────────────────
            status_map: dict[str, tuple[str, str]] = {
                "clean": ("success", "✅ No issues found"),
                "warning": ("success", "⚠️ Review complete — warnings found"),
                "error": ("failure", "❌ Review complete — errors found"),
            }
            gh_state, description = status_map.get(
                severity, ("success", "Review complete")
            )
            await client.set_commit_status(owner, repo, pr_sha, gh_state, description)  # type: ignore[arg-type]

            duration = time.perf_counter() - start
            REVIEW_DURATION.observe(duration)
            log.info(
                "review.complete",
                owner=owner,
                repo=repo,
                pr=pr_number,
                severity=severity,
                comment_count=len(comments),
                duration_s=round(duration, 2),
            )
            return {
                "status": "ok",
                "severity": severity,
                "comment_count": len(comments),
            }

    finally:
        ACTIVE_REVIEWS.dec()
