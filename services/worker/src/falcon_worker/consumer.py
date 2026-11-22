"""``fl:jobs`` consumer: at-least-once, idempotent, single-flight (docs/CONTRACTS.md).

Per verdict document (partial or final), in this order:
1. final only: upsert Postgres ``verdicts`` (+ ``evidence``) and ``SET fl:wmeta:<id>``;
2. ``SET fl:verdict:last:<id> <json> EX 3600``;
3. ``PUBLISH fl:verdict:<id> <json>``;
4. final only, after a successful PUBLISH: ``SET vc:<fingerprint> <verdict_id>`` (never for a
   degraded verdict), ``XADD fl:events MAXLEN ~ 100000 * event <PlatformEvent JSON>``, and the
   completion marker ``fl:wdone:<id>``.

Delivery: an entry is acked only after its final was published (or it was dead-lettered).
On any failure the entry stays pending; ``XAUTOCLAIM`` picks up entries idle for
``RECLAIM_IDLE_MS`` from any consumer, and after ``MAX_DELIVERIES`` deliveries the job goes to
``fl:jobs:dead`` with a degraded final (best effort) and is acked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from collections.abc import Mapping
from typing import Any

from falcon_core.cascade import Cascade, CascadeMetrics, CheckJob, reissue, url_sha256
from falcon_core.cascade.assemble import build_verdict
from falcon_core.cascade.engine import usable_cached
from falcon_core.scoring.arbiter import ArbiterContext, score
from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.signals.url.canonical import canonicalize
from falcon_worker import keys
from falcon_worker.events import verdict_created
from falcon_worker.store import VerdictStore

log = logging.getLogger("falcon.worker")

MAX_DELIVERIES = 3
RECLAIM_IDLE_MS = 60_000


def _dumps(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def _parse_doc(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def consumer_name() -> str:
    """Stable per replica: ``FL_WORKER_ID`` if set, else the hostname. Reclaim does not depend on
    it (XAUTOCLAIM takes idle entries from any consumer), it only keeps XPENDING readable."""
    return os.environ.get("FL_WORKER_ID") or f"worker-{os.environ.get('HOSTNAME') or socket.gethostname()}"


class RedisVerdictCache:
    """Read side of ``vc:<fingerprint>`` -> verdict_id; the doc comes from ``fl:verdict:last:``
    (1 h) or Postgres. Degraded or non-final docs are never served."""

    def __init__(self, redis: Any, store: VerdictStore | None) -> None:
        self.r = redis
        self.store = store

    async def get(self, key: str) -> dict[str, Any] | None:
        vid = await self.r.get(keys.verdict_cache(key))
        if not vid:
            return None
        doc = _parse_doc(await self.r.get(keys.last_key(str(vid))))
        if doc is None and self.store is not None:
            try:
                doc = await self.store.get(str(vid))
            except Exception:  # noqa: BLE001 - store down: treat as a miss
                doc = None
        return doc if usable_cached(doc) else None


class RedisSink:
    """``VerdictSink`` for one job. Every Redis error propagates to the worker (job stays pending)."""

    def __init__(self, worker: Worker, cache_key: str | None = None) -> None:
        self.w = worker
        self.cache_key = cache_key
        self.final_doc: dict[str, Any] | None = None

    async def emit(self, doc: dict[str, Any], meta: Mapping[str, Any]) -> None:
        vid = doc["verdict_id"]
        if doc["final"]:
            meta = await self._meta(meta)
            try:
                await self.w.store.upsert(doc)
            except Exception as exc:  # noqa: BLE001 - Redis still carries the verdict for 1 h
                log.error("verdict store failed: %s", type(exc).__name__, extra={"verdict_id": vid})
            await self.w.r.set(keys.meta_key(vid), _dumps(meta), ex=keys.LAST_TTL_S)
        body = _dumps(doc)
        await self.w.r.set(keys.last_key(vid), body, ex=keys.LAST_TTL_S)
        await self.w.r.publish(keys.channel(vid), body)
        if doc["final"]:
            await self.after_final(doc, meta)

    async def _meta(self, meta: Mapping[str, Any]) -> dict[str, Any]:
        """Re-issued verdicts inherit the original's fingerprints for the event."""
        out = dict(meta)
        src = out.pop("reissued_from", None)
        if src and not out.get("fingerprints"):
            prior = _parse_doc(await self.w.r.get(keys.meta_key(str(src))))
            if prior and prior.get("fingerprints"):
                out["fingerprints"] = prior["fingerprints"]
                out.setdefault("final_registrable_domain", prior.get("final_registrable_domain"))
        return out

    async def after_final(self, doc: dict[str, Any], meta: Mapping[str, Any]) -> None:
        """Steps after a successful final PUBLISH. Idempotent: safe to repeat on a retry."""
        vid = doc["verdict_id"]
        ttl = keys.VC_TTL_S.get(doc["verdict"])
        if self.cache_key and ttl and doc.get("degraded") is False:
            await self.w.r.set(keys.verdict_cache(self.cache_key), vid, ex=ttl)
        event = verdict_created(doc, meta)
        await self.w.r.xadd(keys.EVENTS_STREAM, {"event": _dumps(event)}, maxlen=keys.EVENTS_MAXLEN, approximate=True)
        await self.w.r.set(keys.done_key(vid), "1", ex=keys.LAST_TTL_S)
        self.final_doc = doc


