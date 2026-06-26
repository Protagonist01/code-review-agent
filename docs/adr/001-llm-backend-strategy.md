# ADR-001: Abstracted LLM Backend with OpenRouter Default

## Status
Accepted

## Context
The core value proposition of this project is privacy-preserving code review. Engineering teams handle proprietary source code, unreleased features, and security-sensitive logic in PRs. The ideal solution lets teams choose where inference runs based on their own trust, hardware, and cost constraints â€” rather than hardcoding a single provider.

Three valid deployment profiles exist:

1. **Fully local** â€” maximum privacy, no code leaves the machine, requires a GPU or tolerance for slow CPU inference
2. **Cloud inference on free/open-weight models** - code is sent to a third-party provider such as OpenRouter or Groq. Fast/free tiers are useful for development and demos
3. **Frontier model API** â€” highest review quality, code sent externally, pay-per-token

The question was whether to pick one and hardcode it, or build an abstraction layer.

## Decision
Implement a **swappable LLM backend** behind a common interface, controlled by a single `LLM_PROVIDER` environment variable. The project identity is local-first code review: `ollama` is the privacy-preserving deployment path, while `openrouter` is the default quick-start path for demos and low-friction local testing.

**Supported backends:**

| Backend | `LLM_PROVIDER` value | Speed | Cost | Privacy |
|---------|---------------------|-------|------|---------|
| OpenRouter free model | `openrouter` | A few seconds per review | Free tier | Code sent to OpenRouter/provider |
| Groq (Llama 3 / Mixtral) | `groq` | ~3-5s per review | Free/paid tiers | Code sent to Groq |
| Ollama (local) | `ollama` | ~15-30s CPU, ~5s GPU | Free | Zero data leaves machine |
| OpenAI / Anthropic | `openai` / `anthropic` | ~2-4s | Pay per token | Code sent externally |

The backend abstraction lives in `src/agent/llm_backend.py`. Each backend implements the same interface:

```python
class LLMBackend(Protocol):
    async def complete(self, prompt: str, system: str) -> str: ...
```

Switching backends requires no changes outside `.env`.

**Why OpenRouter as the quick-start default:**
- Gives the project a free API path without requiring a GPU
- Uses the OpenAI-compatible Chat Completions shape, so the implementation stays small
- Lets users swap among current free `:free` models from `.env` without code changes
- Keeps paid frontier providers optional instead of required for first setup
- Lowers the hardware barrier to zero - the project works on any laptop

**Why Ollama remains fully supported:**
- Teams with sensitive codebases or compliance requirements need a zero-egress option
- Airgapped environments require fully local inference
- The Ollama REST API is OpenAI-compatible â€” it slots into the same backend interface with no special-casing
- Ollama is the backend that best represents the project's local-first identity

## Consequences

**Gained:**
- Any developer can run the project without a GPU by using the OpenRouter free API path
- Privacy-sensitive teams can use local Ollama with one config change
- The backend is independently testable â€” integration tests mock the `LLMBackend` interface, so they run without any live LLM
- Adding a new backend (e.g. Fireworks AI, Together AI) requires implementing one method and registering it in `src/agent/llm_backend.py`
- Eval results in `evals/results/` are tagged with the backend used â€” quality differences between providers are measurable

**Trade-offs:**
- The abstraction layer adds a small amount of indirection â€” contributors need to understand the `LLMBackend` protocol before adding provider-specific features (e.g. function calling)
- Free provider tiers have rate limits and model availability can change; heavy PR volume may require a paid plan or local Ollama
- Review quality varies across backends; the eval golden set should be run against each backend separately to understand quality trade-offs.

**Alternatives considered:**
- **Hardcode Ollama** â€” rejected; too high a hardware barrier for most developers and demo environments
- **Hardcode a cloud API** â€” rejected; undermines the privacy-first positioning and adds mandatory cost
- **LiteLLM as the abstraction** â€” considered; provides a unified interface over 100+ providers. Deferred because it adds a heavy dependency for a project that only needs 3â€“4 backends. Can be adopted later if the backend list grows

