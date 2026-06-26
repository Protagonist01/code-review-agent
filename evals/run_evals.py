#!/usr/bin/env python3
"""
Evaluation runner for the AI Code Review Agent.

Loads evals/golden_set.jsonl, runs the LangGraph agent on each diff,
and measures true positive rate, false positive rate, and parse success rate.

Usage:
    python evals/run_evals.py
    python evals/run_evals.py --backend groq
    python evals/run_evals.py --output evals/results/run_001.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger()

GOLDEN_SET_PATH = Path("evals/golden_set.jsonl")
RESULTS_DIR = Path("evals/results")


def load_golden_set() -> list[dict]:
    """Load all entries from the golden set JSONL file.

    Returns:
        List of golden-set dicts, one per line.
    """
    entries: list[dict] = []
    with open(GOLDEN_SET_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


async def run_single(entry: dict) -> dict:
    """Run the agent on a single golden set entry and return metrics.

    Args:
        entry: A golden-set dict containing ``id``, ``diff``,
               ``expected_issues``, and ``expected_clean``.

    Returns:
        A result dict with TP/FP/FN counts, latency, and parse status.
    """
    from src.agent.graph import review_graph  # local import avoids circular refs

    start = time.perf_counter()
    try:
        state: dict = {
            "owner": "eval-org",
            "repo": "eval-repo",
            "pr_number": 0,
            "pr_sha": "eval000",
            "installation_id": None,
            "raw_diff": entry["diff"],
            "retry_count": 0,
            "error": None,
            # Provide minimal context — context_fetcher node handles None gracefully
            "repo_context": {
                "language": None,
                "readme_excerpt": None,
                "file_tree": [],
            },
        }
        final = await review_graph.ainvoke(state)
        comments = final.get("review_comments", [])
        latency = time.perf_counter() - start

        # ── scoring ─────────────────────────────────────────────────────
        expected = entry.get("expected_issues", [])
        expected_clean = entry.get("expected_clean", False)

        matched: list[bool] = []
        for expected_issue in expected:
            pattern = expected_issue.get("pattern", "")
            found = any(
                re.search(pattern, c.message, re.IGNORECASE)
                for c in comments
            )
            matched.append(found)

        tp = sum(matched)
        fn = len(matched) - tp
        fp = (
            len(comments)
            if expected_clean
            else max(0, len(comments) - len(expected))
        )

        return {
            "id": entry["id"],
            "description": entry["description"],
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "comment_count": len(comments),
            "expected_count": len(expected),
            "parse_success": True,
            "latency_s": round(latency, 2),
            "severity": final.get("severity", "unknown"),
        }

    except Exception as exc:
        latency = time.perf_counter() - start
        log.exception("eval.entry_failed", entry_id=entry["id"], error=str(exc))
        return {
            "id": entry["id"],
            "description": entry.get("description", ""),
            "tp": 0,
            "fn": len(entry.get("expected_issues", [])),
            "fp": 0,
            "comment_count": 0,
            "expected_count": len(entry.get("expected_issues", [])),
            "parse_success": False,
            "latency_s": round(latency, 2),
            "severity": "error",
            "error": str(exc),
        }


async def main(output_path: Path) -> None:
    """Load golden set, run every entry through the agent, print & save results.

    Args:
        output_path: Where to write the JSON results file.
    """
    entries = load_golden_set()
    print(f"Running evals on {len(entries)} golden set entries...\n")

    results: list[dict] = []
    for entry in entries:
        print(f"  [{entry['id']}] {entry['description']}...", end=" ", flush=True)
        result = await run_single(entry)
        results.append(result)
        status = "\u2705" if result["parse_success"] else "\u274c"
        print(f"{status} ({result['latency_s']}s)")

    # ── aggregate metrics ────────────────────────────────────────────────
    total_expected = sum(r["expected_count"] for r in results)
    total_tp = sum(r["tp"] for r in results)
    total_fp = sum(r["fp"] for r in results)
    total_fn = sum(r["fn"] for r in results)
    parse_successes = sum(1 for r in results if r["parse_success"])
    mean_latency = sum(r["latency_s"] for r in results) / len(results)

    tpr = total_tp / total_expected if total_expected > 0 else 0.0
    fpr = total_fp / len(results) if results else 0.0
    parse_rate = parse_successes / len(results) if results else 0.0

    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(entries),
        "true_positive_rate": round(tpr, 3),
        "false_positive_rate": round(fpr, 3),
        "parse_success_rate": round(parse_rate, 3),
        "mean_latency_s": round(mean_latency, 2),
        "targets": {
            "tpr_min": 0.70,
            "fpr_max": 0.15,
            "parse_rate_min": 0.98,
            "latency_p95_max_s": 30,
        },
        "passed": tpr >= 0.70 and fpr <= 0.15 and parse_rate >= 0.98,
        "entries": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2))

    # ── print summary ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("EVAL RESULTS")
    print("=" * 60)
    ok = "\u2705"
    fail = "\u274c"
    print(
        f"  True Positive Rate:  {tpr:.1%}  (target \u2265 70%)   "
        f"{ok if tpr >= 0.70 else fail}"
    )
    print(
        f"  False Positive Rate: {fpr:.1%}  (target \u2264 15%)   "
        f"{ok if fpr <= 0.15 else fail}"
    )
    print(
        f"  Parse Success Rate:  {parse_rate:.1%}  (target \u2265 98%)   "
        f"{ok if parse_rate >= 0.98 else fail}"
    )
    print(f"  Mean Latency:        {mean_latency:.1f}s")
    passed_str = f"PASSED {ok}" if summary["passed"] else f"FAILED {fail}"
    print(f"\n  Overall: {passed_str}")
    print(f"  Results saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run golden set evals")
    parser.add_argument(
        "--output",
        default="evals/results/latest.json",
        help="Output JSON path",
    )
    args = parser.parse_args()
    asyncio.run(main(Path(args.output)))
