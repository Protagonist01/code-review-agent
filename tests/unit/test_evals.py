from unittest.mock import AsyncMock

import pytest

from evals.run_evals import fixture_diff, load_golden_set, run_single, score_comments, summarize
from src.agent.models import ReviewComment
from src.agent.nodes.diff_parser import _parse_diff
from src.demo import run_demo


def test_every_golden_case_produces_reviewable_hunks():
    entries = load_golden_set()
    assert len(entries) == 10
    for entry in entries:
        hunks = _parse_diff(fixture_diff(entry))
        assert hunks, entry["id"]
        for issue in entry.get("expected_issues", []):
            assert issue["file"] in {hunk.file_path for hunk in hunks}


def test_scoring_counts_unmatched_comments_as_false_positives():
    expected = [{"file": "app.py", "line": 2, "severity": "error", "pattern": "empty"}]
    comment = ReviewComment(file_path="app.py", line=2, severity="error", message="empty list")
    unrelated = comment.model_copy(update={"file_path": "elsewhere.py"})
    assert score_comments(expected, [unrelated]) == {"tp": 0, "fp": 1, "fn": 1}
    assert score_comments(expected, [comment, comment]) == {"tp": 1, "fp": 1, "fn": 0}
    assert score_comments(expected * 2, [comment]) == {"tp": 1, "fp": 0, "fn": 1}


def test_latency_threshold_and_failures_cannot_pass():
    result = {"tp": 1, "fn": 0, "fp": 0, "run_success": True, "latency_s": 31}
    assert not summarize([result])["passed"]
    result.update(latency_s=1, run_success=False)
    assert not summarize([result])["passed"]


async def test_eval_failure_records_false_negatives():
    graph = AsyncMock()
    graph.ainvoke.side_effect = RuntimeError("model unavailable")
    result = await run_single(load_golden_set()[0], graph)
    assert result["fn"] == 1
    assert result["run_success"] is False


async def test_demo_exercises_real_graph_without_network(monkeypatch):
    monkeypatch.setattr(
        "src.github_client.client.GitHubClient", AsyncMock(side_effect=AssertionError("network"))
    )
    monkeypatch.setattr(
        "src.agent.nodes.llm_reviewer.get_llm_backend",
        AsyncMock(side_effect=AssertionError("provider")),
    )
    result = await run_demo()
    assert result["severity"] == "error"
    assert result["review_comments"][0].line == 3
    assert "calculator.py:3" in result["summary"]


def test_malformed_fixture_cannot_silently_pass():
    with pytest.raises(ValueError, match="no reviewable"):
        fixture_diff({"diff": "not a diff"})
