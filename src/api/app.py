"""FastAPI application factory.

Usage
-----
Run with Uvicorn::

    uvicorn src.api.app:app --host 0.0.0.0 --port 8000

Public helpers
--------------
* :func:`create_app` — construct and configure a :class:`fastapi.FastAPI`
  instance (used by tests to get a fresh app instance).
* :func:`get_redis` — return the module-level Redis client initialised during
  lifespan startup; raises if called before the app has started.
* ``app`` — the pre-built application instance used by Uvicorn / Gunicorn.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from src.api.middleware import AccessLogMiddleware, RequestIDMiddleware
from src.api.webhook import router as webhook_router
from src.config import settings

log = structlog.get_logger()

# Module-level Redis client — initialised in ``lifespan``, closed on shutdown.
_redis: aioredis.Redis | None = None


# ── Redis accessor ────────────────────────────────────────────────────────────


def get_redis() -> aioredis.Redis:
    """Return the shared async Redis client.

    Returns:
        The Redis client created during application startup.

    Raises:
        RuntimeError: If called before the application lifespan has started
            (i.e. before ``startup`` has run).
    """
    if _redis is None:
        raise RuntimeError("Redis not initialised — app not started yet")
    return _redis


# ── Logging setup ─────────────────────────────────────────────────────────────


def _configure_logging() -> None:
    """Configure structlog for JSON or pretty-printed console output.

    The output format is controlled by ``settings.log_json``:

    * ``True`` → machine-readable JSON (suitable for log aggregators).
    * ``False`` → colourised dev console output (suitable for local hacking).

    The minimum log level is taken from ``settings.log_level`` (e.g.
    ``"INFO"``, ``"DEBUG"``).
    """
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if settings.log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and graceful shutdown.

    Startup
    ~~~~~~~
    * Configure structured logging.
    * Open the async Redis connection pool.

    Shutdown
    ~~~~~~~~
    * Flush and close the Redis connection pool.
    """
    global _redis  # noqa: PLW0603

    _configure_logging()

    owns_redis = _redis is None
    if owns_redis:
        _redis = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    log.info("app.started", host=settings.api_host, port=settings.api_port)

    try:
        yield
    finally:
        if owns_redis and _redis is not None:
            await _redis.aclose()
            _redis = None
        log.info("app.shutdown")


# ── Application factory ───────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build and return a configured :class:`fastapi.FastAPI` instance.

    Middleware stack (outermost → innermost):

    1. :class:`~src.api.middleware.RequestIDMiddleware` — stamp request IDs.
    2. :class:`~src.api.middleware.AccessLogMiddleware` — log every request.

    Routes:

    * ``POST /webhook`` — GitHub webhook receiver.
    * ``GET  /health``  — liveness probe.
    * ``GET  /metrics`` — Prometheus scrape endpoint.

    Returns:
        A fully wired :class:`fastapi.FastAPI` application.
    """
    app = FastAPI(
        title="AI Code Review Agent",
        description="GitHub PR reviewer with configurable local or hosted inference",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    # Middleware (added in reverse order — last added = outermost)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # Routers
    app.include_router(webhook_router)

    # ── Built-in endpoints ────────────────────────────────────────────────────

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Kubernetes/Docker liveness probe — always returns 200 OK."""
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    async def ready() -> PlainTextResponse:
        """Check API-to-Redis connectivity; workers and providers are separate checks."""
        try:
            await get_redis().ping()
        except Exception:
            return PlainTextResponse("Redis unavailable", status_code=503)
        return PlainTextResponse("ready")

    @app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
    async def metrics() -> str:
        """Prometheus scrape endpoint — returns all registered metrics."""
        return generate_latest().decode("utf-8")

    return app


# Pre-built application instance consumed by Uvicorn / Gunicorn.
app = create_app()
