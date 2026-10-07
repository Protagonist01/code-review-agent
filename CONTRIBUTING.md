# Contributing

Keep pull requests focused. Explain the problem, resulting behavior, and verification. Discuss substantial design changes in an issue first.

Use Python 3.11+ and uv from the repository root:

```bash
uv sync --locked --extra dev
uv run --locked pytest
uv run --locked ruff check src tests evals scripts
uv run --locked ruff format --check src tests evals scripts
uv run --locked mypy src
uv build --no-sources
uv run --locked python scripts/check_artifacts.py
```

Add regression tests for behavior changes. Mock external services and use synthetic fixtures; tests must not use live credentials or post to real pull requests. The offline demo exercises the pipeline without network calls.

For dependency changes, edit `pyproject.toml`, run `uv lock`, then `uv sync --locked --extra dev` and repeat the checks. Commit the updated lockfile. Use `uv lock --upgrade-package PACKAGE` for targeted updates and inspect the resulting diff.

Format with `uv run --locked ruff format src tests evals scripts`. The Makefile is a convenience for POSIX shells; the commands above also work in PowerShell.

Never commit credentials, logs, caches, local tools, or generated evaluation results. Update documentation when configuration or behavior changes. Keep private repository code out of issues and pull requests. Follow the security reporting instructions in SECURITY.md.

Treat contributors respectfully. Contributions use the repository's MIT license.
