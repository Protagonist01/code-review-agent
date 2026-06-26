"""Prometheus metric definitions for the AI Code Review Agent.

All metrics are module-level singletons registered with the default
``prometheus_client`` registry at import time.  Import this module wherever
you need to record observations — the same objects are shared across the
process.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Latency ───────────────────────────────────────────────────────────────────

REVIEW_DURATION = Histogram(
    "review_duration_seconds",
    "End-to-end PR review latency from task start to GitHub review posted",
    buckets=[1, 5, 10, 20, 30, 60, 120],
)

# ── LLM usage ─────────────────────────────────────────────────────────────────

LLM_TOKENS_USED = Counter(
    "llm_tokens_used_total",
    "Cumulative LLM token consumption",
    ["model", "provider"],
)

# ── Review output ─────────────────────────────────────────────────────────────

COMMENTS_POSTED = Counter(
    "comments_posted_total",
    "Review comments posted to GitHub, broken down by severity label",
    ["severity"],
)

# ── Error tracking ────────────────────────────────────────────────────────────

WEBHOOK_ERRORS = Counter(
    "webhook_errors_total",
    "Webhook processing errors broken down by error type",
    ["error_type"],
)

# ── Concurrency ───────────────────────────────────────────────────────────────

ACTIVE_REVIEWS = Gauge(
    "active_reviews",
    "Number of review jobs currently in-flight across all workers",
)
