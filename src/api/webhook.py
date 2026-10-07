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
import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from src.api.metrics import WEBHOOK_ERRORS, WEBHOOK_REQUESTS
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
    provided = signature_header[len("sha256=") :]
    return hmac.compare_digest(expected.encode("ascii"), provided.encode("utf-8"))


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
    WEBHOOK_REQUESTS.inc()
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > settings.max_webhook_bytes:
            WEBHOOK_ERRORS.labels(error_type="payload_too_large").inc()
            raise HTTPException(status_code=413, detail="Webhook payload too large")
    payload_bytes = bytes(payload)

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

    try:
        data: dict[str, Any] = json.loads(payload_bytes)
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
    except ValueError as exc:
        WEBHOOK_ERRORS.labels(error_type="invalid_payload").inc()
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    action: str = data.get("action", "")
    if not isinstance(action, str) or action not in {"opened", "synchronize", "reopened"}:
        log.info("webhook.ignored_action", event_type=event_type, action=action or "unknown")
        return Response(content="Action ignored", status_code=200)

    # ── Extract PR metadata ───────────────────────────────────────────────────
    try:
        pr = data["pull_request"]
        pr_number: int = pr["number"]
        pr_sha: str = pr["head"]["sha"]
        owner: str = data["repository"]["owner"]["login"]
        repo: str = data["repository"]["name"]
        installation_id: int | None = data.get("installation", {}).get("id")
        if not all(isinstance(value, str) and value for value in (owner, repo, pr_sha)):
            raise TypeError("Invalid identifiers")
        if type(pr_number) is not int or pr_number < 1:
            raise TypeError("Invalid PR number")
        if installation_id is not None and (
            type(installation_id) is not int or installation_id < 1
        ):
            raise TypeError("Invalid installation")
    except (KeyError, TypeError, AttributeError) as exc:
        WEBHOOK_ERRORS.labels(error_type="invalid_payload").inc()
        raise HTTPException(status_code=400, detail="Invalid PR payload") from exc

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
    dedup_key = f"review:{owner}:{repo}:{pr_number}:{pr_sha}"
    try:
        claimed = await redis.set(dedup_key, "1", nx=True, ex=3600)
    except Exception as exc:
        WEBHOOK_ERRORS.labels(error_type="redis_unavailable").inc()
        raise HTTPException(status_code=503, detail="Queue unavailable") from exc
    if not claimed:
        return Response(content="Already queued", status_code=200)
    try:
        await run_in_threadpool(
            review_pr.delay,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            pr_sha=pr_sha,
            installation_id=installation_id,
        )
    except Exception as exc:
        WEBHOOK_ERRORS.labels(error_type="dispatch_failure").inc()
        try:
            await redis.delete(dedup_key)
        except Exception:
            log.exception("webhook.claim_release_failed")
        raise HTTPException(status_code=503, detail="Queue unavailable") from exc
    return Response(content="Review enqueued", status_code=202)
