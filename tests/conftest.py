from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio  # noqa: F401 – registers asyncio mode

from src.agent.models import DiffHunk, RepoContext, ReviewComment
from src.config import settings

# ── Diff fixtures ──────────────────────────────────────────────────────────────

SIMPLE_DIFF = """diff --git a/src/calculator.py b/src/calculator.py
index abc123..def456 100644
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -10,7 +10,10 @@ def divide(a, b):
     \"\"\"Divide a by b.\"\"\"
-    return a / b
+    if b == 0:
+        return None  # BUG: should raise ZeroDivisionError
+    return a / b
"""

SECURITY_DIFF = """diff --git a/src/auth.py b/src/auth.py
index 111..222 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -5,4 +5,7 @@ def authenticate(user, password):
-    return check_hash(password, user.password_hash)
+    # Temporary debug: log password for testing
+    print(f"DEBUG password={password}")
+    return check_hash(password, user.password_hash)
"""


@pytest.fixture
def simple_diff() -> str:
    """Return a minimal unified diff with a single bug-fix hunk."""
    return SIMPLE_DIFF


@pytest.fixture
def security_diff() -> str:
    """Return a unified diff that contains a credential-logging security issue."""
    return SECURITY_DIFF


@pytest.fixture
def sample_hunk() -> DiffHunk:
    """Return a pre-built DiffHunk for a Python calculator file."""
    return DiffHunk(
        file_path="src/calculator.py",
        start_line=10,
        hunk_header="@@ -10,7 +10,10 @@ def divide(a, b):",
        content=(
            "@@ -10,7 +10,10 @@ def divide(a, b):\n"
            "-    return a / b\n"
            "+    if b == 0:\n"
            "+        return None\n"
            "+    return a / b"
        ),
        language="Python",
    )


@pytest.fixture
def sample_context() -> RepoContext:
    """Return a minimal RepoContext for a Python project."""
    return RepoContext(
        language="Python",
        readme_excerpt="A simple calculator library.",
        file_tree=["src/", "tests/", "README.md", "pyproject.toml"],
    )


@pytest.fixture
def sample_comment() -> ReviewComment:
    """Return a single ReviewComment at warning severity."""
    return ReviewComment(
        file_path="src/calculator.py",
        line=12,
        severity="warning",
        message="Returning None instead of raising an exception is unexpected behaviour.",
    )


# ── HMAC helper ────────────────────────────────────────────────────────────────


def make_signature(payload: bytes, secret: str = "test-secret") -> str:
    """Compute the sha256 HMAC signature string for *payload*."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.fixture
def webhook_secret(monkeypatch) -> str:
    """Patch settings.github_webhook_secret with a known test value."""
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "github_webhook_secret", secret)
    return secret


# ── Mock LLM backend ───────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_backend():
    """Return an AsyncMock LLM backend that returns a pre-canned pipe-delimited response."""
    backend = AsyncMock()
    backend.complete = AsyncMock(
        return_value=(
            "src/calculator.py | 12 | warning | "
            "Returning None is unexpected; raise ZeroDivisionError instead"
        )
    )
    return backend


# ── Webhook payload factories ──────────────────────────────────────────────────


def make_pr_payload(
    owner: str = "testorg",
    repo: str = "testrepo",
    pr_number: int = 42,
    sha: str = "abc123def456",
    action: str = "opened",
    installation_id: int = 12345,
) -> bytes:
    """Build a JSON-encoded GitHub pull_request webhook payload."""
    payload = {
        "action": action,
        "pull_request": {
            "number": pr_number,
            "head": {"sha": sha},
        },
        "repository": {
            "name": repo,
            "owner": {"login": owner},
        },
        "installation": {"id": installation_id},
    }
    return json.dumps(payload).encode()


@pytest.fixture
def pr_payload() -> bytes:
    """Return a default 'opened' PR payload as bytes."""
    return make_pr_payload()
