"""domain.cert_age_days / domain.cert_issuer / domain.ct_siblings from the crt.sh JSON API.

One crt.sh query per domain (cached 6 h, single-flight) feeds three evidence items. crt.sh is a free best-effort
service: calls are limited to 2 concurrent, and after a 429/5xx/timeout a circuit breaker skips the service for
60 s (the signal then reports ``crt_backoff`` instead of hammering it). A live TLS handshake is deliberately not
a fallback: it would be egress outside the guarded path.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, async_signal
from falcon_core.signals.cache import get_cache, get_clock, single_flight
from falcon_core.signals.domain.common import (
    _ICANN,
    FetchError,
    error_evidence,
    fetch_json,
    target_domain,
)

CRT_TTL_S = 6 * 3600
CRT_NEG_TTL_S = 3600
HTTP_BUDGET_S = 2.2
BACKOFF_S = 60.0
MAX_SIBLINGS = 25

SPEC = SignalSpec(
    name="domain.cert_age_days",
    family="domain",
    tier="T1",
    input_types=("url",),
    timeout_ms=2500,
    network="egress_proxy",
    emits=("domain.cert_age_days", "domain.cert_issuer", "domain.ct_siblings"),
    cache_ttl_s=CRT_TTL_S,
    feature_names=("cert_age_days",),
)

_sem: asyncio.Semaphore | None = None
_blocked_until = 0.0


def reset_backoff() -> None:
    """Test hook."""
    global _blocked_until
    _blocked_until = 0.0


def _semaphore() -> asyncio.Semaphore:
    global _sem
    loop_sem = _sem
    if loop_sem is None or getattr(loop_sem, "_fl_loop", None) is not asyncio.get_running_loop():
        loop_sem = asyncio.Semaphore(2)
        loop_sem._fl_loop = asyncio.get_running_loop()  # type: ignore[attr-defined]
        _sem = loop_sem
    return loop_sem


def _parse_ts(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def issuer_org(dn: str) -> str:
    """'C=US, O=Let's Encrypt, CN=R11' -> "Let's Encrypt" (falls back to CN, then the raw DN)."""
    parts: dict[str, str] = {}
    for piece in dn.split(","):
        k, _, v = piece.strip().partition("=")
        if v and k.upper() not in parts:
            parts[k.upper()] = v.strip()
    return (parts.get("O") or parts.get("CN") or dn)[:120]


def summarize(rows: Any, domain: str) -> dict[str, Any]:
    """crt.sh rows -> compact cacheable summary."""
    if not isinstance(rows, list):
        raise FetchError("bad_json")
    dated: list[tuple[datetime, dict[str, Any]]] = []
    siblings: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = _parse_ts(r.get("not_before")) or _parse_ts(r.get("entry_timestamp"))
        if d is not None:
            dated.append((d, r))
        for san in str(r.get("name_value", "")).splitlines():
            san = san.strip().lower().removeprefix("*.")
            if not san or "@" in san:
                continue
            reg = _ICANN(san).top_domain_under_public_suffix
            if reg and reg.lower() != domain:
                siblings.add(reg.lower())
    if not dated:
        return {"certs_seen": 0}
    dated.sort(key=lambda t: t[0])
    first, latest = dated[0], dated[-1]
    latest_dn = str(latest[1].get("issuer_name", ""))
    return {
        "certs_seen": len(dated),
        "first_not_before": first[0].isoformat(),
        "latest_not_before": latest[0].isoformat(),
        "issuer_dn": latest_dn[:200],
        "issuer": issuer_org(latest_dn) if latest_dn else None,
        "siblings_total": len(siblings),
        "siblings": sorted(siblings)[:MAX_SIBLINGS],
    }


async def crt_lookup(ctx: SignalContext, domain: str) -> dict[str, Any]:
    cache = get_cache(ctx)
    key = f"crt:{domain}"
    hit = await cache.get(key)
    if isinstance(hit, dict):
        return hit

    async def work() -> dict[str, Any]:
        global _blocked_until
        if time.monotonic() < _blocked_until:
            raise FetchError("backoff")
        url = f"https://crt.sh/?q={quote(domain, safe='.-')}&output=json"
        try:
            async with _semaphore():
                rows = await fetch_json(ctx.http, url, timeout_s=HTTP_BUDGET_S)
        except FetchError as exc:
            if exc.code in ("rate_limited", "timeout", "connect_error") or exc.code.startswith(
                "http_5"
            ):
                _blocked_until = time.monotonic() + BACKOFF_S
            raise
        res = summarize(rows, domain)
        await cache.set(key, res, CRT_TTL_S if res["certs_seen"] else CRT_NEG_TTL_S)
        return res

    return await single_flight(key, work)


@async_signal(SPEC)
async def run(ctx: SignalContext) -> list[Evidence]:
    t = target_domain(ctx.url)
    if t is None:
        return []
    try:
        info = await crt_lookup(ctx, t.domain)
    except FetchError as exc:
        return [error_evidence(SPEC, f"crt_{exc.code}", "crt")]
    if not info.get("certs_seen"):
        return [
            Evidence(
                signal="domain.cert_age_days",
                family="domain",
                observed={"cert_age_days": None, "certs_seen": 0},
                display={
                    "en": "No certificates found in public CT logs",
                    "ar": "لا توجد شهادات لهذا النطاق في سجلات الشفافية العامة",
                },
                polarity="neutral",
                source="crt",
                tier="T1",
                confidence=0.5,
            )
        ]
    first = _parse_ts(info["first_not_before"])
    assert first is not None  # noqa: S101 - written by summarize()
    now = datetime.fromtimestamp(get_clock(ctx)(), tz=UTC)
    age = max(0, (now - first).days)
    out = [
        Evidence(
            signal="domain.cert_age_days",
            family="domain",
            observed={
                "cert_age_days": age,
                "first_seen": info["first_not_before"],
                "certs_seen": info["certs_seen"],
            },
            display={
                "en": f"First certificate issued {age} days ago",
                "ar": f"صدرت أول شهادة قبل {age} يومًا",
            },
            polarity="risk" if age < 7 else "neutral",
            source="crt",
            tier="T1",
        )
    ]
    if info.get("issuer"):
        out.append(
            Evidence(
                signal="domain.cert_issuer",
                family="domain",
                observed={"issuer": info["issuer"], "issuer_dn": info.get("issuer_dn")},
                display={
                    "en": f"Certificate issuer: {info['issuer']}"[:200],
                    "ar": f"جهة إصدار الشهادة: {info['issuer']}"[:200],
                },
                polarity="neutral",
                source="crt",
                tier="T1",
            )
        )
    sib = info.get("siblings", [])
    out.append(
        Evidence(
            signal="domain.ct_siblings",
            family="domain",
            observed={"count": info.get("siblings_total", 0), "domains": sib},
            display={
                "en": f"{info.get('siblings_total', 0)} other domains share its certificates",
                "ar": f"{info.get('siblings_total', 0)} نطاقات أخرى تشترك في شهاداته",
            },
            polarity="neutral",
            source="crt",
            tier="T1",
        )
    )
    return out
