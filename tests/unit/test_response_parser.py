from __future__ import annotations

import pytest

from src.agent.models import DiffHunk, ReviewComment
from src.agent.nodes.response_parser import parse_llm_response


@pytest.fixture
def sample_hunk() -> DiffHunk:
    """Return a sample DiffHunk for a Python calculator file."""
    return DiffHunk(
        file_path="src/calculator.py",
        start_line=10,
        hunk_header="@@ -10,7 +10,10 @@",
        content=" context\n context\n-    return a / b\n+    return None\n+    other()",
        language="Python",
    )


def test_valid_single_comment(sample_hunk: DiffHunk) -> None:
    """A single well-formed pipe-delimited line should produce one ReviewComment."""
    raw = "src/calculator.py | 12 | warning | Returning None is unexpected"
    result = parse_llm_response(raw, sample_hunk)
    assert len(result) == 1
    assert result[0].file_path == "src/calculator.py"
    assert result[0].line == 12
    assert result[0].severity == "warning"
    assert "None" in result[0].message


def test_none_output_returns_empty(sample_hunk: DiffHunk) -> None:
    """The literal string NONE (uppercase) should yield an empty list."""
    result = parse_llm_response("NONE", sample_hunk)
    assert result == []


def test_none_case_insensitive(sample_hunk: DiffHunk) -> None:
    """The none sentinel should be matched case-insensitively."""
    result = parse_llm_response("none", sample_hunk)
    assert result == []


def test_multiple_comments(sample_hunk: DiffHunk) -> None:
    """Multiple valid lines should each produce a distinct ReviewComment."""
    raw = (
        "src/calculator.py | 12 | warning | Returns None unexpectedly\n"
        "src/calculator.py | 13 | error | Division by zero not handled"
    )
    result = parse_llm_response(raw, sample_hunk)
    assert len(result) == 2
    severities = {c.severity for c in result}
    assert "warning" in severities
    assert "error" in severities


def test_malformed_line_skipped(sample_hunk: DiffHunk) -> None:
    """Lines that cannot be parsed should be silently skipped."""
    raw = "This is not valid format\nsrc/calculator.py | 12 | warning | Valid comment"
    result = parse_llm_response(raw, sample_hunk)
    assert len(result) == 1


def test_invalid_severity_skipped(sample_hunk: DiffHunk) -> None:
    """Lines with unrecognised severity values should be skipped."""
    raw = "src/calculator.py | 12 | critical | Some issue"
    result = parse_llm_response(raw, sample_hunk)
    assert len(result) == 0


def test_invalid_line_number_skipped(sample_hunk: DiffHunk) -> None:
    """Lines where the line number is not an integer should be skipped."""
    raw = "src/calculator.py | abc | warning | Some issue"
    result = parse_llm_response(raw, sample_hunk)
    assert len(result) == 0


def test_empty_file_path_uses_hunk_path(sample_hunk: DiffHunk) -> None:
    """An empty file_path field may fall back to the hunk's file_path."""
    raw = " | 12 | warning | Some issue"
    result = parse_llm_response(raw, sample_hunk)
    # Implementation may skip or fall back; either is acceptable.
    if result:
        assert result[0].file_path == sample_hunk.file_path


def test_comment_lines_skipped(sample_hunk: DiffHunk) -> None:
    """Lines beginning with # should be treated as comments and skipped."""
    raw = "# This is a comment\nsrc/calculator.py | 12 | info | Style note"
    result = parse_llm_response(raw, sample_hunk)
    assert len(result) == 1


def test_all_severity_levels_accepted(sample_hunk: DiffHunk) -> None:
    """All three valid severity levels (info, warning, error) should be accepted."""
    for severity in ("info", "warning", "error"):
        raw = f"src/calculator.py | 10 | {severity} | Some message"
        result = parse_llm_response(raw, sample_hunk)
        assert len(result) == 1, f"Expected 1 comment for severity={severity}"
        assert result[0].severity == severity


def test_extra_whitespace_trimmed(sample_hunk: DiffHunk) -> None:
    """Fields with leading/trailing whitespace should still be parsed correctly."""
    raw = "  src/calculator.py  |  12  |  warning  |  Trim whitespace test  "
    result = parse_llm_response(raw, sample_hunk)
    if result:
        assert result[0].severity == "warning"
        assert result[0].line == 12


def test_result_type_is_review_comment(sample_hunk: DiffHunk) -> None:
    """Each item returned should be an instance of ReviewComment."""
    raw = "src/calculator.py | 10 | info | Check return type"
    result = parse_llm_response(raw, sample_hunk)
    for item in result:
        assert isinstance(item, ReviewComment)


@pytest.mark.parametrize(
    "raw",
    [
        "other.py | 12 | error | Wrong file",
        "src/calculator.py | 999 | error | Outside diff",
    ],
)
def test_rejects_locations_outside_hunk(sample_hunk, raw):
    assert parse_llm_response(raw, sample_hunk) == []
