from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import pytest

from src.agent.models import ReviewComment
from src.config import settings
from src.github_client import auth as auth_module
from src.github_client.client import GitHubClient


class FakeResponse:
    def __init__(self, json_data=None, text: str = "", status_code: int = 200) -> None:
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")


class FakeHTTP:
    def __init__(self) -> None:
        self.posts = []
        self.closed = False

    async def get(self, path: str, **kwargs):
        if path.endswith("/reviews"):
            return FakeResponse([])
        if path.endswith("/pulls/7") and kwargs.get("headers"):
            return FakeResponse(text="diff --git a/a.py b/a.py")
        if path.endswith("/pulls/7"):
            return FakeResponse({"number": 7})
        if path.endswith("/repos/acme/service"):
            return FakeResponse({"language": "Python"})
        if path.endswith("/git/trees/abc123"):
            return FakeResponse({"tree": [{"path": "src"}, {"path": ""}, {"path": "README.md"}]})
        if path.endswith("/readme"):
            encoded = base64.b64encode(b"hello readme").decode()
            return FakeResponse({"content": encoded})
        return FakeResponse(status_code=404)

    async def post(self, path: str, json: dict):
        self.posts.append((path, json))
        return FakeResponse({})

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def github_client() -> tuple[GitHubClient, FakeHTTP]:
    client = GitHubClient(installation_id=123)
    http = FakeHTTP()
    client._token = "token"
    client._http = http
    return client, http


@pytest.mark.asyncio
async def test_github_client_reads_repository_data(github_client) -> None:
    client, _ = github_client

    assert await client.get_pull_request("acme", "service", 7) == {"number": 7}
    assert await client.get_diff("acme", "service", 7) == "diff --git a/a.py b/a.py"
    assert await client.get_repo_language("acme", "service") == "Python"
    assert await client.get_file_tree("acme", "service", "abc123") == ["src", "README.md"]
    assert await client.get_readme("acme", "service", "abc123") == "hello readme"


@pytest.mark.asyncio
async def test_github_client_posts_review_and_status(github_client) -> None:
    client, http = github_client
    comments = [
        ReviewComment(
            file_path="src/app.py",
            line=10,
            severity="error",
            message="Handle None before use.",
        )
    ]

    await client.post_review("acme", "service", 7, "abc123", comments, "Summary")
    await client.set_commit_status("acme", "service", "abc123", "success", "x" * 200)

    review_path, review_payload = http.posts[0]
    status_path, status_payload = http.posts[1]
    assert review_path == "/repos/acme/service/pulls/7/reviews"
    assert review_payload["comments"][0]["body"].startswith("**[ERROR]**")
    assert status_path == "/repos/acme/service/statuses/abc123"
    assert len(status_payload["description"]) == 140


@pytest.mark.asyncio
async def test_github_client_close_closes_http(github_client) -> None:
    client, http = github_client

    await client.close()

    assert http.closed is True
    assert client._http is None


def test_generate_app_jwt_uses_expected_claims(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(settings, "github_app_id", "12345")
    monkeypatch.setattr(auth_module.time, "time", lambda: 1000)
    monkeypatch.setattr(auth_module, "_load_private_key", lambda: b"private-key")

    def fake_encode(payload, private_key, algorithm):
        captured.update(payload=payload, private_key=private_key, algorithm=algorithm)
        return "jwt-token"

    monkeypatch.setattr(auth_module.jwt, "encode", fake_encode)

    assert auth_module.generate_app_jwt() == "jwt-token"
    assert captured["payload"] == {"iat": 940, "exp": 1060, "iss": "12345"}
    assert captured["private_key"] == b"private-key"
    assert captured["algorithm"] == "RS256"


@pytest.mark.asyncio
async def test_get_auth_token_prefers_pat(monkeypatch) -> None:
    monkeypatch.setattr(settings, "github_token", "pat-token")

    assert await auth_module.get_auth_token(None) == "pat-token"


@pytest.mark.asyncio
async def test_get_auth_token_requires_installation_without_pat(monkeypatch) -> None:
    monkeypatch.setattr(settings, "github_token", None)

    with pytest.raises(ValueError, match="installation_id is required"):
        await auth_module.get_auth_token(None)


@pytest.mark.asyncio
async def test_get_auth_token_fetches_installation_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "github_token", None)
    fetch = AsyncMock(return_value="installation-token")
    monkeypatch.setattr(auth_module, "get_installation_token", fetch)

    assert await auth_module.get_auth_token(123) == "installation-token"
    fetch.assert_awaited_once_with(123)


async def test_retry_reconciles_already_published_review(github_client):
    client, http = github_client
    await client.post_review("acme", "service", 7, "abc123", [], "Summary")
    published = dict(http.posts[0][1], state="COMMENT")
    http.get = AsyncMock(return_value=FakeResponse([published]))
    await client.post_review("acme", "service", 7, "abc123", [], "Summary")
    assert len(http.posts) == 1


async def test_review_reconciliation_paginates(github_client):
    client, http = github_client
    await client.post_review("acme", "service", 7, "abc123", [], "Summary")
    published = dict(http.posts[0][1], state="COMMENT")
    http.get = AsyncMock(side_effect=[FakeResponse([{}] * 100), FakeResponse([published])])
    await client.post_review("acme", "service", 7, "abc123", [], "Summary")
    assert len(http.posts) == 1
    assert http.get.call_args.kwargs["params"]["page"] == 2
