"""Falcon Lens worker (skeleton): health server plus an idle loop. The cascade lands later.

Network note: the worker is the only service besides egress-proxy that shares a network with the
sandbox (`sandbox_ctl`). Docker networks are not directional, so the sandbox can reach this port.
The worker therefore exposes ONLY /healthz, /readyz and /metrics (plus /metrics/sandbox) on it:
never a job or control API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse

from falcon_core.config import get_settings
from falcon_core.service import create_app, run

log = logging.getLogger("falcon.worker")
settings = get_settings()

SANDBOX_METRICS_URL = "http://sandbox:8000/metrics"


async def idle_loop(interval: float = 30.0) -> None:
    while True:
        log.info("worker idle")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(idle_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


deps: dict[str, str] = {}
if settings.redis_url:
    deps["redis"] = settings.redis_url
if settings.database_url:
    deps["postgres"] = settings.database_url.get_secret_value()

app = create_app("worker", deps=deps, lifespan=lifespan, title="Falcon Lens worker")


@app.get("/metrics/sandbox", include_in_schema=False)
async def sandbox_metrics() -> Response:
    """Relay the sandbox's metrics so Prometheus never needs a route into the sandbox network."""
    token = settings.fl_sandbox_token
    headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(SANDBOX_METRICS_URL, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("sandbox metrics relay failed: %s", exc)
        return PlainTextResponse("# sandbox metrics unavailable\n", status_code=503)
    return PlainTextResponse(resp.text, media_type=resp.headers.get("content-type", "text/plain"))


if __name__ == "__main__":
    run(app)
