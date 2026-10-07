"""LangGraph StateGraph assembly for the AI Code Review Agent.

Defines :func:`build_graph` which wires all pipeline nodes together and
returns a compiled :class:`~langgraph.graph.CompiledStateGraph`.  The
module-level ``review_graph`` singleton is the entry-point used by the
Celery task worker.

Pipeline topology::

    START
      └─► diff_parser
            └─► context_fetcher
                  └─► prompt_builder
                        └─► llm_reviewer
                              └─► response_parser
                                    └─► summary_builder
                                          └─► END
"""

from __future__ import annotations

from functools import partial
from typing import Any

import structlog
from langgraph.graph import END, START, StateGraph

from src.agent.llm_backend import LLMBackend
from src.agent.nodes.context_fetcher import context_fetcher
from src.agent.nodes.diff_parser import diff_parser
from src.agent.nodes.llm_reviewer import llm_reviewer
from src.agent.nodes.prompt_builder import prompt_builder
from src.agent.nodes.response_parser import response_parser
from src.agent.nodes.summary_builder import summary_builder
from src.agent.state import ReviewState

log = structlog.get_logger()


def build_graph(*, fetch_context: bool = True, backend: LLMBackend | None = None) -> Any:
    """Construct and compile the review pipeline StateGraph.

    Nodes are registered in dependency order and connected with simple
    directed edges (no conditional branching in the happy path).

    Returns:
        A compiled LangGraph ``CompiledStateGraph`` ready for ``ainvoke``.
    """
    graph: StateGraph[Any] = StateGraph(ReviewState)

    # ── Register nodes ──────────────────────────────────────────────────────
    graph.add_node("diff_parser", diff_parser)
    if fetch_context:
        graph.add_node("context_fetcher", context_fetcher)
    graph.add_node("prompt_builder", prompt_builder)
    graph.add_node("llm_reviewer", partial(llm_reviewer, backend=backend))
    graph.add_node("response_parser", response_parser)
    graph.add_node("summary_builder", summary_builder)

    # ── Wire edges ──────────────────────────────────────────────────────────
    graph.add_edge(START, "diff_parser")
    if fetch_context:
        graph.add_edge("diff_parser", "context_fetcher")
        graph.add_edge("context_fetcher", "prompt_builder")
    else:
        graph.add_edge("diff_parser", "prompt_builder")
    graph.add_edge("prompt_builder", "llm_reviewer")
    graph.add_edge("llm_reviewer", "response_parser")
    graph.add_edge("response_parser", "summary_builder")
    graph.add_edge("summary_builder", END)

    compiled = graph.compile()
    log.info("graph.compiled", node_count=6 if fetch_context else 5)
    return compiled


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere that needs to run reviews
# ---------------------------------------------------------------------------
review_graph = build_graph()
