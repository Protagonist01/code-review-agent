# ADR-004: Configurable local and hosted inference

## Status

Accepted. Supersedes [ADR-001](001-local-llm-via-ollama.md), which originally chose local Ollama as the default.

## Context

Different repositories have different privacy, hardware, and budget constraints. Fixing one inference provider would make the review pipeline depend on that provider's API and deployment model.

## Decision

Expose an `LLMBackend` protocol with `async complete(prompt: str, system: str) -> str`. Implement it through LangChain integrations for OpenRouter, Ollama, Groq, OpenAI, and Anthropic. Select the provider and model through environment settings. OpenRouter is the current configuration default; model availability and cost must be verified by the operator.

The review graph depends on the protocol rather than a particular client. Its optional backend argument permits recorded, network-free demos and tests. Evaluations keep real inference but disable GitHub context fetching.

## Consequences

- Provider changes do not alter parsing, validation, or GitHub publication.
- Hosted providers receive source diffs and repository context; users must evaluate their data handling.
- A locally hosted Ollama service keeps inference within the operator's infrastructure. GitHub API communication is still required, so the entire application is not air-gapped or free of network traffic.
- Smaller local models and hosted models can differ in quality and latency. No provider comparison or latency guarantee has been established by this repository.
- The protocol returns text only. Token accounting and richer structured provider results would need a broader interface.

Hardcoding Ollama would restrict users without local inference capacity. Hardcoding a hosted provider would remove the local-inference option. The small protocol keeps both available without adding a second routing layer.
