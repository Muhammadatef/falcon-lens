"""Cache + single-flight shared by the network signals (``ctx.cache``).

Two interchangeable stores: ``RedisCache`` (production, ``redis.asyncio``) and ``MemoryCache`` (tests and
the default when ``ctx.cache`` is ``None``). Both hold JSON-serialisable values and a few set operations
used by the feed mirror. ``single_flight`` collapses concurrent identical lookups in one process.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol, cast


class KV(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl_s: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def sismember(self, key: str, member: str) -> bool: ...
    async def replace_set(self, key: str, members: Iterable[str]) -> int: ...
    async def scard(self, key: str) -> int: ...


class MemoryCache:
    """In-process KV with TTL. ``clock`` is injectable so tests control expiry."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._sets: dict[str, frozenset[str]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, exp = item
        if exp is not None and exp <= self._clock():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        self._data[key] = (value, None if ttl_s is None else self._clock() + ttl_s)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._sets.pop(key, None)

    async def sismember(self, key: str, member: str) -> bool:
        return member in self._sets.get(key, frozenset())

    async def replace_set(self, key: str, members: Iterable[str]) -> int:
        self._sets[key] = frozenset(members)
        return len(self._sets[key])

    async def scard(self, key: str) -> int:
        return len(self._sets.get(key, frozenset()))


class RedisCache:
    """redis.asyncio-backed KV (values are JSON). Pass a ``redis.asyncio.Redis`` client."""

    def __init__(self, client: Any, prefix: str = "") -> None:
        self._r = client
        self._p = prefix

    async def get(self, key: str) -> Any | None:
        raw = await self._r.get(self._p + key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        await self._r.set(self._p + key, json.dumps(value, separators=(",", ":")), ex=ttl_s)

    async def delete(self, key: str) -> None:
        await self._r.delete(self._p + key)

    async def sismember(self, key: str, member: str) -> bool:
        return bool(await self._r.sismember(self._p + key, member))

    async def replace_set(self, key: str, members: Iterable[str]) -> int:
        """Build into a temp key then RENAME, so readers never see a half-loaded set."""
        full, tmp = self._p + key, f"{self._p}{key}:tmp"
        await self._r.delete(tmp)
        n = 0
        batch: list[str] = []
        for m in members:
            batch.append(m)
            if len(batch) >= 1000:
                await self._r.sadd(tmp, *batch)
                n += len(batch)
                batch = []
        if batch:
            await self._r.sadd(tmp, *batch)
            n += len(batch)
        if n == 0:
            await self._r.delete(full)
        else:
            await self._r.rename(tmp, full)
        return n

    async def scard(self, key: str) -> int:
        return int(await self._r.scard(self._p + key))


_DEFAULT = MemoryCache()


def default_cache() -> MemoryCache:
    return _DEFAULT


def get_cache(ctx: Any) -> KV:
    c = getattr(ctx, "cache", None)
    return cast(KV, c) if c is not None else _DEFAULT


def get_clock(ctx: Any) -> Callable[[], float]:
    c = getattr(ctx, "clock", None)
    return c if callable(c) else time.time


_INFLIGHT: dict[str, asyncio.Task[Any]] = {}


async def single_flight[T](key: str, fn: Callable[[], Awaitable[T]]) -> T:
    """Run ``fn`` once per key across concurrent callers in this process.

    The work runs in its own task and waiters ``shield`` it, so one caller timing out (signal budget)
    does not cancel the lookup the others (and the cache) still benefit from."""
    task = _INFLIGHT.get(key)
    if task is None:

        async def runner() -> T:
            return await fn()

        task = asyncio.ensure_future(runner())
        _INFLIGHT[key] = task

        def _done(t: asyncio.Task[Any]) -> None:
            if _INFLIGHT.get(key) is t:
                del _INFLIGHT[key]
            if not t.cancelled():
                t.exception()  # mark retrieved; waiters still see it via await

        task.add_done_callback(_done)
    return cast(T, await asyncio.shield(task))
