FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.11-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

LABEL org.opencontainers.image.source="https://github.com/Protagonist01/code-review-agent" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
