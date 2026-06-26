# ADR-001: Use a Local LLM via Ollama Instead of a Third-Party API

## Status
Accepted

## Context
The core value proposition of this project is privacy-preserving code review. Engineering teams handle proprietary source code, unreleased features, and security-sensitive logic in PRs. Sending diffs to a third-party LLM API (OpenAI, Anthropic, etc.) introduces:

- **Data residency risk** — code processed on external infrastructure
- **Vendor dependency** — API outages block reviews
- **Cost unpredictability** — token pricing scales with PR volume
- **Compliance friction** — some orgs prohibit sending source code externally under SOC 2 / ISO 27001 policies

The question was: can a locally-hosted open-weight model produce reviews good enough to be useful?

## Decision
Use **Ollama** as the local LLM runtime, defaulting to **CodeLlama 7B** with support for swapping to Mistral or Llama 3 via config.

Ollama was chosen over alternatives (llama.cpp directly, vLLM, LM Studio) because:
- Single binary, Docker-native, no CUDA setup required for CPU inference
- Model pull via CLI (`ollama pull codellama`) mirrors Docker's UX — low barrier for contributors
- REST API is OpenAI-compatible, making future cloud fallback a one-line config change
- Active maintenance and broad model support

The model is configurable via `OLLAMA_MODEL` in `.env` so teams can swap to larger models if GPU is available.

## Consequences

**Gained:**
- Zero code leaves the local environment
- No API costs or rate limits
- Works airgapped
- Demonstrates understanding of local inference infrastructure

**Trade-offs:**
- Review latency is 10–30s on CPU vs ~2s with GPT-4o API
- 7B models produce lower-quality reviews than frontier models — acknowledged in README limitations
- Requires ~5GB disk for model weights
- GPU recommended for production use; documented in setup guide