class Worker:
    def __init__(
        self,
        redis: Any,
        cascade: Cascade,
        store: VerdictStore,
        registry: BrandRegistry,
        metrics: CascadeMetrics,
        *,
        consumer: str | None = None,
        follower_wait_s: float = 30.0,
        poll_s: float = 0.1,
        reclaim_idle_ms: int = RECLAIM_IDLE_MS,
        max_deliveries: int = MAX_DELIVERIES,
    ) -> None:
        self.r = redis
        self.cascade = cascade
        self.store = store
        self.registry = registry
        self.metrics = metrics
        self.consumer = consumer or consumer_name()
        self.follower_wait_s = follower_wait_s
        self.poll_s = poll_s
        self.reclaim_idle_ms = reclaim_idle_ms
        self.max_deliveries = max_deliveries

    # --- stream loop -----------------------------------------------------------------------

    async def ensure_group(self) -> None:
        from redis.exceptions import ResponseError

        try:
            await self.r.xgroup_create(keys.JOBS_STREAM, keys.JOBS_GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    @staticmethod
    def _entries(resp: Any) -> list[tuple[str, dict[str, str]]]:
        """Normalise XREADGROUP replies (RESP2 list or RESP3 dict shape)."""
        out: list[tuple[str, dict[str, str]]] = []
        if not resp:
            return out
        streams = resp.items() if isinstance(resp, dict) else resp
        for item in streams:
            _name, entries = item
            out.extend(Worker._norm_entries(entries))
        return out

    @staticmethod
    def _norm_entries(entries: Any) -> list[tuple[str, dict[str, str]]]:
        out: list[tuple[str, dict[str, str]]] = []
        for entry in entries or []:
            entry_id, fields = entry
            if fields is None:  # entry deleted from the stream while pending
                out.append((str(entry_id), {}))
                continue
            if isinstance(fields, list):
                fields = dict(zip(fields[::2], fields[1::2], strict=False))
            out.append((str(entry_id), {str(k): str(v) for k, v in fields.items()}))
        return out

    async def _deliveries(self, entry_id: str) -> int:
        rows = await self.r.xpending_range(keys.JOBS_STREAM, keys.JOBS_GROUP, min=entry_id, max=entry_id, count=1)
        for row in rows or []:
            if str(row.get("message_id")) == entry_id:
                return int(row.get("times_delivered", 1))
        return 1

    async def _dispatch(self, entries: list[tuple[str, dict[str, str]]], counted: bool) -> int:
        async def one(eid: str, f: dict[str, str]) -> None:
            n = await self._deliveries(eid) if counted else 1
            try:
                await self.handle(eid, f, deliveries=n)
            except Exception as exc:  # noqa: BLE001 - leave pending; reclaim retries it
                self.metrics.tool_errors.labels("worker", type(exc).__name__[:40]).inc()
                log.warning("job %s failed (delivery %d), left pending: %s", eid, n, type(exc).__name__)

        if entries:
            await asyncio.gather(*(one(eid, f) for eid, f in entries))
        return len(entries)

    async def read_batch(self, pending: bool, count: int = 8, block_ms: int = 2000) -> int:
        """Read new entries (``pending=False``) or re-read this consumer's own pending list."""
        resp = await self.r.xreadgroup(
            keys.JOBS_GROUP,
            self.consumer,
            {keys.JOBS_STREAM: "0" if pending else ">"},
            count=count,
            block=None if pending else block_ms,
        )
        return await self._dispatch(self._entries(resp), counted=True)

    async def reclaim(self, count: int = 16) -> int:
        """XAUTOCLAIM entries idle for ``reclaim_idle_ms`` (any consumer, e.g. a dead replica)."""
        start = "0-0"
        total = 0
        for _ in range(10):  # bounded sweep
            resp = await self.r.xautoclaim(
                keys.JOBS_STREAM,
                keys.JOBS_GROUP,
                self.consumer,
                min_idle_time=self.reclaim_idle_ms,
                start_id=start,
                count=count,
            )
            start = str(resp[0])
            entries = self._norm_entries(resp[1])
            total += await self._dispatch(entries, counted=True)
            if start in ("0-0", "0"):
                break
        return total

    async def run_forever(self, reclaim_every_s: float = 15.0) -> None:
        next_reclaim = 0.0
        while True:
            try:
                await self.ensure_group()
                await self.read_batch(pending=True)  # own pending entries after a restart
                while True:
                    if time.monotonic() >= next_reclaim:
                        next_reclaim = time.monotonic() + reclaim_every_s
                        await self.reclaim()
                    await self.read_batch(pending=False)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep consuming after Redis hiccups
                log.warning("job loop error, retrying: %s", type(exc).__name__)
                await asyncio.sleep(2)

    # --- one job ---------------------------------------------------------------------------

    async def _ack(self, entry_id: str) -> None:
        await self.r.xack(keys.JOBS_STREAM, keys.JOBS_GROUP, entry_id)

    async def _dead(self, entry_id: str, fields: Mapping[str, str], reason: str) -> None:
        dead = {"entry_id": entry_id, "reason": reason[:200], "verdict_id": fields.get("verdict_id", "")}
        await self.r.xadd(keys.JOBS_DEAD, dead, maxlen=10_000, approximate=True)

    async def handle(self, entry_id: str, fields: Mapping[str, str], deliveries: int = 1) -> dict[str, Any] | None:
        """Process one entry. Acks on success or dead-letter; raises (no ack) on failure."""
        try:
            job = CheckJob.from_fields(fields)
        except ValueError as exc:
            log.error("malformed job %s: %s", entry_id, str(exc)[:200])
            await self._dead(entry_id, fields, f"malformed:{str(exc)[:120]}")
            await self._ack(entry_id)
            return None

        vid = job.verdict_id
        if await self.r.get(keys.done_key(vid)):
            await self._ack(entry_id)  # already completed (redelivery or duplicate entry)
            return None
        claimed = await self.r.set(keys.claim_key(vid), entry_id, nx=True, ex=keys.CLAIM_TTL_S)
        if not claimed and str(await self.r.get(keys.claim_key(vid))) != entry_id:
            log.info("duplicate job entry skipped", extra={"verdict_id": vid})
            await self._ack(entry_id)  # the original entry owns this verdict_id
            return None

        sink = RedisSink(self, cache_key=self._cache_key(job))
        last = _parse_doc(await self.r.get(keys.last_key(vid)))
        last_final = last if last is not None and last.get("final") else None
        if deliveries > self.max_deliveries:
            await self._give_up(job, entry_id, fields, sink, deliveries, last_final)
            return sink.final_doc
        if last_final is not None:
            # The final was stored and SET but a later step failed: finish it, never re-score.
            await self._finish(sink, last_final)
            await self._ack(entry_id)
            return last_final

        if job.input_type != "url":
            await self._unsupported(job, sink)
        else:
            await self._url(job, sink)
        await self._ack(entry_id)
        return sink.final_doc

    def _cache_key(self, job: CheckJob) -> str | None:
        if job.input_type != "url" or job.url is None:
            return None
        if job.fingerprint:
            return job.fingerprint
        c = canonicalize(job.url)
        return url_sha256(c) if c.ok else None

    def _degraded_doc(self, job: CheckJob, reason: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        result = score([], None, ArbiterContext(input_type=job.input_type, extra_degraded_reasons=(reason,)))
        return build_verdict(
            result,
            verdict_id=job.verdict_id,
            input_type=job.input_type,
            tier="T0",
            final=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            registry=self.registry,
            input_fingerprint=job.fingerprint,
            source=job.source,
        )

    async def _finish(self, sink: RedisSink, last_final: dict[str, Any]) -> None:
        vid = last_final["verdict_id"]
        meta = _parse_doc(await self.r.get(keys.meta_key(vid))) or {}
        await self.r.publish(keys.channel(vid), _dumps(last_final))  # same doc: still one final
        await sink.after_final(last_final, meta)

    async def _give_up(
        self,
        job: CheckJob,
        entry_id: str,
        fields: Mapping[str, str],
        sink: RedisSink,
        deliveries: int,
        last_final: dict[str, Any] | None,
    ) -> None:
        await self._dead(entry_id, fields, f"max_deliveries:{deliveries}")
        try:  # best effort: tell the waiting client instead of letting SSE time out
            if last_final is not None:
                await self._finish(sink, last_final)  # never replace an existing final
            else:
                doc = self._degraded_doc(job, "job_failed_repeatedly")
                await sink.emit(doc, {})
                self.metrics.record_final(job.input_type, doc["verdict"], "T0", "none", job.source)
                self.metrics.degraded.inc()
        except Exception as exc:  # noqa: BLE001 - dead-lettered either way
            log.error("degraded final after max deliveries failed: %s", type(exc).__name__)
        await self._ack(entry_id)

    async def _unsupported(self, job: CheckJob, sink: RedisSink) -> None:
        """message/email/image pipelines are not built yet: answer degraded, never silent."""
        doc = self._degraded_doc(job, f"input_type_not_supported_yet:{job.input_type}")
        await sink.emit(doc, {})
        await self.r.delete(keys.blob_key(job.verdict_id))
        self.metrics.record_final(job.input_type, doc["verdict"], "T0", "none", job.source)
        self.metrics.degraded.inc()

    async def _url(self, job: CheckJob, sink: RedisSink) -> None:
        url = job.url or ""
        key = sink.cache_key
        if key is None:
            await self.cascade.run_url(job.verdict_id, url, sink, source=job.source)
            return
        lock = keys.worker_single_flight(key)
        if await self.r.set(lock, job.verdict_id, nx=True, ex=keys.SINGLE_FLIGHT_TTL_S):
            try:
                await self.cascade.run_url(job.verdict_id, url, sink, source=job.source, cache_key=key)
            finally:
                if str(await self.r.get(lock)) == job.verdict_id:
                    await self.r.delete(lock)
            return
        leader = await self.r.get(lock)
        doc = await self._wait_for_leader(str(leader) if leader else None, lock)
        if doc is None:  # leader vanished, failed or too slow: run it ourselves
            await self.cascade.run_url(job.verdict_id, url, sink, source=job.source, cache_key=key)
            return
        self.metrics.cache_hits.labels("single_flight").inc()
        out = reissue(
            doc,
            verdict_id=job.verdict_id,
            source=job.source,
            latency_ms=int((time.time() - job.submitted_at.timestamp()) * 1000),
            note=f"Shared result of an identical check in flight ({str(leader)[:32]})",
            input_fingerprint=doc.get("input_fingerprint"),
        )
        c = canonicalize(url)
        await sink.emit(out, {"registrable_domain": c.registrable or c.host, "reissued_from": str(leader)})
        self.metrics.record_final("url", out["verdict"], out["tier_reached"], out["model_route"], job.source)

    async def _wait_for_leader(self, leader: str | None, lock: str) -> dict[str, Any] | None:
        if not leader:
            return None
        deadline = time.monotonic() + self.follower_wait_s
        while time.monotonic() < deadline:
            doc = _parse_doc(await self.r.get(keys.last_key(leader)))
            if doc is not None and doc.get("final"):
                return doc
            if str(await self.r.get(lock)) != leader:
                # Lock released or taken over without a final: the leader failed.
                doc = _parse_doc(await self.r.get(keys.last_key(leader)))
                return doc if doc is not None and doc.get("final") else None
            await asyncio.sleep(self.poll_s)
        return None
