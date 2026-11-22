"""Service helper: FastAPI app with /healthz, /readyz, /metrics and JSON logging."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from falcon_core import __version__
from falcon_core.logging import configure_logging
from falcon_core.telemetry.metrics import REGISTRY as FL_REGISTRY

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]
DepCheck = Callable[[], Awaitable[bool]]

log = logging.getLogger("falcon.service")

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


def create_app(
    service: str,
    *,
    deps: Mapping[str, str | DepCheck] | None = None,
    lifespan: Lifespan | None = None,
    title: str | None = None,
) -> FastAPI:
    """Build a FastAPI app for one Falcon Lens service.

    ``deps`` maps a dependency name to a URL (TCP-checked) or an async callable;
    ``/readyz`` returns 503 until every configured dependency answers.
    """
    configure_logging(service)
    registry = CollectorRegistry()
    requests_total = Counter(
        "fl_http_requests_total",
        "HTTP requests handled",
        ["service", "method", "status"],
        registry=registry,
    )
    Gauge(
        "fl_service_info", "Service build info", ["service", "version"], registry=registry
    ).labels(service, __version__).set(1)

    checks: dict[str, DepCheck] = {
        name: (tcp_check(dep) if isinstance(dep, str) else dep)
        for name, dep in (deps or {}).items()
    }

    app = FastAPI(title=title or service, version=__version__, lifespan=lifespan)
    app.state.registry = registry

    @app.middleware("http")
    async def count_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path not in ("/healthz", "/readyz", "/metrics"):
            requests_total.labels(service, request.method, str(response.status_code)).inc()
        return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> Response:
        results = dict(
            zip(checks, await asyncio.gather(*(c() for c in checks.values())), strict=True)
        )
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
