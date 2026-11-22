"""Falcon Lens Sentinel (skeleton): health server plus an idle consumer on stream fl:events.

Correlation, rules and the LangGraph agent land in later task cards. This stub only joins
the consumer group so the wiring (stream, group, restart policy) is proven.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import redis.asyncio as aioredis
from fastapi import FastAPI
from redis.exceptions import RedisError, ResponseError

from falcon_core.config import get_settings
from falcon_core.service import create_app, run

log = logging.getLogger("falcon.sentinel")
settings = get_settings()

STREAM = "fl:events"
GROUP = "sentinel"
CONSUMER = f"sentinel-{os.environ.get('HOSTNAME') or socket.gethostname()}"


async def consume(url: str) -> None:
    """Idle consumer: read, log and ack (events are ignored until rules exist)."""
    client = aioredis.from_url(url, decode_responses=True)
    try:
        while True:
            try:
                try:
                    await client.xgroup_create(STREAM, GROUP, id="$", mkstream=True)
                except ResponseError as exc:
                    if "BUSYGROUP" not in str(exc):
                        raise
                while True:
                    batches = await client.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=10, block=5000)
                    for _stream, entries in batches:
                        for entry_id, _fields in entries:
                            log.info("event received (stub, ignored)", extra={"entry_id": entry_id})
                            await client.xack(STREAM, GROUP, entry_id)
            except (RedisError, OSError) as exc:
                log.warning("redis unavailable, retrying: %s", exc)
                await asyncio.sleep(2)
    finally:
        await client.aclose()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(consume(settings.redis_url or "redis://redis:6379/0"))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = create_app(
    "sentinel",
    deps={"redis": settings.redis_url or "redis://redis:6379/0"},
    lifespan=lifespan,
    title="Falcon Lens Sentinel",
)

if __name__ == "__main__":
    run(app)
