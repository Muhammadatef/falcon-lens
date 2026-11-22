"""Redis Streams consumer for `fl:events` (ADR-002 "Listen").

At-least-once: XREADGROUP + XACK, stale pending entries are taken over with XAUTOCLAIM, handlers are idempotent
on event_id (Redis set + primary key in sentinel_features), and an entry that fails 3 times goes to the
`fl:events:dlq` stream and is acked. Features and incidents are persisted before the ack, so a restart
rehydrates the same state (review finding 7).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from redis.exceptions import ResponseError
from sentinel_core.events import Event, parse_event
from sentinel_core.incidents import Sentinel

from . import metrics as m
from .db import IncidentCache, Repo

log = logging.getLogger("falcon.sentinel.consumer")

STREAM = "fl:events"
GROUP = "sentinel"
DLQ = "fl:events:dlq"
PROCESSED = "fl:sentinel:processed"
FAILS = "fl:sentinel:fails"
MAX_FAILURES = 3


class Consumer:
    def __init__(
        self,
        redis: Any,
        repo: Repo,
        cache: IncidentCache,
        sentinel: Sentinel,
        name: str,
        on_incidents: Callable[[list[str]], Awaitable[None]] | None = None,
        min_idle_ms: int = 30_000,
    ) -> None:
        self.redis, self.repo, self.cache, self.sentinel = redis, repo, cache, sentinel
        self.name = name
        self.on_incidents = on_incidents
        self.min_idle_ms = min_idle_ms

    async def setup(self) -> int:
        """Create the group and rehydrate the deterministic core from Postgres. Returns events replayed."""
        try:
            await self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        await self.cache.load()
        raws = await self.repo.load_features()
        events = [parse_event(r) for r in raws]
        self.sentinel.process(
            events
        )  # idempotent: existing incidents are already stored, nothing changes
        await self.cache.flush()
        return len(events)

    @staticmethod
    def _decode(fields: dict[str, str]) -> dict[str, Any]:
        raw = fields.get("event") or fields.get("data")
        if raw is None:
            raise ValueError("stream entry has no 'event' field")
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("event is not an object")
        return obj

    async def handle(self, entry_id: str, fields: dict[str, str]) -> list[str]:
        """Process one entry; raises on failure (caller counts failures). Returns changed incident ids."""
        data = self._decode(fields)
        ev: Event = parse_event(data)
        ms = int(entry_id.split("-")[0])
        m.EVENT_LAG.set(max(0.0, time.time() - ms / 1000))
        if await self.redis.sismember(PROCESSED, ev.event_id):
            return []
        await self.repo.add_features([data])
        before = {i["incident_id"]: i for i in self.cache.all()}
        changed = self.sentinel.process([ev])
        written, _deleted = await self.cache.flush()
        for iid in written:
            inc = self.cache.get(iid)
            if inc is None:
                continue
            if iid not in before:
                m.INCIDENTS_TOTAL.labels(inc["type"], inc["severity"], inc["source"]).inc()
                if inc["source"] == "live":
                    m.TIME_TO_INCIDENT.observe(max(0.0, time.time() - ev.occurred_at.timestamp()))
            for r in inc["rule_ids"]:
                m.RULE_FIRED.labels(r).inc()
        m.SentinelMetrics().refresh_gauges(self.cache.all())
        await self.redis.sadd(PROCESSED, ev.event_id)
        return changed

    async def _fail(self, entry_id: str, fields: dict[str, str], exc: Exception) -> None:
        n = await self.redis.hincrby(FAILS, entry_id, 1)
        if n >= MAX_FAILURES:
            await self.redis.xadd(
                DLQ, {"entry_id": entry_id, "error": str(exc)[:500], "attempts": str(n), **fields}
            )
            await self.redis.xack(STREAM, GROUP, entry_id)
            await self.redis.hdel(FAILS, entry_id)
            m.DEAD_LETTER.inc()
            log.warning("event moved to dlq", extra={"entry_id": entry_id})
        else:
            log.warning("event handling failed (attempt %s): %s", n, exc)

    async def _process_entries(self, entries: list[tuple[str, dict[str, str]]]) -> int:
        changed: list[str] = []
        done = 0
        for entry_id, fields in entries:
            try:
                for iid in await self.handle(entry_id, fields):
                    if iid not in changed:
                        changed.append(iid)
                await self.redis.xack(STREAM, GROUP, entry_id)
                await self.redis.hdel(FAILS, entry_id)
                done += 1
            except Exception as exc:  # noqa: BLE001 - any handler failure is counted toward the DLQ
                await self._fail(entry_id, fields, exc)
        if changed and self.on_incidents:
            await self.on_incidents(changed)
        return done

    async def claim_stale(self, count: int = 50) -> int:
        """Take over entries another (dead) consumer left pending, via XAUTOCLAIM."""
        res = await self.redis.xautoclaim(
            STREAM, GROUP, self.name, min_idle_time=self.min_idle_ms, start_id="0-0", count=count
        )
        entries = [(eid, f) for eid, f in res[1] if f is not None]
        return await self._process_entries(entries)

    async def run_once(self, block_ms: int = 1000, count: int = 50) -> int:
        n = await self.claim_stale(count)
        batches = await self.redis.xreadgroup(
            GROUP, self.name, {STREAM: ">"}, count=count, block=block_ms
        )
        for _stream, entries in batches or []:
            n += await self._process_entries(entries)
        return n
