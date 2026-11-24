"""Service helper: FastAPI app with /healthz, /readyz, /metrics and JSON logging."""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry import context as otel_context
from opentelemetry.propagate import extract
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)
from starlette.types import Receive, Scope, Send

from falcon_core import __version__
from falcon_core.logging import configure_logging
from falcon_core.telemetry.metrics import REGISTRY as FL_REGISTRY
from falcon_core.telemetry.tracing import fl_span, setup_tracing

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]
DepCheck = Callable[[], Awaitable[bool]]

log = logging.getLogger("falcon.service")
_TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")

_DEFAULT_PORTS = {"postgresql": 5432, "postgres": 5432, "redis": 6379, "http": 80, "https": 443}


def tcp_check(url: str, timeout: float = 1.5) -> DepCheck:
    """Dependency check: can we open a TCP connection to the host:port in ``url``."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or _DEFAULT_PORTS.get(parts.scheme, 0)

    async def check() -> bool:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except (OSError, TimeoutError):
            return False
        writer.close()
        return True

    return check


_TRACE_HEADERS = (b"traceparent", b"tracestate", b"baggage")


class _FalconApp(FastAPI):
    """FastAPI's native tracing adopts any inbound trace context before user middleware runs, so untrusted
    callers' W3C trace headers are dropped here, ahead of it."""

    trust: Callable[[Request], bool] = staticmethod(lambda _r: False)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        has_trace = scope["type"] in ("http", "websocket") and any(
            k.lower() in _TRACE_HEADERS for k, _ in scope["headers"]
        )
        if has_trace and not self.trust(Request(scope)):
            scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() not in _TRACE_HEADERS]}
        await super().__call__(scope, receive, send)


def create_app(
    service: str,
    *,
    deps: Mapping[str, str | DepCheck] | None = None,
    lifespan: Lifespan | None = None,
    title: str | None = None,
    protect: bool = False,
    token: str | None = None,
    trust_traceparent: Callable[[Request], bool] | None = None,
) -> FastAPI:
    """Build a FastAPI app for one Falcon Lens service.

    ``deps`` maps a dependency name to a URL (TCP-checked) or an async callable;
    ``/readyz`` returns 503 until every configured dependency answers.

    With ``protect=True`` every path except ``/healthz`` and ``/readyz`` needs
    ``Authorization: Bearer <token>`` (fail-closed: 503 if no token is configured).

    An inbound W3C ``traceparent`` is adopted only when ``trust_traceparent(request)`` is true (a trusted internal
    caller); otherwise, and by default, every request starts a fresh trace so outside callers cannot inject trace ids.
    """
    configure_logging(service)
    trust = trust_traceparent or (lambda _r: False)
    # Spans go to the otel-collector (-> Phoenix) only when OTEL_EXPORTER_OTLP_ENDPOINT is set.
    setup_tracing(service)
    registry = CollectorRegistry()
    requests_total = Counter(
        "fl_http_requests_total",
        "HTTP requests handled",
        ["service", "method", "status"],
        registry=registry,
    )
    Gauge("fl_service_info", "Service build info", ["service", "version"], registry=registry).labels(
        service, __version__
    ).set(1)

    checks: dict[str, DepCheck] = {
        name: (tcp_check(dep) if isinstance(dep, str) else dep) for name, dep in (deps or {}).items()
    }

    app = _FalconApp(title=title or service, version=__version__, lifespan=lifespan)
    app.trust = trust
    app.state.registry = registry

    if protect:

        @app.middleware("http")
        async def require_token(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            if request.url.path in ("/healthz", "/readyz"):
                return await call_next(request)
            if not token:
                return JSONResponse({"detail": "service token not configured"}, status_code=503)
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            return await call_next(request)

    @app.middleware("http")
    async def count_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path in ("/healthz", "/readyz", "/metrics"):
            return await call_next(request)
        # Route template only (never the raw path or query: they can carry ids or URLs).
        # A valid W3C `traceparent` makes this span a child of the caller's (voice checks link this way).
        parent = request.headers.get("traceparent", "")
        token = otel_context.attach(extract({"traceparent": parent})) if _TRACEPARENT_RE.match(parent) else None
        try:
            with fl_span(f"http {request.method}", "CHAIN", **{"fl.source": service}) as sp:
                response = await call_next(request)
                route = request.scope.get("route")
                sp.set_attribute("http.request.method", request.method)
                sp.set_attribute("http.route", str(getattr(route, "path", "unmatched"))[:80])
                sp.set_attribute("http.response.status_code", response.status_code)
        finally:
            if token is not None:
                otel_context.detach(token)
        requests_total.labels(service, request.method, str(response.status_code)).inc()
        return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> Response:
        results = dict(zip(checks, await asyncio.gather(*(c() for c in checks.values())), strict=True))
        ready = all(results.values())
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "service": service, "deps": results},
            status_code=200 if ready else 503,
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        # fl_ metrics live in one shared registry (falcon_core.telemetry.metrics).
        body = generate_latest(registry) + generate_latest(FL_REGISTRY)
        return Response(body, media_type=CONTENT_TYPE_LATEST)

    return app


def run(app: Any, port: int = 8000) -> None:  # pragma: no cover - thin uvicorn wrapper
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None, access_log=False)
