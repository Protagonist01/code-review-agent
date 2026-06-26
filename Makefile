.PHONY: up down restart logs test test-unit test-integration coverage eval lint format install install-dev clean

# ── Docker ─────────────────────────────────────────────────────────────────────
up:
	docker compose -f infra/docker-compose.yml up -d

down:
	docker compose -f infra/docker-compose.yml down

restart:
	docker compose -f infra/docker-compose.yml restart api worker

logs:
	docker compose -f infra/docker-compose.yml logs -f api worker

# ── Python ─────────────────────────────────────────────────────────────────────
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

# ── Tests ──────────────────────────────────────────────────────────────────────
test:
	pytest tests/

test-unit:
	pytest tests/unit/ -v --no-cov

test-integration:
	pytest tests/integration/ -v

coverage:
	pytest tests/ --cov=src --cov-report=html
	@echo "Open htmlcov/index.html to view coverage report"

# ── Evals ──────────────────────────────────────────────────────────────────────
eval:
	python evals/run_evals.py

# ── Code quality ───────────────────────────────────────────────────────────────
lint:
	ruff check src/ tests/
	mypy src/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# ── Cleanup ────────────────────────────────────────────────────────────────────
clean:
	rm -rf .pytest_cache htmlcov .coverage __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
