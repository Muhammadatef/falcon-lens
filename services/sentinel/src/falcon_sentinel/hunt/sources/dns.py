"""DNS existence check over DoH JSON (Google Public DNS JSON API, https://dns.google/resolve).

``NS`` on the registrable domain first: wildcard and parking DNS make ``A`` alone meaningless. NXDOMAIN (Status 3)
or no NS delegation -> unregistered, and no ``A`` / ``MX`` query follows. Only registered names get ``A`` and
``MX``. Token bucket at ``qps`` (fake clock in tests), negative cache 6 h, positive 1 h, never longer than the
response's Cache-Control max-age (Google APIs ToS: no cached copies past the cache header).
The query carries the domain name only; ``edns_client_subnet=0.0.0.0/0`` keeps our address out of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..clock import Clock
from ..http import HuntHTTP
from .base import Paused

NEG_TTL_S = 6 * 3600
POS_TTL_S = 3600
TYPE_NS, TYPE_A, TYPE_MX = 2, 1, 15
_MAX_AGE = re.compile(r"max-age=(\d+)")


@dataclass(frozen=True)
class DnsResult:
    registered: bool | None  # None = could not tell (SERVFAIL, timeout); retried on a later cycle
    has_a: bool = False
    has_mx: bool = False


class TokenBucket:
    def __init__(self, rate: float, clock: Clock, capacity: float | None = None) -> None:
        self.rate, self.clock = rate, clock
        self.capacity = capacity if capacity is not None else 1.0  # no burst: never more than `rate` per second
        self.tokens = self.capacity
        self.last = clock.monotonic()

    async def acquire(self) -> None:
        while True:
            now = self.clock.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1 - 1e-9:  # tolerance: float refill must never spin on 0.9999999
                self.tokens = max(0.0, self.tokens - 1)
                return
            await self.clock.sleep((1 - self.tokens) / self.rate)


class DohResolver:
    def __init__(self, http: HuntHTTP, url: str, qps: int, clock: Clock) -> None:
        self.http, self.url, self.clock = http, url, clock
        self.bucket = TokenBucket(float(qps), clock)
        self._cache: dict[str, tuple[float, DnsResult]] = {}
        self.queries = 0

    async def _query(self, name: str, rtype: int) -> tuple[int | None, set[int], int | None]:
        """(dns Status, answer types, cache max-age). Status None = transport/HTTP failure."""
        await self.bucket.acquire()
        self.queries += 1
        try:
            resp = await self.http.get_json(
                self.url, params={"name": name, "type": str(rtype), "edns_client_subnet": "0.0.0.0/0"}
            )
        except Paused:
            raise
        except Exception:  # noqa: BLE001 - any failure means "could not tell", never "unregistered"
            return None, set(), None
        m = _MAX_AGE.search(resp.headers.get("cache-control", ""))
        max_age = int(m.group(1)) if m else None
        if resp.status != 200 or not isinstance(resp.data, dict) or not isinstance(resp.data.get("Status"), int):
            return None, set(), max_age
        types = {
            a.get("type")
            for a in resp.data.get("Answer") or []
            if isinstance(a, dict) and isinstance(a.get("type"), int)
        }
        return int(resp.data["Status"]), {t for t in types if isinstance(t, int)}, max_age

    def _cache_put(self, name: str, res: DnsResult, ttl: int, max_age: int | None) -> None:
        if max_age is not None:
            ttl = min(ttl, max_age)
        if ttl > 0 and res.registered is not None:
            self._cache[name] = (self.clock.monotonic() + ttl, res)

    async def check(self, name: str) -> DnsResult:
        hit = self._cache.get(name)
        if hit and hit[0] > self.clock.monotonic():
            return hit[1]
        status, types, max_age = await self._query(name, TYPE_NS)
        if status == 3 or (status == 0 and TYPE_NS not in types):
            res = DnsResult(registered=False)
            self._cache_put(name, res, NEG_TTL_S, max_age)
            return res
        if status != 0:
            return DnsResult(registered=None)
        _sa, a_types, _ = await self._query(name, TYPE_A)
        _sm, mx_types, _ = await self._query(name, TYPE_MX)
        res = DnsResult(registered=True, has_a=TYPE_A in a_types, has_mx=TYPE_MX in mx_types)
        self._cache_put(name, res, POS_TTL_S, max_age)
        return res
