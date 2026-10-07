from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agent.models import DiffHunk, RepoContext, ReviewComment
from src.agent.nodes import context_fetcher as context_fetcher_module
from src.agent.nodes import llm_reviewer as llm_reviewer_module
from src.agent.nodes.prompt_builder import build_hunk_prompt, prompt_builder
from src.agent.nodes.summary_builder import summary_builder


class FakeGitHubClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __init__(self, installation_id: int | None = None) -> None:
        self.installation_id = installation_id

    async def get_repo_language(self, owner: str, repo: str) -> str:
        return "Python"

    async def get_file_tree(self, owner: str, repo: str, sha: str) -> list[str]:
        return ["src", "tests", "README.md"]

    async def get_readme(self, owner: str, repo: str, ref: str) -> str:
        return "A" * 600


@pytest.mark.asyncio
async def test_context_fetcher_returns_repo_context(monkeypatch) -> None:
    import src.github_client.client as client_module

    monkeypatch.setattr(client_module, "GitHubClient", FakeGitHubClient)

    result = await context_fetcher_module.context_fetcher(
        {
            "owner": "acme",
            "repo": "service",
            "pr_sha": "abc123",
            "installation_id": 42,
        }
    )

    context = result["repo_context"]
    assert context.language == "Python"
    assert context.file_tree == ["src", "tests", "README.md"]
    assert context.readme_excerpt == "A" * 500


@pytest.mark.asyncio
async def test_context_fetcher_falls_back_without_identifiers() -> None:
    result = await context_fetcher_module.context_fetcher({"owner": "", "repo": ""})

    assert result["repo_context"] == RepoContext()


@pytest.mark.asyncio
async def test_context_fetcher_falls_back_on_client_error(monkeypatch) -> None:
    import src.github_client.client as client_module

    class FailingClient(FakeGitHubClient):
        async def get_repo_language(self, owner: str, repo: str) -> str:
            raise RuntimeError("github unavailable")

    monkeypatch.setattr(client_module, "GitHubClient", FailingClient)

    result = await context_fetcher_module.context_fetcher(
        {"owner": "acme", "repo": "service", "pr_sha": "abc123"}
    )

    assert result["repo_context"] == RepoContext()


def test_build_hunk_prompt_includes_context(
    sample_hunk: DiffHunk, sample_context: RepoContext
) -> None:
    system_prompt, user_prompt = build_hunk_prompt(sample_hunk, sample_context)

    assert "code review" in system_prompt.lower()
    assert "src/calculator.py" in user_prompt
    assert "A simple calculator library." in user_prompt
    assert "pyproject.toml" in user_prompt


@pytest.mark.asyncio
async def test_prompt_builder_validates_template() -> None:
    assert await prompt_builder({}) == {}


@pytest.mark.asyncio
async def test_llm_reviewer_returns_no_comments_for_empty_hunks() -> None:
    result = await llm_reviewer_module.llm_reviewer({"hunks": []})

    assert result == {"review_comments": []}


@pytest.mark.asyncio
async def test_llm_reviewer_parses_backend_comments(monkeypatch, sample_hunk: DiffHunk) -> None:
    backend = AsyncMock()
    backend.complete = AsyncMock(
        return_value="src/calculator.py | 12 | warning | Return a clear error instead"
    )
    monkeypatch.setattr(llm_reviewer_module, "get_llm_backend", lambda: backend)

    result = await llm_reviewer_module.llm_reviewer(
        {"hunks": [sample_hunk], "repo_context": RepoContext(language="Python")}
    )

    comments = result["review_comments"]
    assert len(comments) == 1
    assert comments[0].severity == "warning"
    backend.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_reviewer_propagates_backend_errors(monkeypatch, sample_hunk: DiffHunk) -> None:
    backend = AsyncMock()
    backend.complete = AsyncMock(side_effect=RuntimeError("provider down"))
    monkeypatch.setattr(llm_reviewer_module, "get_llm_backend", lambda: backend)

    with pytest.raises(RuntimeError, match="provider down"):
        await llm_reviewer_module.llm_reviewer({"hunks": [sample_hunk]})


@pytest.mark.asyncio
async def test_summary_builder_reports_highest_severity() -> None:
    comments = [
        ReviewComment(file_path="a.py", line=1, severity="info", message="note"),
        ReviewComment(file_path="b.py", line=2, severity="error", message="bug"),
    ]

    result = await summary_builder({"review_comments": comments})

    assert result["severity"] == "error"
    assert "ERROR" in result["summary"]
    assert "b.py:2" in result["summary"]


@pytest.mark.asyncio
async def test_summary_builder_reports_clean_when_no_comments() -> None:
    result = await summary_builder({"review_comments": []})

    assert result["severity"] == "clean"
    assert "No issues found" in result["summary"]


@pytest.mark.parametrize("response", ["", "nonsense", "```"])
async def test_invalid_model_result_fails_review(monkeypatch, sample_hunk, response):
    backend = AsyncMock()
    backend.complete.return_value = response
    monkeypatch.setattr(llm_reviewer_module, "get_llm_backend", lambda: backend)
    with pytest.raises(ValueError, match="no valid"):
        await llm_reviewer_module.llm_reviewer({"hunks": [sample_hunk]})


async def test_oversized_diff_cannot_pass(monkeypatch):
    from src.agent.nodes.diff_parser import diff_parser
    from src.config import settings

    monkeypatch.setattr(settings, "max_diff_lines", 1)
    with pytest.raises(ValueError, match="MAX_DIFF_LINES"):
        await diff_parser({"raw_diff": "line1\nline2"})
