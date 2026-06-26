"""Diff parser node for the LangGraph review pipeline.

Converts a raw unified-diff string from ``state["raw_diff"]`` into a list
of :class:`~src.agent.models.DiffHunk` objects and stores them under
``state["hunks"]``.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import structlog

from src.agent.models import DiffHunk
from src.agent.state import ReviewState
from src.config import settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Language inference map (file extension → human-readable language name)
# ---------------------------------------------------------------------------
_EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".h": "C++",
    ".hpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".swift": "Swift",
    ".php": "PHP",
    ".scala": "Scala",
    ".r": "R",
    ".R": "R",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".sql": "SQL",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "SASS",
    ".md": "Markdown",
    ".tf": "Terraform",
    ".dockerfile": "Dockerfile",
}

# Patterns that identify noise files which should not be reviewed
_NOISE_PATTERNS: tuple[str, ...] = (
    ".lock",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    ".min.js",
    ".min.css",
    ".generated.",
    ".pb.go",
    "_pb2.py",
    ".pb2_grpc.py",
    "migration",
)


def _infer_language(file_path: str) -> str | None:
    """Infer a human-readable language name from a file path.

    Args:
        file_path: Path of the changed file (e.g. ``src/main.py``).

    Returns:
        A language name string, or ``None`` if the extension is unknown.
    """
    suffix = PurePosixPath(file_path).suffix.lower()
    # Handle Dockerfile specifically (no extension)
    name = PurePosixPath(file_path).name.lower()
    if name in ("dockerfile", "containerfile"):
        return "Dockerfile"
    return _EXT_TO_LANG.get(suffix)


def _is_noise_file(file_path: str) -> bool:
    """Return True if the file path matches a known noise pattern.

    Noise files (lock files, generated code, minified assets) are skipped
    to reduce irrelevant LLM commentary.

    Args:
        file_path: Path of the changed file.

    Returns:
        ``True`` if the file should be skipped.
    """
    lower = file_path.lower()
    return any(pattern in lower for pattern in _NOISE_PATTERNS)


def _parse_diff(raw_diff: str) -> list[DiffHunk]:
    """Parse a raw unified diff into a list of :class:`DiffHunk` objects.

    Args:
        raw_diff: Full text of a unified diff (as returned by GitHub's API).

    Returns:
        A (possibly empty) list of :class:`DiffHunk` instances.
    """
    hunks: list[DiffHunk] = []
    current_file: str | None = None
    current_hunk_header: str | None = None
    current_hunk_lines: list[str] = []
    current_start_line: int = 1

    lines = raw_diff.splitlines()

    def _flush_hunk() -> None:
        """Finalise the current hunk and append it to ``hunks``."""
        if current_file and current_hunk_header and current_hunk_lines:
            if _is_noise_file(current_file):
                return
            hunks.append(
                DiffHunk(
                    file_path=current_file,
                    start_line=current_start_line,
                    hunk_header=current_hunk_header,
                    content="\n".join(current_hunk_lines),
                    language=_infer_language(current_file),
                )
            )

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip binary file notices
        if "Binary files" in line:
            i += 1
            continue

        # New file section: "--- a/..." followed by "+++ b/..."
        if line.startswith("--- "):
            # Flush any pending hunk before switching files
            _flush_hunk()
            current_hunk_header = None
            current_hunk_lines = []

            # Try to read the +++ line right after
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                plus_line = lines[i + 1]
                # Strip the "+++ b/" prefix; handle "/dev/null"
                raw_path = plus_line[4:]  # remove "+++ "
                if raw_path.startswith("b/"):
                    raw_path = raw_path[2:]
                current_file = None if raw_path == "/dev/null" else raw_path.strip()
                i += 2
                continue

        # Hunk header: @@ -L,S +L,S @@
        if line.startswith("@@"):
            # Flush the previous hunk
            _flush_hunk()
            current_hunk_header = line
            current_hunk_lines = [line]

            # Extract the start line of the new-file side: +L or +L,S
            match = re.search(r"\+(\d+)(?:,\d+)?", line)
            current_start_line = int(match.group(1)) if match else 1
            i += 1
            continue

        # Hunk content (context, added, removed lines)
        if current_hunk_header is not None:
            # A new "diff --git" or "---" line signals the end of this hunk
            if line.startswith("diff --git"):
                _flush_hunk()
                current_hunk_header = None
                current_hunk_lines = []
            else:
                current_hunk_lines.append(line)

        i += 1

    # Flush the final hunk
    _flush_hunk()
    return hunks


async def diff_parser(state: ReviewState) -> dict[str, list[DiffHunk]]:
    """LangGraph node: parse the raw unified diff into DiffHunk objects.

    Reads ``state["raw_diff"]``, validates its size, and returns a dict
    with a single key ``"hunks"`` containing the parsed results.

    Args:
        state: The current :class:`~src.agent.state.ReviewState`.

    Returns:
        A partial state update: ``{"hunks": list[DiffHunk]}``.
    """
    raw_diff: str = state.get("raw_diff", "")

    if not raw_diff:
        log.warning("diff_parser.empty_diff", owner=state.get("owner"), repo=state.get("repo"))
        return {"hunks": []}

    line_count = raw_diff.count("\n")
    if line_count > settings.max_diff_lines:
        log.warning(
            "diff_parser.diff_too_large",
            line_count=line_count,
            max_diff_lines=settings.max_diff_lines,
            owner=state.get("owner"),
            repo=state.get("repo"),
            pr_number=state.get("pr_number"),
        )
        return {"hunks": []}

    hunks = _parse_diff(raw_diff)

    log.info(
        "diff_parser.complete",
        hunk_count=len(hunks),
        owner=state.get("owner"),
        repo=state.get("repo"),
        pr_number=state.get("pr_number"),
    )
    return {"hunks": hunks}
