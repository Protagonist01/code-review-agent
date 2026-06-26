"""Shared Pydantic models used across the agent pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class DiffHunk(BaseModel):
    """A single reviewable hunk extracted from a unified diff."""

    file_path: str
    """Path of the file being changed (b-side of the diff)."""

    start_line: int
    """Line number in the new file where this hunk starts (from @@ header)."""

    hunk_header: str
    """Raw @@ -L,S +L,S @@ header string."""

    content: str
    """Full hunk text including the header and all ± context lines."""

    language: str | None = None
    """Inferred programming language (e.g. 'Python', 'TypeScript')."""

    @field_validator("start_line")
    @classmethod
    def _positive_line(cls, v: int) -> int:
        if v < 1:
            raise ValueError("start_line must be >= 1")
        return v


class RepoContext(BaseModel):
    """Repo-level context used to ground the LLM review."""

    language: str | None = None
    """Primary repository language as reported by GitHub."""

    readme_excerpt: str | None = None
    """First ~500 characters of the repository README."""

    file_tree: list[str] = []
    """Top-level file and directory names (depth 2 max)."""


class ReviewComment(BaseModel):
    """A single review comment produced by the LLM and validated by the parser."""

    file_path: str
    line: int
    severity: Literal["info", "warning", "error"]
    message: str

    @field_validator("line")
    @classmethod
    def _positive_line(cls, v: int) -> int:
        if v < 1:
            raise ValueError("line must be >= 1")
        return v
