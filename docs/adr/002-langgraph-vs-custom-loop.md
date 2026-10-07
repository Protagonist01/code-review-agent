# ADR-002: Model the review pipeline with LangGraph

## Status

Accepted.

## Context

The review pipeline has distinct steps with explicit inputs and outputs. A plain sequence of async function calls could implement the current linear flow. Named graph nodes make each stage independently testable and provide a shared typed state representation.

## Decision

Use a LangGraph `StateGraph` with `ReviewState`: diff parsing, repository context, prompt validation, model review, response filtering, and summary generation. The worker fetches the diff and publishes the result outside the graph.

The current graph is linear. Retries happen at the Celery task level, not through conditional graph edges. Graph construction can omit remote context and accept an injected backend for isolated evaluations and the offline demo. Streaming, checkpoints, and conditional retry branches are possible future capabilities, not implemented features.

## Consequences

- Stages can be tested with small state dictionaries and model fixtures.
- The dependency and graph API add complexity compared with a plain async function.
- The named stages and explicit state help readers inspect the pipeline and replace a stage without changing the worker contract.
- There is no durable graph checkpoint; a task retry repeats analysis.

The plain-function alternative remains reasonable for a small linear pipeline. LangGraph was retained to make stage boundaries explicit and leave room for future branching. See [architecture](../architecture.md) for the implemented topology.
