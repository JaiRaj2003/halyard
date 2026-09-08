"""Correlation ids and request logging at the HTTP boundary.

One id per HTTP exchange, taken from the caller's ``X-Request-ID`` when it
looks like one and minted otherwise, returned on every response — including
error responses — and set in the request context so anything logged while the
request is being served can be tied back to it.

What is logged is deliberately narrow: id, method, route template, path,
status and duration. Never a body, a query string, an ask, a person or any
evidence — the domain already records what happened to a request as events on
the request itself; these lines only say that the server was asked and how it
answered.
"""

from __future__ import annotations

import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..observability import REQUEST_ID_HEADER, request_id_var, resolve_request_id

logger = logging.getLogger("halyard.http")


class RequestContextMiddleware:
    """Pure ASGI middleware: correlation id in, correlation id out, one log line.

    Written against the raw ASGI interface rather than ``BaseHTTPMiddleware`` so
    the context variable is set in the same task that runs the endpoint, and so
    a failure after the response has started is not mistaken for one we can
    still answer.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status: int | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception as exc:
                logger.exception(
                    "unhandled_error request_id=%s method=%s route=%s path=%s error=%s",
                    request_id,
                    scope["method"],
                    _route_template(scope),
                    scope["path"],
                    type(exc).__name__,
                )
                if status is not None:
                    raise
                status = 500
                response = JSONResponse(
                    {"detail": "Internal server error", "request_id": request_id},
                    status_code=status,
                    headers={REQUEST_ID_HEADER: request_id},
                )
                await response(scope, receive, send)
        finally:
            logger.info(
                "request request_id=%s method=%s route=%s path=%s status=%s duration_ms=%.1f",
                request_id,
                scope["method"],
                _route_template(scope),
                scope["path"],
                status if status is not None else "-",
                (time.perf_counter() - started) * 1000,
            )
            request_id_var.reset(token)


def _route_template(scope: Scope) -> str:
    """``/api/requests/{request_key}`` rather than the concrete path, once routed."""
    route = scope.get("route")
    return route.path if isinstance(route, Route) else "-"
