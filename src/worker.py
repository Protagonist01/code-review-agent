"""Celery entry point for revision-aware GitHub pull-request reviews.

Reserve one task per process. Compose sets concurrency to one; prefetch alone
is not a concurrency limit. Retry failures up to three times with backoff.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

import structlog
from celery import Celery

from src.config import settings

log = structlog.get_logger()
celery_app = Celery("code_review_agent", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_routes={"src.worker.review_pr": {"queue": "reviews"}},
)


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
    """Bridge the synchronous Celery task into the async review pipeline."""
    return asyncio.run(_run_review(owner, repo, pr_number, pr_sha, installation_id))


async def _run_review(
    owner: str,
    repo: str,
    pr_number: int,
    pr_sha: str,
    installation_id: int | None,
) -> dict[str, object]:
    from src.agent.graph import review_graph
    from src.api.metrics import ACTIVE_REVIEWS, COMMENTS_POSTED, REVIEW_DURATION, REVIEWS_COMPLETED
    from src.github_client.client import GitHubClient

    ACTIVE_REVIEWS.inc()
    start = time.perf_counter()
    try:
        async with GitHubClient(installation_id=installation_id) as client:
            try:
                log.info("review.start", owner=owner, repo=repo, pr=pr_number, sha=pr_sha[:7])
                await client.set_commit_status(
                    owner, repo, pr_sha, "pending", "AI review in progress"
                )
                metadata = await client.get_pull_request(owner, repo, pr_number)
                if metadata["head"]["sha"] != pr_sha:
                    await client.set_commit_status(
                        owner, repo, pr_sha, "error", "Review superseded by a newer commit"
                    )
                    return {"status": "superseded", "severity": "error", "comment_count": 0}
                raw_diff = await client.get_diff(owner, repo, pr_number)
                metadata = await client.get_pull_request(owner, repo, pr_number)
                if metadata["head"]["sha"] != pr_sha:
                    await client.set_commit_status(
                        owner, repo, pr_sha, "error", "PR changed while fetching diff"
                    )
                    return {"status": "superseded", "severity": "error", "comment_count": 0}
                final_state = await review_graph.ainvoke(
                    {
                        "owner": owner,
                        "repo": repo,
                        "pr_number": pr_number,
                        "pr_sha": pr_sha,
                        "installation_id": installation_id,
                        "raw_diff": raw_diff,
                    }
                )
                if not final_state.get("hunks"):
                    await client.set_commit_status(
                        owner, repo, pr_sha, "error", "Skipped: no reviewable diff hunks"
                    )
                    return {"status": "skipped", "severity": "error", "comment_count": 0}
                comments = final_state["review_comments"]
                summary = final_state["summary"]
                severity = final_state["severity"]
                metadata = await client.get_pull_request(owner, repo, pr_number)
                if metadata["head"]["sha"] != pr_sha:
                    await client.set_commit_status(
                        owner, repo, pr_sha, "error", "PR changed during review"
                    )
                    return {"status": "superseded", "severity": "error", "comment_count": 0}
                await client.post_review(owner, repo, pr_number, pr_sha, comments, summary)
                status_map: dict[str, tuple[Literal["success", "failure"], str]] = {
                    "clean": ("success", "No findings above the configured severity threshold"),
                    "warning": ("success", "Review complete: warnings found"),
                    "error": ("failure", "Review complete: errors found"),
                }
                gh_state, description = status_map[severity]
                await client.set_commit_status(owner, repo, pr_sha, gh_state, description)
                for comment in comments:
                    COMMENTS_POSTED.labels(severity=comment.severity).inc()
                duration = time.perf_counter() - start
                REVIEW_DURATION.observe(duration)
                REVIEWS_COMPLETED.inc()
                log.info(
                    "review.complete",
                    owner=owner,
                    repo=repo,
                    pr=pr_number,
                    severity=severity,
                    comment_count=len(comments),
                    duration_s=round(duration, 2),
                )
                return {"status": "ok", "severity": severity, "comment_count": len(comments)}
            except Exception:
                log.exception("review.failed", owner=owner, repo=repo, pr=pr_number)
                try:
                    await client.set_commit_status(
                        owner, repo, pr_sha, "error", "Review failed: see worker logs"
                    )
                except Exception:
                    log.exception("review.error_status_failed", pr=pr_number)
                raise
    finally:
        ACTIVE_REVIEWS.dec()
