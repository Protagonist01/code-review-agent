.PHONY: up down logs demo test lint format build eval install-dev

COMPOSE = docker compose --env-file .env -f infra/docker-compose.yml

up:
	$(COMPOSE) up --build -d redis api worker

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api worker

install-dev:
	uv sync --locked --extra dev

demo:
	uv run --locked code-review-demo

test:
	uv run --locked pytest

lint:
	uv run --locked ruff check src tests evals scripts
	uv run --locked ruff format --check src tests evals scripts
	uv run --locked mypy src

format:
	uv run --locked ruff check --fix src tests evals scripts
	uv run --locked ruff format src tests evals scripts

build:
	uv build --no-sources
	uv run --locked python scripts/check_artifacts.py

eval:
	uv run --locked python -m evals.run_evals
