# ADR-003: Process Reviews Asynchronously via Celery + Redis

## Status
Accepted

## Context
GitHub webhooks expect an HTTP `200` response within **10 seconds** or they mark the delivery as failed and retry. LLM inference for a non-trivial diff takes 15–60 seconds on CPU. Handling the review synchronously inside the webhook handler would cause consistent timeout failures and duplicate processing on GitHub's retry attempts.

## Decision
Acknowledge the webhook immediately with `202 Accepted`, then enqueue the review job to a **Celery** worker backed by **Redis**.

The webhook handler:
1. Validates HMAC signature
2. Extracts PR metadata
3. Enqueues a `review_pr` Celery task
4. Returns `202` to GitHub within ~50ms

The Celery worker:
1. Picks up the job from Redis
2. Runs the full LangGraph review pipeline
3. Posts results to GitHub API

## Consequences

**Gained:**
- Webhook handler always responds within GitHub's 10s window
- Natural retry mechanism — Celery retries failed jobs with exponential backoff
- Worker concurrency is independently scalable from the API layer
- Job queue depth is a Prometheus metric — observable backpressure
- Redis doubles as the rate-limiter store (one dependency, two uses)

**Trade-offs:**
- Adds operational complexity: Redis and at least one Celery worker must be running
- Review results are not immediate — there's a queue delay under load
- Debugging requires checking both the API logs and the worker logs

**Mitigation:**
`docker-compose.yml` starts Redis, the API, and a Celery worker together. `make up` gives a fully working stack in one command. The `flower` Celery dashboard is included for job monitoring at `localhost:5555`.
