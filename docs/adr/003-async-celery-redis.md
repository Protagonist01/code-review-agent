# ADR-003: Process reviews with Celery and Redis

## Status

Accepted.

## Context

Model inference and GitHub API operations can outlast a webhook request. Running them synchronously would couple delivery acknowledgement to provider latency and availability. GitHub does not automatically redeliver failed webhook deliveries; operators need to inspect failures and redeliver as needed.

## Decision

Validate the signature, bound and validate the payload, claim the repository/PR/SHA in Redis, and enqueue a Celery task. Return `202 Accepted` only after dispatch succeeds. Redis or dispatch failures return 503; duplicate claims return 200.

The worker fetches the diff, invokes the review graph, and publishes GitHub review/status updates. Celery retries exceptions up to three times with backoff. Late acknowledgement and rejection on worker loss support recovery but do not guarantee exactly-once execution.

## Consequences

- API acknowledgement is independent of model inference, though Redis/broker outages can still delay it.
- API and worker can scale independently. The Compose pilot explicitly uses one worker process and limits prefetch to one task per process.
- Redis stores queued jobs, task results, and one-hour duplicate claims. It is not a configured rate limiter.
- Redis and workers add operational complexity. Persistence, backup/restore, queue recovery, and concurrent publication require live validation.
- Queue depth and worker metrics are not exposed by the current API metrics endpoint. Optional Flower helps inspect Celery tasks but must stay private.

Compose persists Redis data and keeps service ports on localhost. [Deployment guidance](../deployment.md) describes the operational checks still needed.

## Reference

[GitHub: handling failed webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries).
