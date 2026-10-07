# Build Book - Code Review Agent

## Index

- [Entry 1 - Recovering review publication](#entry-1---recovering-review-publication)
- [Entry 2 - Making evaluations exercise real code](#entry-2---making-evaluations-exercise-real-code)


## Entry 1 - Recovering review publication

**Files:** `src/github_client/client.py`, `tests/unit/test_github_client.py`

### Context

A worker can publish a review successfully and then lose the HTTP response. A retry currently publishes another review. A local success flag cannot resolve that ambiguous outcome because it is written after the remote request.

### Options and decision

A Redis-only completion flag misses the crash window. Querying GitHub before a retry lets the remote resource act as evidence. Use a stable digest of the intended review payload in a hidden body marker and look for that marker on the same commit before posting. This is reconciliation, not a transaction: concurrent workers can still both observe absence.

### How to build it

Serialize the commit, summary, and inline comments deterministically, hash them with SHA-256, and append an HTML comment marker. Paginate the PR review list in pages of 100. If a submitted review has the same commit and marker, return without another POST; otherwise post the marked review. Fail if the lookup fails, rather than assuming absence. Test first publication, recovery after a lost response, and pagination with a mocked HTTP client.

### Verification in progress

Run the GitHub client tests and full suite after implementation. No real GitHub writes are needed. The clean dependency install failed downloading mypy; use existing installed tools while trying an isolated package build separately.

### Result

The full suite passed: 80 tests, 93.07% coverage. Lint and strict type checks passed. Offline source and wheel builds passed; archive inspection confirmed the prompt and license are included. Retry and pagination tests prove identical published payloads are skipped. They do not prove serialization of concurrent jobs or deduplication when a new model response changes the payload.

## Entry 2 - Making evaluations exercise real code

**Date:** 2026-10-07. **Files:** `src/agent/graph.py`, `evals/run_evals.py`, `src/demo.py`, `tests/unit/test_evals.py`.

### Context

Every golden-set diff starts with `@@` and lacks file headers. The parser needs `---` and `+++` to know the file, so the old runner can report success without reviewing any hunk. It also contacts a made-up GitHub repository, and its false-positive count compares the number of comments with the number of expected issues instead of matching them.

### Before you read on

How would you use the production pipeline for an isolated evaluation while guaranteeing that repository context and review publication never contact GitHub?

### Options considered and why

Changing the production parser to guess missing paths would hide malformed input. Instead, adapt the fixture at the evaluation boundary and make graph construction accept an optional backend and an option to skip remote context. Production defaults keep context fetching and real inference. The demo injects a recorded backend and labels its output; it cannot be mistaken for a live accuracy result.

### How to build it

1. Add keyword-only `fetch_context` and `backend` arguments to `build_graph`. When context is disabled, connect the diff parser directly to the prompt builder. Bind the optional backend into the reviewer with `functools.partial`.
2. Wrap bare fixture hunks with unified-diff headers using the expected issue's file path, or an explicit synthetic path for clean cases. Reject inputs that still produce no hunks.
3. Match each expected issue to one unused comment with the same file, line, severity, and message pattern. Each unmatched comment is a false positive; each unmatched expectation is a false negative. Report precision and recall with their correct denominators.
4. Record the provider and model, compute p95 latency, enforce all declared thresholds, and return a failing exit code when the run fails.
5. Test adapters and scoring with synthetic responses. Run the whole demo graph with a recorded backend to exercise packaged prompt loading and response validation without credentials.

### What went wrong / verification in progress

The global Python environment stalls during application imports. An isolated environment from `uv.lock` is being prepared to separate project dependencies from unrelated installed packages. Docker's Linux engine is unavailable, so container execution must be verified in CI or on a host with Docker running.

### Audit verification update

The isolated Python 3.13 suite passed 99 tests with 93.85% source line coverage; lint, formatting, and strict mypy checks passed. All ten evaluation inputs now produce reviewable hunks, and scoring regression tests cover unmatched and duplicate findings. No live provider evaluation was performed. Initial imports were slow in both Python environments, so isolation did not establish a cause for that delay.

The first CLI smoke test hit Windows' cp1252 console encoding when the summary printed emoji. The demo now configures UTF-8 output for a real stdout stream and labels the recorded response explicitly. Package archive inspection passed, and a separate installed-wheel smoke test and Python 3.11 test run are underway.

### Final result

Python 3.11.15 also passed all 99 tests, with 88.05% source line coverage. Both versions exceeded the 80% threshold. The installed wheel passed both `python -I -m src.demo` and its console entry point from a directory outside the checkout on Python 3.12.13. The runtime dependency audit found no known vulnerabilities in 85 packages on the audited platform. Container configuration parsed, but Docker execution and remote GitHub Actions remain unverified. Source packages now include the linked operational docs, build book, example environment, and Docker ignore rules while excluding editorial assets and credentials.
