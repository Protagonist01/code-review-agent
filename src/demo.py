"""Offline walkthrough using a recorded response; no provider or GitHub calls."""

from __future__ import annotations

import asyncio
import io
import logging
import sys

import structlog

from src.agent.models import RepoContext
from src.agent.state import ReviewState

DEMO_DIFF = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,3 @@
 def average(values):
-    return sum(values)
+    total = sum(values)
+    return total / len(values)
"""


class RecordedBackend:
    """Return an illustrative recorded finding, not a live model prediction."""

    async def complete(self, prompt: str, system: str) -> str:
        return "calculator.py | 3 | error | Guard against an empty list before dividing."


async def run_demo() -> ReviewState:
    from src.agent.graph import build_graph

    graph = build_graph(fetch_context=False, backend=RecordedBackend())
    state: ReviewState = {"raw_diff": DEMO_DIFF, "repo_context": RepoContext(language="Python")}
    return await graph.ainvoke(state)  # type: ignore[no-any-return]


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    print("Offline demo: recorded model output, no network calls.\n")
    print(DEMO_DIFF)
    result = asyncio.run(run_demo())
    summary = result["summary"].rsplit("\n*Reviewed by ", 1)[0]
    print(summary + "\n*Reviewed using a recorded response (offline)*")
    print("\nGitHub publication is omitted. This demonstrates the pipeline, not model accuracy.")


if __name__ == "__main__":
    main()
