"""GitHub webhook endpoint.

Responsibilities
----------------
1. **HMAC-SHA256 verification** — rejects requests whose ``X-Hub-Signature-256``
   header does not match the shared secret from ``settings.github_webhook_secret``.
2. **Event / action filtering** — only ``pull_request`` events with
   ``opened``, ``synchronize``, or ``reopened`` actions proceed further.
3. **Deduplication** — skips re-queuing if a review for the same commit SHA is
   already in Redis (TTL: 1 hour).
4. **Task enqueueing** — dispatches a ``review_pr`` Celery task and returns
   ``202 Accepted`` immediately so GitHub does not time out.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, Response

from src.api.metrics import WEBHOOK_ERRORS
from src.config import settings
from src.worker import review_pr

log = structlog.get_logger()
router = APIRouter()


# ── HMAC helpers ──────────────────────────────────────────────────────────────


def verify_github_signature(payload: bytes, signature_header: str | None) -> bool:
    """Verify the HMAC-SHA256 webhook signature supplied by GitHub.

    GitHub signs every webhook payload with the configured secret and sends
    the hex digest as ``sha256=<hex>`` in the ``X-Hub-Signature-256`` header.

    Args:
        payload: Raw request body bytes.
        signature_header: Value of the ``X-Hub-Signature-256`` request header,
            or ``None`` if the header was absent.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    if not settings.github_webhook_secret:
        log.warning("webhook.secret_not_configured")
        return False
    expected = hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


# ── Route ─────────────────────────────────────────────────────────────────────


@router.post("/webhook")
async def github_webhook(request: Request) -> Response:
    """Receive and validate GitHub webhook events, then enqueue a review job.

    Returns:
        * ``403`` — invalid or missing HMAC signature.
        * ``200`` — event/action is ignored (not a relevant PR event).
        * ``202`` — review job successfully enqueued.

    Raises:
        HTTPException: With status 403 on signature failure.
    """
    payload_bytes = await request.body()

    # ── HMAC auth ─────────────────────────────────────────────────────────────
    sig = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature(payload_bytes, sig):
        WEBHOOK_ERRORS.labels(error_type="auth_failure").inc()
        log.warning(
            "webhook.auth_failure",
            ip=request.client.host if request.client else "unknown",
        )
        raise HTTPException(status_code=403, detail="Invalid signature")

    # ── Event filter ──────────────────────────────────────────────────────────
    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type != "pull_request":
        log.info("webhook.ignored_event", event_type=event_type or "unknown")
        return Response(content="Event ignored", status_code=200)

    payload: dict[str, Any] = await request.json()
    action: str = payload.get("action", "")
    if action not in {"opened", "synchronize", "reopened"}:
        log.info("webhook.ignored_action", event_type=event_type, action=action or "unknown")
        return Response(content="Action ignored", status_code=200)

    # ── Extract PR metadata ───────────────────────────────────────────────────
    pr = payload["pull_request"]
    pr_number: int = pr["number"]
    pr_sha: str = pr["head"]["sha"]
    owner: str = payload["repository"]["owner"]["login"]
    repo: str = payload["repository"]["name"]
    installation_id: int | None = payload.get("installation", {}).get("id")

    log.info(
        "webhook.received",
        action=action,
        owner=owner,
        repo=repo,
        pr=pr_number,
        sha=pr_sha[:7],
    )

    # ── Deduplication (skip if same SHA already queued) ───────────────────────
    from src.api.app import get_redis  # local import avoids circular dependency

    redis = get_redis()
    dedup_key = f"review:{owner}:{repo}:{pr_sha}"
    if await redis.exists(dedup_key):
        log.info("webhook.deduplicated", dedup_key=dedup_key)
        return Response(content="Already queued", status_code=200)
    await redis.setex(dedup_key, 3600, "1")  # expire after 1 h

    # ── Enqueue review task ───────────────────────────────────────────────────
    review_pr.delay(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        pr_sha=pr_sha,
        installation_id=installation_id,
    )

    return Response(content="Review enqueued", status_code=202)
