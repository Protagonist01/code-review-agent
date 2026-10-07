"""Response parser node for the LangGraph review pipeline.

Exposes two public interfaces:

1. :func:`parse_llm_response` — a pure function that parses raw LLM text in
   ``FILE | LINE | SEVERITY | MESSAGE`` format into
   :class:`~src.agent.models.ReviewComment` objects.

2. :func:`response_parser` — a LangGraph node that acts as a validation
   pass-through, applying the severity filter from
   ``settings.min_comment_severity`` to the already-parsed comments.
"""

from __future__ import annotations

import structlog

from src.agent.models import DiffHunk, ReviewComment
from src.agent.state import ReviewState
from src.config import settings

log = structlog.get_logger()

# Severity ordering used for the minimum-severity filter
SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "error": 2,
}


def parse_llm_response(raw: str, hunk: DiffHunk) -> list[ReviewComment]:
    """Parse LLM output into a list of :class:`ReviewComment` objects.

    Expected LLM output format — one issue per line::

        FILE | LINE | SEVERITY | MESSAGE

    Or the sentinel value ``NONE`` (case-insensitive) when no issues were
    found.

    Lines that do not conform to the format are silently skipped.

    Args:
        raw: Raw text response from the LLM backend.
        hunk: The :class:`~src.agent.models.DiffHunk` that was reviewed
              (used as a fallback file path when the LLM omits it).

    Returns:
        A list of valid :class:`ReviewComment` instances (may be empty).
    """
    comments: list[ReviewComment] = []
    valid_lines: set[int] = set()
    current_line = hunk.start_line
    for diff_line in hunk.content.splitlines():
        if diff_line.startswith(("@@", "\\", "-")):
            continue
        if diff_line.startswith(("+", " ")):
            valid_lines.add(current_line)
            current_line += 1

    for raw_line in raw.splitlines():
        line = raw_line.strip()

        # Skip blank lines and comment-style lines
        if not line or line.startswith("#"):
            continue

        # Sentinel value — no issues found
        if line.upper() == "NONE":
            return []

        # Support both " | " and "|" as delimiters
        if " | " in line:
            parts = line.split(" | ", maxsplit=3)
        elif "|" in line:
            parts = line.split("|", maxsplit=3)
        else:
            log.debug("response_parser.skip_malformed_line", line=line)
            continue

        if len(parts) != 4:
            log.debug("response_parser.skip_wrong_part_count", parts=len(parts), line=line)
            continue

        # --- file_path ---
        file_path = parts[0].strip() or hunk.file_path

        # --- line number ---
        try:
            line_number = int(parts[1].strip())
        except ValueError:
            log.debug("response_parser.skip_non_int_line", raw_line_number=parts[1].strip())
            continue

        if file_path != hunk.file_path or line_number not in valid_lines:
            continue

        if line_number < 1:
            log.debug("response_parser.skip_negative_line", line_number=line_number)
            continue

        # --- severity ---
        severity = parts[2].strip().lower()
        if severity not in SEVERITY_ORDER:
            log.debug("response_parser.skip_unknown_severity", severity=severity)
            continue

        # --- message ---
        message = parts[3].strip()
        if not message:
            log.debug("response_parser.skip_empty_message", line=line)
            continue

        try:
            comment = ReviewComment(
                file_path=file_path,
                line=line_number,
                severity=severity,  # type: ignore[arg-type]
                message=message,
            )
            comments.append(comment)
        except Exception as exc:  # noqa: BLE001
            log.debug("response_parser.skip_invalid_comment", error=str(exc))

    return comments


async def response_parser(state: ReviewState) -> dict[str, list[ReviewComment]]:
    """LangGraph node: validate and filter review comments by severity.

    Acts as a pass-through for the already-parsed comments produced by
    ``llm_reviewer``, applying the ``settings.min_comment_severity``
    threshold to remove low-severity noise before posting.

    Args:
        state: The current :class:`~src.agent.state.ReviewState`.

    Returns:
        A partial state update: ``{"review_comments": list[ReviewComment]}``
        containing only comments at or above the configured severity floor.
    """
    all_comments: list[ReviewComment] = state.get("review_comments", [])

    min_order = SEVERITY_ORDER.get(settings.min_comment_severity, 0)

    filtered: list[ReviewComment] = [
        c for c in all_comments if SEVERITY_ORDER.get(c.severity, 0) >= min_order
    ]

    dropped = len(all_comments) - len(filtered)
    log.info(
        "response_parser.complete",
        total_comments=len(all_comments),
        filtered_comments=len(filtered),
        dropped_below_threshold=dropped,
        min_severity=settings.min_comment_severity,
    )

    return {"review_comments": filtered}
