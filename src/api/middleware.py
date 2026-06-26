"""ASGI middleware for request-ID injection and structured access logging.

Two middleware classes are provided:

* :class:`RequestIDMiddleware` — attaches a UUID to every request/response
  via the ``X-Request-ID`` header and stores it on ``request.state``.
* :class:`AccessLogMiddleware` — emits a structured log line for every
  completed request, including method, path, status code, and latency.

Both middleware classes extend ``starlette.middleware.base.BaseHTTPMiddleware``
and can be added to any FastAPI / Starlette application.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a unique ``X-Request-ID`` header on every request/response.

    The generated UUID is also stored on ``request.state.request_id`` so
    that downstream handlers (route functions, other middleware) can
    include it in log entries or error responses.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Attach a fresh UUID to the request state and outgoing headers."""
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emit a structured access log line for every completed HTTP request.

    Log fields emitted:

    * ``method`` — HTTP verb (GET, POST, …)
    * ``path`` — URL path (no query string)
    * ``status`` — HTTP response status code
    * ``duration_ms`` — wall-clock latency in milliseconds (2 d.p.)
    * ``request_id`` — value set by :class:`RequestIDMiddleware`, or ``"-"``
      if that middleware was not installed.

    .. note::
        This middleware should be added *after* :class:`RequestIDMiddleware`
        in the middleware stack so that ``request.state.request_id`` is
        already populated when the log line is emitted.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Time the request and log the outcome once a response is returned."""
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        request_id = getattr(request.state, "request_id", "-")
        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
            request_id=request_id,
        )
        return response
