"""Evaluate example diffs with real inference and no GitHub reads or writes.

Run `python -m evals.run_evals --backend ollama`. Hosted calls may incur costs.
Pattern scoring is illustrative and does not establish production accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agent.graph import build_graph
from src.agent.models import RepoContext, ReviewComment
from src.agent.nodes.diff_parser import _parse_diff
from src.agent.state import ReviewState
from src.config import settings

GOLDEN_SET_PATH = Path(__file__).with_name("golden_set.jsonl")


def load_golden_set() -> list[dict[str, Any]]:
    with GOLDEN_SET_PATH.open(encoding="utf-8") as dataset:
        entries = [json.loads(line) for line in dataset if line.strip()]
    if not entries:
        raise ValueError("Evaluation dataset is empty")
    return entries


def fixture_diff(entry: dict[str, Any]) -> str:
    """Add explicit paths to legacy bare hunks before production parsing."""
    diff: str = entry["diff"]
    if diff.startswith("@@"):
        paths = {issue["file"] for issue in entry.get("expected_issues", [])}
        if len(paths) > 1:
            raise ValueError("A bare hunk cannot represent multiple files")
        path = next(iter(paths), "example.py")
        diff = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{diff}"
    if not _parse_diff(diff):
        raise ValueError("Evaluation fixture has no reviewable hunks")
    return diff


def score_comments(expected: list[dict[str, Any]], comments: list[ReviewComment]) -> dict[str, int]:
    """Match expectations to distinct comments; extra comments are false positives."""
    matches: dict[int, int] = {}

    def assign(issue_index: int, visited: set[int]) -> bool:
        issue = expected[issue_index]
        for index, comment in enumerate(comments):
            if index in visited or not (
                comment.file_path == issue["file"]
                and comment.line == issue["line"]
                and comment.severity == issue["severity"]
                and re.search(issue["pattern"], comment.message, re.IGNORECASE)
            ):
                continue
            visited.add(index)
            if index not in matches or assign(matches[index], visited):
                matches[index] = issue_index
                return True
        return False

    for issue_index in range(len(expected)):
        assign(issue_index, set())
    tp = len(matches)
    return {"tp": tp, "fn": len(expected) - tp, "fp": len(comments) - tp}


async def run_single(entry: dict[str, Any], graph: Any) -> dict[str, Any]:
    start = time.perf_counter()
    result: dict[str, Any] = {
        "id": entry["id"],
        "description": entry["description"],
        "expected_count": len(entry.get("expected_issues", [])),
    }
    try:
        state: ReviewState = {"raw_diff": fixture_diff(entry), "repo_context": RepoContext()}
        final = await graph.ainvoke(state)
        comments = final["review_comments"]
        result.update(score_comments(entry.get("expected_issues", []), comments))
        result.update(run_success=True, comment_count=len(comments), severity=final["severity"])
    except Exception as exc:
        result.update(
            tp=0,
            fn=result["expected_count"],
            fp=0,
            run_success=False,
            comment_count=0,
            severity="error",
            error=str(exc),
        )
    result["latency_s"] = time.perf_counter() - start
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        raise ValueError("No evaluation results")
    tp, fp, fn = (sum(row[key] for row in results) for key in ("tp", "fp", "fn"))
    recall = tp / (tp + fn) if tp + fn else 1.0
    precision = tp / (tp + fp) if tp + fp else 1.0
    success_rate = sum(row["run_success"] for row in results) / len(results)
    latencies = sorted(row["latency_s"] for row in results)
    p95 = latencies[math.ceil(0.95 * len(latencies)) - 1]
    return {
        "run_at": datetime.now(UTC).isoformat(),
        "provider": settings.llm_provider,
        "model": getattr(settings, f"{settings.llm_provider}_model"),
        "entry_count": len(results),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": recall,
        "precision": precision,
        "run_success_rate": success_rate,
        "mean_latency_s": sum(latencies) / len(latencies),
        "latency_p95_s": p95,
        "targets": {
            "recall_min": 0.70,
            "precision_min": 0.85,
            "run_success_rate_min": 0.98,
            "latency_p95_max_s": 30,
        },
        "passed": recall >= 0.70 and precision >= 0.85 and success_rate >= 0.98 and p95 <= 30,
        "entries": results,
    }


async def main(output_path: Path) -> bool:
    graph = build_graph(fetch_context=False)
    results = []
    for entry in load_golden_set():
        result = await run_single(entry, graph)
        results.append(result)
        print(f"{entry['id']}: {'completed' if result['run_success'] else 'failed'}")
    summary = summarize(results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "entries"}, indent=2))
    print(f"Results saved to {output_path}")
    return bool(summary["passed"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evals/results/latest.json"))
    parser.add_argument(
        "--backend", choices=["groq", "ollama", "openai", "anthropic", "openrouter"]
    )
    args = parser.parse_args()
    if args.backend:
        settings.llm_provider = args.backend
    raise SystemExit(0 if asyncio.run(main(args.output)) else 1)
