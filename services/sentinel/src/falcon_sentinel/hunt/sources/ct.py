"""crt.sh Certificate Transparency source (HUNTER.md sections 3 and 9).

Two modes, one rate limiter: at most one call per ``min_interval_s`` (>= 120 s), 6 h cache, circuit breaker with
exponential backoff on 429 / 5xx / timeout, 30 s timeout, 4 MB response cap (hunt/http.py).

* ``lookup`` (``ct_lookup``): ``?q=<candidate>&output=json`` for one registered candidate. Yields the earliest
  certificate ``not_before`` and the reason ``cert_fresh`` when it is under ``fresh_days`` old. Parsing reuses
  ``falcon_core.signals.domain.crt.summarize``.
* ``search`` (``ct_search``, experimental, off by default): ``?q=%<token>%&output=json``, one brand token per call,
  round-robin. Every probe so far returned an empty list.

An empty list means "no data", never "no threat": it never changes a candidate's status. crt.sh publishes no
terms of use (checked 2026-11-24), so neither mode is in the default FL_HUNT_SOURCES.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sentinel_core.hunt.candidates import registrable
from sentinel_core.hunt.tokens import brand_tokens

from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.signals.domain.crt import summarize

from ..clock import Clock
from ..http import HuntHTTP
from .base import Paused, Sighting, SourceDisabled, SourceKind, SourceStatus

CRT_URL = "https://crt.sh/"
TERMS_URL = "https://crt.sh/"
CACHE_TTL_S = 6 * 3600
BACKOFF_BASE_S = 300.0
BACKOFF_MAX_S = 6 * 3600.0


class RateWait(Exception):
    """The minimum gap since the last crt.sh call has not passed yet (the call was not made)."""


class Backoff(Exception):
    """The breaker is open after 429 / 5xx / timeout (the call was not made)."""


@dataclass
class Breaker:
    failures: int = 0
    open_until: float = 0.0

    def is_open(self, now: float) -> bool:
        return now < self.open_until

    def fail(self, now: float) -> float:
        self.failures += 1
        wait = float(min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2.0 ** (self.failures - 1)))
        self.open_until = now + wait
        return wait

    def ok(self) -> None:
        self.failures, self.open_until = 0, 0.0


@dataclass(frozen=True)
class CtSummary:
    certs_seen: int
    first_not_before: datetime | None
    fresh: bool


class CrtSh:
    """Shared limiter + breaker + cache for both modes."""

    def __init__(self, http: HuntHTTP, clock: Clock, min_interval_s: int, fresh_days: int = 7) -> None:
        self.http, self.clock = http, clock
        self.min_interval_s = max(120, min_interval_s)
        self.fresh_days = fresh_days
        self.breaker = Breaker()
        self.last_call: float | None = None
        self.call_times: list[float] = []
        self._cache: dict[str, tuple[float, Any]] = {}

    def ready(self) -> bool:
        now = self.clock.monotonic()
        if self.breaker.is_open(now):
            return False
        return self.last_call is None or now - self.last_call >= self.min_interval_s

    async def _get(self, q: str) -> list[dict[str, Any]]:
        now = self.clock.monotonic()
        hit = self._cache.get(q)
        if hit and hit[0] > now:
            return list(hit[1])
        if self.breaker.is_open(now):
            raise Backoff(str(self.breaker.open_until - now))
        if self.last_call is not None and now - self.last_call < self.min_interval_s:
            raise RateWait(str(self.min_interval_s - (now - self.last_call)))
        self.last_call = now
        self.call_times.append(now)
        try:
            resp = await self.http.get_json(CRT_URL, params={"q": q, "output": "json"})
        except Paused:
            raise
        except Exception as exc:  # noqa: BLE001 - timeout / transport: open the breaker
            self.breaker.fail(self.clock.monotonic())
            raise Backoff(type(exc).__name__) from exc
        if resp.status == 429 or resp.status >= 500:
            self.breaker.fail(self.clock.monotonic())
            raise Backoff(f"http_{resp.status}")
        self.breaker.ok()
        rows = (
            [r for r in resp.data if isinstance(r, dict)] if resp.status == 200 and isinstance(resp.data, list) else []
        )
        self._cache[q] = (self.clock.monotonic() + CACHE_TTL_S, rows)
        return rows

    async def lookup(self, domain: str) -> CtSummary:
        """Raises RateWait / Backoff when no call was made. certs_seen == 0 = no data (not "no threat")."""
        rows = await self._get(domain)
        try:
            s = summarize(rows, domain)
        except Exception:  # noqa: BLE001 - bad shape is "no data"
            return CtSummary(0, None, False)
        if not s.get("certs_seen"):
            return CtSummary(0, None, False)
        first = datetime.fromisoformat(str(s["first_not_before"]))
        fresh = self.clock.now() - first < timedelta(days=self.fresh_days)
        return CtSummary(int(s["certs_seen"]), first, fresh)

    async def search(self, token: str) -> list[dict[str, Any]]:
        return await self._get(f"%{token}%")


class CtSearchSource:
    """Experimental substring discovery. Off by default; only after a probe returned rows (DECISIONS.md)."""

    id = "ct_search"
    kind: SourceKind = "ct"
    requires_key = False
    terms_url: str | None = TERMS_URL

    def __init__(self, crt: CrtSh, registry: BrandRegistry, enabled: bool) -> None:
        self.crt, self.registry, self.enabled = crt, registry, enabled
        self.cursor: dict[str, Any] = {"token": 0}

    def status(self) -> SourceStatus:
        return "live" if self.enabled else "disabled"

    async def poll(self, brands: list[str] | None, since: datetime | None) -> list[Sighting]:
        if not self.enabled:
            raise SourceDisabled("ct_search is experimental and off")
        toks = [(b, t) for b, t in brand_tokens(self.registry) if not brands or b in brands]
        if not toks or not self.crt.ready():
            return []
        i = int(self.cursor.get("token", 0)) % len(toks)
        self.cursor = {"token": (i + 1) % len(toks)}
        brand_id, token = toks[i]
        try:
            rows = await self.crt.search(token)
        except (RateWait, Backoff):
            return []
        now = self.crt.clock.now()
        out: dict[str, Sighting] = {}
        for r in rows:
            for name in str(r.get("name_value", "")).splitlines():
                host = name.strip().lower().removeprefix("*.")
                reg = registrable(host)
                if not reg or self.registry.is_official(reg) or token.replace("-", "") not in reg.replace("-", ""):
                    continue
                if reg not in out:
                    out[reg] = Sighting(
                        domain=reg,
                        brand_id=brand_id,
                        discovery="ct",
                        source_id=self.id,
                        terms_url=TERMS_URL,
                        retrieved_at=now,
                        source="live",
                        reasons=("brand_token_in_cert",),
                    )
        return list(out.values())
