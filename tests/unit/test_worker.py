from __future__ import annotations

from src.agent.models import ReviewComment
from src.worker import _run_review


class FakeGraph:
    async def ainvoke(self, state: dict) -> dict:
        return {
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
