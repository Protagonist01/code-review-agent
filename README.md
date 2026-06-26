<div align="center">

# 🤖 AI Code Review Agent

**Autonomous, privacy-first AI code review that runs on your infrastructure.**

Listens for GitHub PR events → parses diffs → runs LLM review → posts inline comments, summary, and commit status — all without sending code anywhere you don't control.

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-FF6F00?style=flat-square&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Coverage](https://img.shields.io/badge/Coverage-≥80%25-4CAF50?style=flat-square)](https://pytest-cov.readthedocs.io/)

</div>

---

![demo](docs/assets/demo.gif)

---

## Table of Contents

- [Overview](#overview)
- [What It Does](#what-it-does)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [LLM Backend Options](#llm-backend-options)
- [How It Works](#how-it-works)
- [Testing](#testing)
- [Evaluation](#evaluation)
- [Monitoring](#monitoring)
- [Project Structure](#project-structure)
- [Limitations & Roadmap](#limitations--roadmap)

---

## Overview

Most AI code review tools send your code to a third-party API. This project takes a different approach: **the backend is swappable**, so you choose where your code goes.

| Path | Provider | Privacy | Setup |
|---|---|---|---|
| ⚡ Quick start | OpenRouter (free) | Code leaves machine | 2 mins |
| 🔒 Private | Ollama (local) | Zero code egress | Requires GPU/CPU |
| 🏢 Enterprise | OpenAI / Anthropic / Groq | Vendor ToS applies | API key only |

The engineering focus here was on the surrounding system: HMAC-authenticated webhooks, async job processing via Celery + Redis, a LangGraph state machine for the review pipeline, structured output parsing, and a Prometheus/Grafana observability stack.

---

## What It Does

- 📥 **Ingests** GitHub PR `opened` / `synchronize` webhook events (HMAC-signed)
- 🔪 **Parses** the unified diff into isolated hunks with file + line context
- 🌳 **Fetches** repo context (README, file tree, detected language) to ground reviews
- 🧠 **Reviews** each hunk via the configured LLM backend — bugs, security issues, style violations
- 💬 **Posts inline comments** at the exact file + line position on the PR
- 📋 **Posts a summary comment** with a severity breakdown
- ✅ **Sets a commit status** — `✅ clean` / `⚠️ warnings` / `❌ issues found`

---

## Architecture

```
GitHub PR Event  (HMAC-SHA256 signed webhook)
        │
        ▼
FastAPI Gateway ──── HMAC auth ──── Rate limiter (Redis)
        │
        ▼
Celery Worker  (async job queue)
        │
        ▼
LangGraph Agent
  ├── Diff Parser       → splits raw diff into reviewable hunks
  ├── Context Fetcher   → repo tree, README, language detection
  ├── Prompt Builder    → assembles structured prompt per hunk
  ├── LLM Backend       → OpenRouter | Ollama | Groq | OpenAI | Anthropic
  └── Response Parser   → validates FILE | LINE | SEVERITY | MESSAGE format
        │
        ▼
GitHub API Client
  ├── Inline review comments  (line-level)
  ├── PR summary comment
  └── Commit status update
        │
        ▼
Observability Stack
  ├── Prometheus metrics  (latency, tokens, comment counts, errors)
  ├── Structured JSON logs → Loki
  └── Grafana dashboard   (infra/grafana/dashboard.json)
```

---

## Quick Start

**Prerequisites:** Docker, Docker Compose, a GitHub App (takes ~3 mins to create)

```bash
# 1. Clone and configure
git clone https://github.com/Protagonist01/code-review-agent
cd code-review-agent
cp .env.example .env
```

Open `.env` and fill in your GitHub App credentials, then pick an LLM backend:

```bash
# Option A — OpenRouter free tier (recommended for demos, no GPU needed)
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_key_here        # free at openrouter.ai/keys
OPENROUTER_MODEL=cohere/north-mini-code:free

# Option B — Local Ollama (zero code egress, runs on your machine)
LLM_PROVIDER=ollama
# then pull a model:
docker run --rm ollama/ollama pull codellama:7b

# Option C — Paid frontier API
LLM_PROVIDER=openai   # or: groq | anthropic
OPENAI_API_KEY=your_key_here
```

```bash
# 2. Start the full stack
docker compose -f infra/docker-compose.yml up --build

# 3. Expose locally for webhook delivery
.\tools\cloudflared.exe tunnel --url http://localhost:8000

# 4. Register the webhook in your GitHub App settings:
#    Payload URL → https://<your-trycloudflare-url>/webhook
#    Content type → application/json
#    Events → Pull requests
```

> Your first PR will trigger a review in **~2–5s** on OpenRouter/Groq, or **~15–30s** with local Ollama on CPU.

For daily start/stop, log tailing, and tunnel commands, see [`docs/run-cheatsheet.md`](docs/run-cheatsheet.md).

---

## LLM Backend Options

| Provider | `LLM_PROVIDER` | Key Required | Notes |
|---|---|---|---|
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | Free `:free` models available — best for demos |
| Ollama | `ollama` | None | Fully local; quality depends on model size |
| Groq | `groq` | `GROQ_API_KEY` | Very fast inference; generous free tier |
| OpenAI | `openai` | `OPENAI_API_KEY` | High quality; default `gpt-4o-mini` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Best for complex reasoning; default `claude-haiku-4-5` |

Switching backends requires **only a config change** — no code changes. The LLM is abstracted behind a common interface in the LangGraph agent.

---

## How It Works

### 1. Webhook Authentication
Every incoming request is verified against GitHub's HMAC-SHA256 signature before any processing begins. Invalid signatures return `403` immediately with no detail leaked.

### 2. Diff Parsing
Raw unified diffs are parsed into **hunks** — isolated change blocks with surrounding context lines. Each hunk is reviewed independently to keep prompts focused and within the LLM's context window.

### 3. LangGraph State Machine
The review pipeline is a LangGraph graph with explicit state transitions. This makes the pipeline:
- **Inspectable** — each node has a defined input/output schema
- **Testable** — nodes can be unit-tested in isolation
- **Extensible** — new steps (e.g., cross-file reasoning) slot in without rewriting control flow

See [`docs/adr/002-langgraph-vs-custom-loop.md`](docs/adr/002-langgraph-vs-custom-loop.md) for the design rationale.

### 4. Prompt Design
Prompts are stored as versioned `.txt` files in `src/agent/prompts/`, not hardcoded in Python. This makes prompt iteration trackable in git — `git log` shows the full prompt evolution.

### 5. Structured Output Parsing
The LLM responds in a strict `FILE | LINE | SEVERITY | MESSAGE` format. The response parser validates this structure and **silently discards malformed outputs** rather than posting garbled comments.

---

## Testing

```bash
make test              # run all tests
make test-unit         # fast unit tests only (no Docker)
make test-integration  # full webhook-to-GitHub-API flow (Docker required; LLM calls mocked)
make coverage          # generates htmlcov/index.html
```

| Suite | What it covers |
|---|---|
| `tests/unit/` | Diff parser, response parser, HMAC auth — pure functions, no I/O |
| `tests/integration/` | Full webhook → Celery → agent → GitHub API flow with mocked responses |
| `tests/fixtures/` | Real `.patch` files from open-source repos for deterministic replay |

**Coverage gate:** CI fails below 80% line coverage.

---

## Evaluation

Beyond unit tests, review quality is measured against a curated golden set:

```bash
make eval
```

`evals/golden_set.jsonl` contains **50 real diffs** with known issues (seeded bugs, security vulnerabilities, style violations).

| Metric | Target |
|---|---|
| True positive rate (known issues caught) | ≥ 70% |
| False positive rate (correct code flagged) | ≤ 15% |
| Comment parse success rate | ≥ 98% |
| Mean review latency (p95) | < 30s |

Results are written to `evals/results/latest.json` and tracked over time to catch prompt regressions.

---

## Monitoring

The full Grafana dashboard is committed at `infra/grafana/dashboard.json` — import it directly after `make up`.

**Prometheus metrics exposed at `/metrics`:**

| Metric | Description |
|---|---|
| `review_duration_seconds` | End-to-end PR review latency histogram |
| `llm_tokens_used_total` | Token consumption by model |
| `comments_posted_total` | Comments posted, labelled by severity |
| `webhook_errors_total` | Auth failures, parse errors, GitHub API errors |
| `active_reviews` | In-flight review jobs (gauge) |

**Alerts** (defined in `infra/prometheus/alert_rules.yml`):
- Review latency p95 > 60s → Slack / PagerDuty
- Error rate > 5% over 5 minutes → Slack

---

## Project Structure

```
code-review-agent/
├── src/
│   ├── agent/              # LangGraph agent + nodes
│   │   └── prompts/        # versioned .txt prompt files
│   ├── api/                # FastAPI gateway + webhook endpoint
│   ├── github_client/      # thin GitHub API wrapper
│   ├── config.py           # pydantic-settings config
│   └── worker.py           # Celery worker definition
├── tests/
│   ├── unit/               # pure function tests
│   ├── integration/        # end-to-end flow tests
│   └── fixtures/           # real .patch files for replay
├── evals/
│   ├── golden_set.jsonl    # 50 labelled diffs
│   └── run_evals.py        # eval runner + metrics
├── infra/
│   ├── docker-compose.yml
│   ├── prometheus/         # scrape config + alert rules
│   └── grafana/
│       └── dashboard.json  # importable Grafana dashboard
├── docs/
│   ├── adr/                # Architecture Decision Records
│   └── run-cheatsheet.md   # daily dev commands
├── tools/                  # local dev utilities (cloudflared)
├── .env.example
├── Makefile
└── pyproject.toml
```

---

## Limitations & Roadmap

**Current limitations:**
- Reviews are per-hunk — cross-file issues (e.g., a function renamed in one file but not updated in another) are not detected
- No memory between PRs — the agent doesn't learn a repo's coding patterns over time
- Local Ollama inference speed is hardware-dependent; free OpenRouter models are recommended on low-spec machines

**Planned:**
- [ ] Cross-hunk reasoning pass after per-hunk review
- [ ] Repo-level memory via vector store (track recurring patterns per repo)
- [ ] Per-repo review rules defined in `.review-agent.yml`
- [ ] Streaming comment posting (post as comments are generated, not batch at end)

---

## License

[MIT](LICENSE) — use it, fork it, ship it.
