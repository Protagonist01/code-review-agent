from __future__ import annotations

import time
from typing import cast

import httpx
import jwt  # PyJWT
import structlog

from src.config import settings

log = structlog.get_logger()


def _load_private_key() -> bytes:
    """Load the GitHub App private key PEM file."""
    with open(settings.github_private_key_path, "rb") as f:
        return f.read()


def generate_app_jwt() -> str:
    """
    Generate a short-lived JWT for GitHub App authentication.

    Valid for 60 seconds (GitHub allows up to 10 minutes).
    The ``iat`` claim is set 60 seconds in the past to handle clock drift
    between the local machine and GitHub's servers.
    """
    if settings.github_app_id is None:
        raise ValueError("github_app_id is required for GitHub App authentication")

    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued at (60 s in the past to account for clock drift)
        "exp": now + 60,  # expire in 60 seconds
        "iss": str(settings.github_app_id),
    }
    private_key = _load_private_key()
    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token


async def get_installation_token(installation_id: int) -> str:
    """
    Exchange a GitHub App JWT for an installation access token.

    These tokens expire after 1 hour.

    Args:
        installation_id: The GitHub App installation ID for the target org/repo.

    Returns:
        A short-lived installation access token string.

    Raises:
        httpx.HTTPStatusError: If the GitHub API returns a non-2xx response.
    """
    jwt_token = generate_app_jwt()
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        data = response.json()
        log.info("github_auth.installation_token_issued", installation_id=installation_id)
        return cast(str, data["token"])


async def get_auth_token(installation_id: int | None = None) -> str:
    """
    Return the appropriate auth token.

    Resolution order:
    1. If ``GITHUB_TOKEN`` is set (Personal Access Token), use it directly
       — handy for local development without a registered GitHub App.
    2. Otherwise, exchange a JWT for an installation access token via the
       GitHub App authentication flow.

    Args:
        installation_id: Required when ``GITHUB_TOKEN`` is not configured.

    Returns:
        A valid GitHub API bearer token.

    Raises:
        ValueError: If ``installation_id`` is ``None`` and no PAT is configured.
    """
    if settings.github_token:
        return settings.github_token
    if installation_id is None:
        raise ValueError("installation_id is required when not using GITHUB_TOKEN")
    return await get_installation_token(installation_id)
