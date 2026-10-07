"""Context fetcher node for the LangGraph review pipeline.

Fetches repository-level context (primary language, README excerpt, file tree)
from the GitHub API via :class:`~src.github_client.client.GitHubClient` and
stores it in ``state["repo_context"]``.
"""

from __future__ import annotations

import structlog

from src.agent.models import RepoContext
from src.agent.state import ReviewState

log = structlog.get_logger()


async def context_fetcher(state: ReviewState) -> dict[str, RepoContext]:
    """LangGraph node: fetch repository context from GitHub.

    Attempts to retrieve:
    - The primary repository language
    - The top-level file tree at the PR's commit SHA
    - The first 500 characters of the repository README

    On any error the node falls back to an empty :class:`RepoContext` so
    downstream nodes can still proceed without repository context.

    Args:
        state: The current :class:`~src.agent.state.ReviewState`.

    Returns:
        A partial state update: ``{"repo_context": RepoContext}``.
    """
    # Defer the import so that the GitHub client is only constructed when this
    # node actually runs (avoids import-time side-effects during testing).
    from src.github_client.client import GitHubClient  # noqa: PLC0415

    owner: str = state.get("owner", "")
    repo: str = state.get("repo", "")
    pr_sha: str = state.get("pr_sha", "")
    installation_id: int | None = state.get("installation_id")

    if not owner or not repo:
        log.warning("context_fetcher.missing_identifiers")
        return {"repo_context": RepoContext()}

    try:
        async with GitHubClient(installation_id=installation_id) as client:
            language: str | None = await client.get_repo_language(owner, repo)
            file_tree: list[str] = await client.get_file_tree(owner, repo, pr_sha)

            raw_readme: str | None = await client.get_readme(owner, repo, pr_sha)
        readme_excerpt: str | None = raw_readme[:500] if raw_readme else None

        log.info(
            "context_fetcher.complete",
            owner=owner,
            repo=repo,
            language=language,
            file_tree_size=len(file_tree),
            has_readme=readme_excerpt is not None,
        )

        return {
            "repo_context": RepoContext(
                language=language,
                readme_excerpt=readme_excerpt,
                file_tree=file_tree,
            )
        }

    except Exception as exc:  # noqa: BLE001
        log.warning(
            "context_fetcher.error",
            owner=owner,
            repo=repo,
            error=str(exc),
            exc_info=True,
        )
        # Empty context is acceptable — downstream nodes handle None gracefully
        return {"repo_context": RepoContext()}
