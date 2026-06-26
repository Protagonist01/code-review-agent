# Architecture â€” AI Code Review Agent

## Overview

The **AI Code Review Agent** is an event-driven service that automatically
reviews GitHub pull requests using a multi-node LangGraph state machine backed
by a pluggable LLM provider (OpenRouter, Ollama, Groq, OpenAI, or Anthropic).

When a `pull_request` webhook fires, the FastAPI gateway enqueues a Celery
task. The Celery worker invokes the LangGraph graph, which orchestrates
diff fetching â†’ context retrieval â†’ LLM analysis â†’ comment posting in a
structured, retry-aware pipeline.

---

## LangGraph State Machine

```mermaid
flowchart TD
    START([__start__]) --> fetch_diff

    fetch_diff --> parse_diff
    parse_diff --> fetch_context

    fetch_context --> analyze

    analyze --> should_retry{error?}
    should_retry -- yes, retry_count < MAX --> analyze
    should_retry -- max retries exceeded --> post_error_comment

    should_retry -- no error --> filter_comments
    filter_comments --> post_review

    post_review --> END([__end__])
    post_error_comment --> END
```

### Node Descriptions

| Node | Responsibility |
|------|---------------|
| `fetch_diff` | Downloads the raw unified diff for the PR via the GitHub API (App auth or PAT). Stores it in `state.raw_diff`. |
| `parse_diff` | Splits `raw_diff` into `DiffHunk` objects â€” one per file-chunk â€” and populates `state.hunks`. |
| `fetch_context` | Retrieves repository context: primary language, abbreviated README, and top-level file tree. Stored in `state.repo_context`. |
| `analyze` | Sends each hunk to the configured LLM with a structured prompt. Parses the response into `ReviewComment` objects and accumulates them in `state.review_comments`. Also sets `state.summary` and `state.severity`. |
| `filter_comments` | Removes comments below `settings.min_comment_severity` and deduplicates near-identical messages. |
| `post_review` | Calls the GitHub Reviews API to submit all comments as a single review in `COMMENT` mode. |
| `post_error_comment` | Posts a polite error message on the PR when all retries are exhausted. |

---

## Data Flow

```
GitHub Webhook
      â”‚
      â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”    HMAC-SHA256    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  FastAPI    â”‚â—„â”€â”€â”€â”€ verified â”€â”€â”€â”€â”‚  GitHub Platform â”‚
â”‚  /webhook   â”‚                   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”˜
       â”‚ enqueue task
       â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”     Redis      â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚   Celery    â”‚â—„â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–ºâ”‚    Redis Broker  â”‚
â”‚   Worker    â”‚                â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”˜
       â”‚ ainvoke
       â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚       LangGraph Graph       â”‚
â”‚  fetch_diff â†’ parse_diff    â”‚
â”‚  â†’ fetch_context â†’ analyze  â”‚
â”‚  â†’ filter â†’ post_review     â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
               â”‚ GitHub Reviews API
               â–¼
        Pull Request Review
```

---

## LLM Backend Abstraction

The `analyze` node delegates to a provider factory in `src/agent/llm_backend.py`
that returns an `LLMBackend` implementation based on `settings.llm_provider`:

| Provider | Model | Config keys |
|----------|-------|-------------|
| `openrouter` | `cohere/north-mini-code:free` | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` |
| `groq` | `llama-3.3-70b-versatile` | `GROQ_API_KEY`, `GROQ_MODEL` |
| `ollama` | `codellama:7b` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `anthropic` | `claude-haiku-4-5` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |

Provider-specific imports live behind the backend factory, so swapping
backends requires changing a single env variable - no code changes.

where `ReviewOutput` is a Pydantic v2 model. This guarantees the LLM response
is always parseable into typed `ReviewComment` objects.

---

## Async Processing (Celery + Redis)

```
FastAPI (sync route)
  â””â”€â”€ enqueue_review_task.delay(owner, repo, pr_number, â€¦)
                â”‚
                â–¼
        Redis list (queue: "reviews")
                â”‚
                â–¼
        Celery worker process
          â””â”€â”€ asyncio.run(review_graph.ainvoke(state))
```

- The FastAPI webhook handler returns **202 Accepted** immediately after
  enqueueing, so GitHub receives a fast acknowledgement within its 10-second
  window.
- The Celery worker runs the fully-async LangGraph graph inside
  `asyncio.run()` on a dedicated OS thread-pool worker.
- Task result and error state are persisted in Redis so Flower can
  display them, and retries are handled at the **LangGraph node level** (not
  the Celery level) for fine-grained control.

---

## Observability

### Metrics (Prometheus)

The FastAPI app exposes `/metrics` (via `prometheus_fastapi_instrumentator`
plus custom `prometheus_client` counters/histograms):

| Metric | Type | Description |
|--------|------|-------------|
| `review_duration_seconds` | Histogram | End-to-end latency per review |
| `review_comments_total` | Counter | Comments posted, labelled by `severity` |
| `active_reviews` | Gauge | In-flight review tasks |
| `webhook_errors_total` | Counter | Webhook processing errors by `error_type` |
| `llm_tokens_total` | Counter | LLM tokens consumed |
| `reviews_completed_total` | Counter | Successfully completed reviews |

### Alerting (Prometheus Alertmanager)

Three alert rules are defined in `infra/prometheus/alert_rules.yml`:

- **ReviewLatencyHigh** â€” p95 > 60 s for 5 min â†’ `warning`
- **WebhookErrorRateHigh** â€” error rate > 5% â†’ `critical`
- **ActiveReviewsStuck** â€” > 10 in-flight for 10 min â†’ `warning`

### Dashboards (Grafana)

The pre-built Grafana dashboard (`infra/grafana/dashboard.json`) provides
six panels covering latency percentiles, comment severity breakdown, active
reviews gauge, webhook error trends, LLM token consumption, and review
throughput. It auto-provisions from the `infra/grafana/provisioning/`
directory and connects to Prometheus via the `DS_PROMETHEUS` datasource variable.

### Structured Logging

All components use `structlog` with JSON output (when `LOG_JSON=true`) for
machine-parseable logs. Key log events include:

- `webhook.received` â€” raw GitHub event metadata
- `review.started / review.completed / review.failed` â€” task lifecycle
- `llm.invoke` â€” provider, model, token counts, latency
- `github.post_review` â€” comment count and PR reference
