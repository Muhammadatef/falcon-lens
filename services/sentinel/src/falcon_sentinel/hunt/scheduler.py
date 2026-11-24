"""One hunt cycle (HUNTER.md section 3): kill switch and pause -> poll sources -> dedupe -> DNS / CT -> prescore ->
submit the top candidates within quota -> record.

* Started only when FL_HUNT_ENABLED=true (main.py); otherwise no task exists and no request leaves.
* Runtime pause: Redis key ``fl:hunt:paused``, checked before every outbound request (HuntHTTP guard) and before
  every submission. A pause mid-cycle ends the cycle with outcome ``paused``.
* A Postgres advisory lock (store.try_lock) keeps two replicas from hunting at once.
* State lives in the store: a candidate already submitted is never submitted again, after a restart included.
* Submission needs evidence that the name can be visited (DNS ``A`` record, or a fixture host), a prescore at or
  above FL_HUNT_PRESCORE_MIN, quota left in the hour and the day, and a job queue lag of at most 20.
  Prescore is a queue priority, never a risk score: the arbiter decides.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from sentinel_core.hunt.candidates import Candidate, dedupe, transition, with_reasons
from sentinel_core.hunt.config import HuntConfig
from sentinel_core.hunt.prescore import prescore
from sentinel_core.ids import make_ulid

from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.telemetry import metrics as tm

from .clock import Clock
from .http import HuntHTTP
from .settings import HuntSettings
from .sources.base import HuntSource, Paused, Sighting, SourceDisabled
from .sources.ct import Backoff, CrtSh, CtSearchSource, RateWait
from .sources.dns import DohResolver
from .sources.fixture import FixtureSource
from .sources.keyed import KEYED
from .sources.permutation import PermutationSource
from .store import HuntStore
from .submit import Submitter

log = logging.getLogger("falcon.sentinel.hunt")
PAUSE_KEY = "fl:hunt:paused"
SUBMITTABLE = ("new", "skipped_quota", "queued")


def make_guard(redis: Any) -> Callable[[], Awaitable[None]]:
    async def guard() -> None:
        if redis is not None and await redis.get(PAUSE_KEY):
            raise Paused("fl:hunt:paused is set")

    return guard


def doh_host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).hostname or ""


def allow_hosts(settings: HuntSettings) -> tuple[str, ...]:
    """The two hosts hunt-egress lets through: crt.sh and the DoH resolver."""
    return ("crt.sh", doh_host(settings.doh_url))


class HuntScheduler:
    def __init__(
        self,
        *,
        settings: HuntSettings,
        config: HuntConfig,
        registry: BrandRegistry,
        store: HuntStore,
        redis: Any,
        clock: Clock,
        http: HuntHTTP | None,
        submitter: Submitter | None,
        jobs_lag: Callable[[], Awaitable[int]] | None = None,
        brands: list[str] | None = None,
    ) -> None:
        self.s, self.cfg, self.registry = settings, config, registry
        self.store, self.redis, self.clock = store, redis, clock
        self.http, self.submitter, self.jobs_lag = http, submitter, jobs_lag
        self.brands = brands
        self.guard = make_guard(redis)
        active = settings.active_sources()
        self.sources: list[HuntSource] = []
        self.dns: DohResolver | None = None
        self.crt: CrtSh | None = None
        if http is not None and any(s in active for s in ("ct_lookup", "ct_search")):
            self.crt = CrtSh(http, clock, settings.ct_min_interval_s, config.prescore.cert_fresh_days)
        if "fixture" in active:
            self.sources.append(FixtureSource(registry, clock, settings.fixture_path, config.prescore.cert_fresh_days))
        if "permutation" in active and http is not None:
            self.sources.append(PermutationSource(registry, config.permutation, clock, settings.dns_max_per_cycle))
            self.dns = DohResolver(http, settings.doh_url, settings.dns_qps, clock)
        if "ct_search" in active and self.crt is not None:
            self.sources.append(CtSearchSource(self.crt, registry, enabled=True))
        for cls in KEYED:
            if cls.id in active:
                self.sources.append(cls())
        self.ct_lookup = "ct_lookup" in active and self.crt is not None
        self.label = "live" if any(s in active for s in ("permutation", "ct_lookup", "ct_search")) else "fixture"

    # ------------------------------------------------------------------ helpers

    async def paused(self) -> bool:
        return bool(self.redis is not None and await self.redis.get(PAUSE_KEY))

    def _category(self, brand_id: str) -> str | None:
        return next((b.category for b in self.registry.brands if b.brand_id == brand_id), None)

    def _prescore(self, c: Candidate) -> Candidate:
        p = prescore(
            self.cfg.prescore,
            discovery=c.discovery,
            permutation_kind=c.permutation_kind,
            reasons=c.reasons,
            category=self._category(c.brand_id),
        )
        return replace(c, prescore=p)

    @staticmethod
    def visitable(c: Candidate) -> bool:
        return c.provenance.get("source") == "fixture" or "resolves_a" in c.reasons

    def _candidate(self, s: Sighting) -> Candidate:
        return Candidate(
            domain=s.domain,
            brand_id=s.brand_id,
            discovery=s.discovery,
            permutation_kind=s.permutation_kind,
            first_seen=s.retrieved_at,
            provenance={
                "source_id": s.source_id,
                "terms_url": s.terms_url,
                "retrieved_at": s.retrieved_at,
                "source": s.source,
            },
            reasons=tuple(sorted(set(s.reasons))),
            upstream_seen=s.upstream_seen,
            scheme=s.scheme,
        )

    def _windows(self) -> tuple[datetime, datetime]:
        now = self.clock.now()
        hour = now.replace(minute=0, second=0, microsecond=0)
        day = hour.replace(hour=0)
        return hour, day

    async def _quota_left(self) -> tuple[int, int]:
        hour, day = self._windows()
        h = self.s.submit_max_per_hour - await self.store.quota_used("submit_hour", hour)
        d = self.s.submit_max_per_day - await self.store.quota_used("submit_day", day)
        tm.HUNT_QUOTA_REMAINING.labels("hour", self.label).set(max(0, h))
        tm.HUNT_QUOTA_REMAINING.labels("day", self.label).set(max(0, d))
        return max(0, h), max(0, d)

    # ------------------------------------------------------------------ cycle

    async def run_cycle(self) -> dict[str, Any]:
        now = self.clock.now()
        stats: dict[str, Any] = {"sightings": 0, "new": 0, "dns": 0, "unregistered": 0, "ct": 0, "submitted": 0}
        if not await self.store.try_lock():
            tm.HUNT_CYCLES.labels("locked", self.label).inc()
            return {"outcome": "locked", "stats": stats}
        cycle = {"cycle_id": "hcy_" + make_ulid(now, f"hunt-cycle|{now.isoformat()}"), "started_at": now}
        try:
            outcome = await self._cycle(stats)
        except Paused:
            outcome = "paused"
        except Exception:  # noqa: BLE001 - a failed cycle must never stop the Sentinel; the next one retries
            log.exception("hunt cycle failed")
            outcome = "error"
        finally:
            await self.store.unlock()
        cycle.update(finished_at=self.clock.now(), outcome=outcome, stats=stats)
        await self.store.cycle_put(cycle)
        tm.HUNT_CYCLES.labels(outcome, self.label).inc()
        log.info("hunt cycle %s", outcome, extra={"hunt_stats": stats})
        return {"outcome": outcome, "stats": stats}

    async def _poll(self, stats: dict[str, Any]) -> list[Sighting]:
        out: list[Sighting] = []
        for src in self.sources:
            if await self.paused():
                raise Paused("paused")
            state = await self.store.source_state(src.id)
            if hasattr(src, "cursor") and isinstance(state.get("cursor"), dict) and state["cursor"]:
                src.cursor = dict(state["cursor"])
            try:
                got = await src.poll(self.brands, None)
            except SourceDisabled:
                continue
            except Paused:
                raise
            except Exception as exc:  # noqa: BLE001 - one broken source must not stop the others
                log.warning("hunt source %s failed: %s", src.id, type(exc).__name__)
                await self.store.put_source_state(
                    src.id, {**state, "failures": int(state.get("failures") or 0) + 1, "last_error": type(exc).__name__}
                )
                continue
            now = self.clock.now()
            new_state = {**state, "failures": 0, "last_success": now, "last_error": None}
            if hasattr(src, "cursor"):
                new_state["cursor"] = src.cursor
            await self.store.put_source_state(src.id, new_state)
            tm.HUNT_LAST_SUCCESS.labels(src.id, "fixture" if src.id == "fixture" else "live").set(now.timestamp())
            out += got
        stats["sightings"] = len(out)
        return out

    async def _fresh(self, sightings: list[Sighting], stats: dict[str, Any]) -> list[Candidate]:
        recheck = timedelta(hours=self.s.recheck_hours)
        now = self.clock.now()
        fresh: list[Candidate] = []
        for c in dedupe(self._candidate(s) for s in sightings):
            old = await self.store.get_by_domain(c.domain)
            if old is None:
                fresh.append(c)
                stats["new"] += 1
                tm.HUNT_CANDIDATES.labels(c.discovery, str(c.provenance["source"])).inc()
            elif old.status in ("unregistered", "error") and (
                old.checked_at is None or now - old.checked_at >= recheck
            ):
                fresh.append(with_reasons(transition(old, "new"), *c.reasons))
        return fresh

    async def _check(self, c: Candidate, stats: dict[str, Any]) -> Candidate:
        now = self.clock.now()
        if c.provenance.get("source") == "fixture":
            return replace(c, checked_at=now)  # internal fixture host: never looked up on public DNS
        if self.dns is None or stats["dns"] >= self.s.dns_max_per_cycle:
            return c
        stats["dns"] += 1
        res = await self.dns.check(c.domain)
        tm.HUNT_SOURCE_REQUESTS.labels("dns", "ok" if res.registered is not None else "error", "live").inc()
        if res.registered is False:
            stats["unregistered"] += 1
            return transition(c, "unregistered", checked_at=now)
        if res.registered is None:
            return transition(c, "error", checked_at=now)
        reasons = [r for r, ok in (("resolves_a", res.has_a), ("has_mx", res.has_mx)) if ok]
        return replace(with_reasons(c, *reasons), checked_at=now)

    async def _ct(self, cands: list[Candidate], stats: dict[str, Any]) -> list[Candidate]:
        if not self.ct_lookup or self.crt is None:
            return cands
        order = sorted(
            (
                i
                for i, c in enumerate(cands)
                if c.status == "new" and self.visitable(c) and c.provenance.get("source") != "fixture"
            ),
            key=lambda i: (-cands[i].prescore, cands[i].first_seen, cands[i].candidate_id),
        )
        for i in order:
            if self.crt.breaker.is_open(self.clock.monotonic()):
                tm.HUNT_SOURCE_REQUESTS.labels(
                    "ct_lookup", "backoff", "live"
                ).inc()  # visible while the breaker is open
                break
            if not self.crt.ready():
                break
            c = cands[i]
            try:
                s = await self.crt.lookup(c.domain)
            except RateWait:
                break
            except Backoff:
                tm.HUNT_SOURCE_REQUESTS.labels("ct_lookup", "backoff", "live").inc()
                break
            stats["ct"] += 1
            tm.HUNT_SOURCE_REQUESTS.labels("ct_lookup", "ok", "live").inc()
            if s.certs_seen == 0:
                continue  # "no data", never "no threat": the candidate is left as it was
            ups = (
                s.first_not_before
                if c.upstream_seen is None
                else min(c.upstream_seen, s.first_not_before or c.upstream_seen)
            )
            c = replace(c, upstream_seen=ups)
            if s.fresh:
                c = with_reasons(c, "cert_fresh")
            cands[i] = self._prescore(c)
        return cands

    async def _submit(self, stats: dict[str, Any]) -> None:
        if self.submitter is None:
            return
        if self.jobs_lag is not None and await self.jobs_lag() > self.s.jobs_lag_max:
            stats["held_for_lag"] = True  # a user check never waits behind the hunt
            return
        queue = [
            c
            for c in await self.store.list(SUBMITTABLE, limit=1000)
            if c.prescore >= self.s.prescore_min
            and self.visitable(c)
            and (not self.brands or c.brand_id in self.brands)
        ]
        hour, day = self._windows()
        for c in queue:
            await self.guard()
            h_left, d_left = await self._quota_left()
            if h_left <= 0 or d_left <= 0:
                if c.status != "skipped_quota":
                    await self.store.upsert(transition(c, "skipped_quota"))
                continue
            await self.store.quota_take("submit_hour", hour, self.s.submit_max_per_hour)
            await self.store.quota_take("submit_day", day, self.s.submit_max_per_day)
            if c.status != "queued":
                c = transition(c, "queued")
                await self.store.upsert(c)
            r = await self.submitter.submit(c)
            src = str(c.provenance.get("source"))
            if r.outcome == "submitted":
                c = transition(c, "submitted", verdict_id=r.verdict_id)
                stats["submitted"] += 1
                tm.HUNT_SUBMITTED.labels(src).inc()
            elif r.outcome == "already_known":
                c = transition(c, "already_known")
                tm.HUNT_ALREADY_KNOWN.labels(src).inc()
            else:
                c = transition(c, "error", checked_at=self.clock.now())
            await self.store.upsert(c)
        await self._quota_left()

    async def _cycle(self, stats: dict[str, Any]) -> str:
        if await self.paused():
            raise Paused("paused")
        sightings = await self._poll(stats)
        fresh = await self._fresh(sightings, stats)
        checked: list[Candidate] = []
        for c in fresh:
            c = await self._check(c, stats)
            checked.append(self._prescore(c))
        checked = await self._ct(checked, stats)
        for c in checked:
            await self.store.upsert(c)
        await self._submit(stats)
        return "ok"
