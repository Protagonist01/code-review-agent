from __future__ import annotations

from src.agent.models import DiffHunk, ReviewComment
from src.worker import _run_review


class FakeGraph:
    async def ainvoke(self, state: dict) -> dict:
        return {
            "hunks": [
                DiffHunk(
                    file_path="src/app.py", start_line=5, hunk_header="@@ -5 +5 @@", content="+pass"
                )
            ],
            "review_comments": [
                ReviewComment(
                    file_path="src/app.py",
                    line=5,
                    severity="warning",
                    message="Check this branch.",
                )
            ],
            "summary": "Review summary",
            "severity": "warning",
        }


class FakeGitHubClient:
    last_instance = None

    def __init__(self, installation_id: int | None = None) -> None:
        self.installation_id = installation_id
        self.statuses = []
        self.reviews = []
        FakeGitHubClient.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set_commit_status(self, owner, repo, sha, state, description):
        self.statuses.append((owner, repo, sha, state, description))

    async def get_pull_request(self, owner, repo, pr_number):
        return {"head": {"sha": "abc123"}}

    async def get_diff(self, owner, repo, pr_number):
        return "diff --git a/src/app.py b/src/app.py"

    async def post_review(self, owner, repo, pr_number, pr_sha, comments, summary):
        self.reviews.append((owner, repo, pr_number, pr_sha, comments, summary))


async def test_run_review_posts_review_and_statuses(monkeypatch) -> None:
    import src.agent.graph as graph_module
    import src.github_client.client as client_module

    monkeypatch.setattr(graph_module, "review_graph", FakeGraph())
    monkeypatch.setattr(client_module, "GitHubClient", FakeGitHubClient)

    result = await _run_review("acme", "service", 7, "abc123", 99)

    client = FakeGitHubClient.last_instance
    assert result == {"status": "ok", "severity": "warning", "comment_count": 1}
    assert client.installation_id == 99
    assert client.statuses[0][3] == "pending"
    assert client.statuses[-1][3] == "success"
    assert client.reviews[0][5] == "Review summary"


async def test_stale_event_does_not_post_review(monkeypatch):
    import src.github_client.client as client_module

    monkeypatch.setattr(client_module, "GitHubClient", FakeGitHubClient)
    result = await _run_review("acme", "service", 7, "old-sha", 99)
    assert result["status"] == "superseded"
    assert not FakeGitHubClient.last_instance.reviews
    assert FakeGitHubClient.last_instance.statuses[-1][3] == "error"


async def test_publication_failure_sets_error_and_propagates(monkeypatch):
    from unittest.mock import AsyncMock

    import pytest

    import src.agent.graph as graph_module
    import src.github_client.client as client_module

    monkeypatch.setattr(graph_module, "review_graph", FakeGraph())
    monkeypatch.setattr(client_module, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(
        FakeGitHubClient, "post_review", AsyncMock(side_effect=RuntimeError("GitHub down"))
    )
    with pytest.raises(RuntimeError, match="GitHub down"):
        await _run_review("acme", "service", 7, "abc123", 99)
    assert FakeGitHubClient.last_instance.statuses[-1][3] == "error"


async def test_no_reviewable_hunks_does_not_report_success(monkeypatch):
    from unittest.mock import AsyncMock

    import src.agent.graph as graph_module
    import src.github_client.client as client_module

    graph = AsyncMock()
    graph.ainvoke.return_value = {
        "hunks": [],
        "review_comments": [],
        "summary": "No issues",
        "severity": "clean",
    }
    monkeypatch.setattr(graph_module, "review_graph", graph)
    monkeypatch.setattr(client_module, "GitHubClient", FakeGitHubClient)
    result = await _run_review("acme", "service", 7, "abc123", 99)
    assert result["status"] == "skipped"
    assert not FakeGitHubClient.last_instance.reviews
    assert FakeGitHubClient.last_instance.statuses[-1][3] == "error"


async def test_new_commit_during_model_review_does_not_publish(monkeypatch):
    from unittest.mock import AsyncMock

    import src.agent.graph as graph_module
    import src.github_client.client as client_module

    monkeypatch.setattr(graph_module, "review_graph", FakeGraph())
    monkeypatch.setattr(client_module, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(
        FakeGitHubClient,
        "get_pull_request",
        AsyncMock(
            side_effect=[
                {"head": {"sha": "abc123"}},
                {"head": {"sha": "abc123"}},
                {"head": {"sha": "new-sha"}},
            ]
        ),
    )
    result = await _run_review("acme", "service", 7, "abc123", 99)
    assert result["status"] == "superseded"
    assert not FakeGitHubClient.last_instance.reviews
