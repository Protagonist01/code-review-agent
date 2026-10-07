from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import settings

SECRET = "integration-test-secret"


def make_sig(payload: bytes) -> str:
    """Return a valid sha256 HMAC signature string for *payload*."""
    digest = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def pr_payload(
    action: str = "opened",
    pr_number: int = 1,
    sha: str = "abc123",
    owner: str = "org",
    repo: str = "repo",
) -> bytes:
    """Build a minimal GitHub pull_request event payload."""
    return json.dumps(
        {
            "action": action,
            "pull_request": {"number": pr_number, "head": {"sha": sha}},
            "repository": {"name": repo, "owner": {"login": owner}},
            "installation": {"id": 999},
        }
    ).encode()


@pytest.fixture
def client(monkeypatch):
    """TestClient with settings patched and heavy dependencies mocked."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)

    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=False)
    claimed = set()

    async def claim(key, value, **kwargs):
        if key in claimed:
            return False
        claimed.add(key)
        return True

    mock_redis.set = AsyncMock(side_effect=claim)
    mock_task = MagicMock()
    mock_task.delay = MagicMock()

    with (
        patch("src.api.app._redis", mock_redis),
        patch("src.api.webhook.review_pr", mock_task),
    ):
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def test_valid_opened_pr_returns_202(client) -> None:
    """A correctly signed opened PR event should receive HTTP 202 Accepted."""
    payload = pr_payload(action="opened")
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": make_sig(payload),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 202


def test_invalid_signature_returns_403(client) -> None:
    """A request with a bad signature should be rejected with HTTP 403."""
    payload = pr_payload()
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=badhash",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 403


def test_non_pr_event_returns_200(client) -> None:
    """Non-pull_request events (e.g. ping) should be acknowledged with HTTP 200."""
    payload = b'{"zen": "Keep it logically awesome"}'
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": make_sig(payload),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200


def test_closed_pr_action_ignored(client) -> None:
    """A 'closed' PR action should not trigger a review (HTTP 200, not 202)."""
    payload = pr_payload(action="closed")
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": make_sig(payload),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200


def test_synchronize_action_accepted(client) -> None:
    """A 'synchronize' PR action (new push to PR) should trigger a review (HTTP 202)."""
    payload = pr_payload(action="synchronize")
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": make_sig(payload),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 202


def test_reopened_action_accepted(client) -> None:
    """A 'reopened' PR action should trigger a review (HTTP 202)."""
    payload = pr_payload(action="reopened")
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": make_sig(payload),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 202


def test_health_endpoint(client) -> None:
    """The /health endpoint should return HTTP 200 with status=ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_metrics_endpoint_returns_prometheus_format(client) -> None:
    """The /metrics endpoint should return Prometheus-formatted text."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "review_duration_seconds" in resp.text


def test_missing_event_header_handled(client) -> None:
    """Requests missing the X-GitHub-Event header should be handled gracefully."""
    payload = pr_payload()
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-Hub-Signature-256": make_sig(payload),
            "Content-Type": "application/json",
        },
    )
    # Should not 500; 400 or 422 is acceptable
    assert resp.status_code in (200, 400, 422)


def test_duplicate_delivery_idempotent(client) -> None:
    """The same delivery sent twice should not trigger a second review job."""
    payload = pr_payload(action="opened", pr_number=99)
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": make_sig(payload),
        "Content-Type": "application/json",
        "X-GitHub-Delivery": "unique-delivery-id-1234",
    }
    resp1 = client.post("/webhook", content=payload, headers=headers)
    # Second delivery with the same ID should be idempotent
    resp2 = client.post("/webhook", content=payload, headers=headers)
    assert resp1.status_code == 202
    assert resp2.status_code == 200


@pytest.mark.parametrize("payload", [b"{", b"[]", b'{"action":"opened"}'])
def test_invalid_payload_returns_400(client, payload):
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": make_sig(payload),
        },
    )
    assert response.status_code == 400


def test_enqueue_failure_releases_claim(client):
    payload = pr_payload()
    with (
        patch("src.api.webhook.review_pr.delay", side_effect=RuntimeError("broker down")),
        patch("src.api.app._redis.delete", new_callable=AsyncMock) as delete,
    ):
        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": make_sig(payload),
            },
        )
    assert response.status_code == 503
    delete.assert_awaited_once_with("review:org:repo:1:abc123")


def test_payload_limit_applies_to_streamed_body(client, monkeypatch):
    monkeypatch.setattr(settings, "max_webhook_bytes", 10)
    response = client.post("/webhook", content=b"x" * 11)
    assert response.status_code == 413


def test_unicode_signature_is_rejected_without_server_error(client):
    response = client.post(
        "/webhook", content=b"{}", headers=[(b"X-Hub-Signature-256", b"sha256=\xff")]
    )
    assert response.status_code == 403


def test_readiness_reports_redis_failure(client):
    with patch("src.api.app._redis.ping", side_effect=RuntimeError("down")):
        assert client.get("/ready").status_code == 503
    assert client.get("/ready").status_code == 200


def test_broker_and_cleanup_failure_still_return_503(client):
    with (
        patch("src.api.webhook.review_pr.delay", side_effect=RuntimeError("broker down")),
        patch("src.api.app._redis.delete", side_effect=RuntimeError("redis down")),
    ):
        payload = pr_payload()
        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": make_sig(payload),
            },
        )
    assert response.status_code == 503


def test_redis_failure_returns_503_without_dispatch(client):
    with (
        patch("src.api.app._redis.set", side_effect=RuntimeError("redis down")),
        patch("src.api.webhook.review_pr.delay") as dispatch,
    ):
        payload = pr_payload()
        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": make_sig(payload),
            },
        )
    assert response.status_code == 503
    dispatch.assert_not_called()
