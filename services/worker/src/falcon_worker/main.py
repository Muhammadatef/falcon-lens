"""Falcon Lens worker (skeleton): health server plus an idle loop. The cascade lands later."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from falcon_core.config import get_settings
from falcon_core.service import create_app, run

log = logging.getLogger("falcon.worker")
settings = get_settings()


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

if __name__ == "__main__":
    run(app)
