from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Literal, cast

import httpx
import structlog

from src.agent.models import ReviewComment
from src.github_client.auth import get_auth_token

log = structlog.get_logger()

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Thin async wrapper around the GitHub REST API.

    Supports both GitHub App installation tokens and Personal Access Tokens
    (PAT).  A single ``httpx.AsyncClient`` is reused across requests for
    connection pooling; call :meth:`close` when the client is no longer needed
    (or use it as an async context manager).

    Args:
        installation_id: GitHub App installation ID for the target org/repo.
            Not required when a PAT is configured via ``GITHUB_TOKEN``.
    """

    def __init__(self, installation_id: int | None = None) -> None:
        self._installation_id = installation_id
        self._token: str | None = None
        self._http: httpx.AsyncClient | None = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_http(self) -> httpx.AsyncClient:
        """Lazily initialise the shared HTTP client with auth headers."""
        if self._token is None:
            self._token = await get_auth_token(self._installation_id)
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers={
                    "Authorization": f"token {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        return self._http

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._http:
            await self._http.aclose()
            self._http = None

    # ── Async context-manager support ─────────────────────────────────────────

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── Pull-Request helpers ──────────────────────────────────────────────────

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """Fetch PR metadata from the GitHub REST API.

        Args:
            owner: Repository owner (user or org login).
            repo: Repository name.
            pr_number: Pull-request number.

        Returns:
            Parsed JSON response dict from the GitHub API.
        """
        http = await self._get_http()
        r = await http.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    async def get_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Fetch the unified diff for a pull request.

        Requests the ``application/vnd.github.v3.diff`` media type so GitHub
        returns a raw unified-diff string rather than JSON.

        Args:
            owner: Repository owner login.
            repo: Repository name.
            pr_number: Pull-request number.

        Returns:
            Raw unified-diff text.
        """
        http = await self._get_http()
        r = await http.get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        r.raise_for_status()
        return r.text

    # ── Repository helpers ────────────────────────────────────────────────────

    async def get_repo_language(self, owner: str, repo: str) -> str | None:
        """Return the primary programming language detected by GitHub.

        Args:
            owner: Repository owner login.
            repo: Repository name.

        Returns:
            Language string (e.g. ``"Python"``) or ``None`` if undetected.
        """
        http = await self._get_http()
        r = await http.get(f"/repos/{owner}/{repo}")
        r.raise_for_status()
        return cast(str | None, r.json().get("language"))

    async def get_file_tree(self, owner: str, repo: str, sha: str) -> list[str]:
        """Return top-level path names from the repository tree.

        Only fetches depth-1 items (files and directories at the root).

        Args:
            owner: Repository owner login.
            repo: Repository name.
            sha: Commit SHA or branch name to read the tree from.

        Returns:
            Sorted list of top-level path strings.
        """
        http = await self._get_http()
        r = await http.get(f"/repos/{owner}/{repo}/git/trees/{sha}")
        r.raise_for_status()
        tree = r.json().get("tree", [])
        return [item["path"] for item in tree if item.get("path")]

    async def get_readme(self, owner: str, repo: str, ref: str) -> str | None:
        """Fetch a short excerpt of the repository README.

        Decodes the base64-encoded content returned by the GitHub API and
        returns the first 500 characters.

        Args:
            owner: Repository owner login.
            repo: Repository name.
            ref: Git ref (branch, tag, or SHA) to read the README from.

        Returns:
            First 500 characters of the README, or ``None`` if not found.
        """
        http = await self._get_http()
        r = await http.get(
            f"/repos/{owner}/{repo}/readme",
            params={"ref": ref},
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return content[:500]  # excerpt only

    # ── Review posting ────────────────────────────────────────────────────────

    async def post_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
        comments: list[ReviewComment],
        body: str,
    ) -> None:
        """Post a pull-request review with inline comments and a summary body.

        Uses the Pull Request Reviews API so all comments are grouped into a
        single review event rather than scattered individual comments.

        Args:
            owner: Repository owner login.
            repo: Repository name.
            pr_number: Pull-request number.
            commit_sha: SHA of the head commit the review is attached to.
            comments: List of :class:`~src.agent.models.ReviewComment` objects
                to post as inline comments.
            body: Markdown body for the top-level review summary.
        """
        http = await self._get_http()
        inline = [
            {
                "path": c.file_path,
                "line": c.line,
                "side": "RIGHT",
                "body": f"**[{c.severity.upper()}]** {c.message}",
            }
            for c in comments
        ]
        payload: dict[str, object] = {
            "commit_id": commit_sha,
            "body": body,
            "event": "COMMENT",  # APPROVE, REQUEST_CHANGES, or COMMENT
            "comments": inline,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        marker = f"<!-- code-review-agent:{digest} -->"
        page = 1
        while True:
            existing = await http.get(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                params={"per_page": 100, "page": page},
            )
            existing.raise_for_status()
            reviews = existing.json()
            if any(
                review.get("commit_id") == commit_sha
                and review.get("state") != "PENDING"
                and marker in (review.get("body") or "")
                for review in reviews
            ):
                return
            if len(reviews) < 100:
                break
            page += 1
        payload["body"] = f"{body}\n\n{marker}"
        r = await http.post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        r.raise_for_status()
        log.info(
            "github_client.review_posted",
            pr=pr_number,
            comment_count=len(inline),
        )

    # ── Commit status ─────────────────────────────────────────────────────────

    async def set_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: Literal["pending", "success", "failure", "error"],
        description: str,
        context: str = "ai-code-review",
    ) -> None:
        """Set a commit status check on the given SHA.

        Args:
            owner: Repository owner login.
            repo: Repository name.
            sha: Full commit SHA to attach the status to.
            state: GitHub status state — one of ``pending``, ``success``,
                ``failure``, or ``error``.
            description: Short human-readable description (max 140 chars,
                enforced automatically).
            context: Status context label shown in the PR checks UI.
        """
        http = await self._get_http()
        payload = {
            "state": state,
            "description": description[:140],  # GitHub limit
            "context": context,
        }
        r = await http.post(
            f"/repos/{owner}/{repo}/statuses/{sha}",
            json=payload,
        )
        r.raise_for_status()
        log.info("github_client.status_set", sha=sha[:7], state=state)
