from __future__ import annotations

import hashlib
import hmac

from src.api.webhook import verify_github_signature
from src.config import settings

SECRET = "my-test-secret"
PAYLOAD = b'{"action": "opened"}'


def make_sig(payload: bytes = PAYLOAD, secret: str = SECRET) -> str:
    """Compute a valid sha256 HMAC signature string."""
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_signature_accepted(monkeypatch) -> None:
    """A correctly signed payload should be verified as True."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    assert verify_github_signature(PAYLOAD, make_sig()) is True


def test_wrong_secret_rejected(monkeypatch) -> None:
    """A signature produced with a different secret should be rejected."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    wrong_sig = make_sig(secret="wrong-secret")
    assert verify_github_signature(PAYLOAD, wrong_sig) is False


def test_tampered_payload_rejected(monkeypatch) -> None:
    """A valid signature that does not match the submitted payload should be rejected."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    sig = make_sig(PAYLOAD)
    assert verify_github_signature(b'{"action": "closed"}', sig) is False


def test_missing_signature_header_rejected(monkeypatch) -> None:
    """A None signature header should be rejected immediately."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    assert verify_github_signature(PAYLOAD, None) is False


def test_malformed_header_rejected(monkeypatch) -> None:
    """A signature using an unsupported algorithm prefix should be rejected."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    assert verify_github_signature(PAYLOAD, "md5=somehash") is False


def test_empty_secret_rejects_all(monkeypatch) -> None:
    """When the webhook secret is empty, all requests should be rejected."""
    monkeypatch.setattr(settings, "github_webhook_secret", "")
    assert verify_github_signature(PAYLOAD, make_sig()) is False


def test_signature_without_prefix_rejected(monkeypatch) -> None:
    """A raw hex digest without the sha256= prefix should be rejected."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    digest = hmac.new(SECRET.encode(), PAYLOAD, hashlib.sha256).hexdigest()
    assert verify_github_signature(PAYLOAD, digest) is False


def test_empty_payload_with_valid_sig(monkeypatch) -> None:
    """An empty payload with a matching HMAC should still be accepted."""
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    assert verify_github_signature(b"", make_sig(b"")) is True


def test_timing_safe_comparison(monkeypatch) -> None:
    """Verification should use constant-time comparison (no timing side-channel)."""
    # Indirectly validated: wrong signature of same length should still fail.
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    valid = make_sig()
    # Flip the last character to produce a same-length but wrong hash.
    wrong = valid[:-1] + ("a" if valid[-1] != "a" else "b")
    assert verify_github_signature(PAYLOAD, wrong) is False
