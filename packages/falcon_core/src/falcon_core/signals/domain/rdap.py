"""domain.age_days: registration date + registrar from RDAP (RFC 9083), IANA bootstrap (RFC 9224).

whoisit 4.1.0 (the version pinned in VERIFIED_VERSIONS.md) does its own HTTP via requests/httpx, which would
bypass ``ctx.http`` and the SSRF guard. So the network hop is ours and only the response layout is shared:
whoisit's ``ParseDomain`` reads ``events[eventAction=registration|expiration|last changed]`` and
``entities[roles=registrar].vcardArray``; this module reads the same fields (verified against the 4.1.0 source).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, async_signal
from falcon_core.signals.cache import get_cache, get_clock, single_flight
from falcon_core.signals.domain.common import (
    FetchError,
    error_evidence,
    fetch_json,
    target_domain,
)

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
RDAP_TTL_S = 24 * 3600
RDAP_NEG_TTL_S = 3600
HTTP_BUDGET_S = 2.2  # inside the 2.5 s signal budget

SPEC = SignalSpec(
    name="domain.age_days",
    family="domain",
    tier="T1",
    input_types=("url",),
    timeout_ms=2500,
    network="egress_proxy",
    emits=("domain.age_days",),
    cache_ttl_s=RDAP_TTL_S,
    feature_names=("domain_age_days",),
)


def parse_bootstrap(doc: Any) -> dict[str, str]:
    """IANA dns.json -> {tld: https base url (with trailing slash)}."""
    out: dict[str, str] = {}
    for svc in doc.get("services", []) if isinstance(doc, dict) else []:
        try:
            tlds, urls = svc
        except (TypeError, ValueError):
            continue
        https = [u for u in urls if isinstance(u, str) and u.startswith("https://")]
        if not https:
            continue
        base = https[0] if https[0].endswith("/") else https[0] + "/"
        for t in tlds:
            if isinstance(t, str):
                out[t.lower()] = base
    return out


def _parse_dt(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _registrar_name(doc: dict[str, Any]) -> str | None:
    for ent in doc.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        if "registrar" not in [str(r).lower() for r in ent.get("roles", []) or []]:
            continue
        vcard = ent.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) == 2 and isinstance(vcard[1], list):
            for prop in vcard[1]:
                if isinstance(prop, list) and len(prop) >= 4 and prop[0] == "fn" and prop[3]:
                    return str(prop[3])[:200]
        handle = ent.get("handle")
        if handle:
            return str(handle)[:200]
    return None


def parse_rdap_domain(doc: Any) -> dict[str, Any]:
    """RDAP domain object -> {registered_at, expires_at, last_changed_at, registrar} (ISO strings)."""
    if not isinstance(doc, dict):
        raise FetchError("rdap_bad_object")
    dates: dict[str, str | None] = {"registration": None, "expiration": None, "last changed": None}
    for ev in doc.get("events", []) or []:
        if not isinstance(ev, dict):
            continue
        action = str(ev.get("eventAction", "")).strip().lower()
        dt = _parse_dt(ev.get("eventDate"))
        if action in dates and dt is not None and dates[action] is None:
            dates[action] = dt.isoformat()
    return {
        "status": "ok",
        "registered_at": dates["registration"],
        "expires_at": dates["expiration"],
        "last_changed_at": dates["last changed"],
        "registrar": _registrar_name(doc),
    }


async def _bootstrap(ctx: SignalContext) -> dict[str, str]:
    cache = get_cache(ctx)
    cached = await cache.get("rdap:bootstrap")
    if isinstance(cached, dict):
        return {str(k): str(v) for k, v in cached.items()}

    async def work() -> dict[str, str]:
        doc = await fetch_json(ctx.http, BOOTSTRAP_URL, timeout_s=HTTP_BUDGET_S)
        mapping = parse_bootstrap(doc)
        if not mapping:
            raise FetchError("rdap_bootstrap_empty")
        await cache.set("rdap:bootstrap", mapping, RDAP_TTL_S)
        return mapping

    return await single_flight("rdap:bootstrap", work)


async def rdap_lookup(ctx: SignalContext, domain: str, tld: str) -> dict[str, Any]:
    """Cached (24 h; 1 h negative) + single-flight RDAP lookup. Raises FetchError on transient failure."""
    cache = get_cache(ctx)
    key = f"rdap:{domain}"
    hit = await cache.get(key)
    if isinstance(hit, dict):
        return hit

    async def work() -> dict[str, Any]:
        base = (await _bootstrap(ctx)).get(tld)
        if base is None:
            res: dict[str, Any] = {"status": "unsupported_tld"}
            await cache.set(key, res, RDAP_NEG_TTL_S)
            return res
        try:
            doc = await fetch_json(ctx.http, f"{base}domain/{domain}", timeout_s=HTTP_BUDGET_S)
        except FetchError as exc:
            if exc.code == "not_found":
                res = {"status": "not_found"}
                await cache.set(key, res, RDAP_NEG_TTL_S)
                return res
            raise
        res = parse_rdap_domain(doc)
        await cache.set(key, res, RDAP_TTL_S)
        return res

    return await single_flight(key, work)


@async_signal(SPEC)
async def run(ctx: SignalContext) -> list[Evidence]:
    t = target_domain(ctx.url)
    if t is None:
        return []  # raw IP / unparsable host: nothing to look up
    try:
        info = await rdap_lookup(ctx, t.domain, t.tld)
    except FetchError as exc:
        return [error_evidence(SPEC, f"rdap_{exc.code}", "rdap")]
    status = info.get("status")
    if status == "unsupported_tld":
        return [error_evidence(SPEC, "rdap_unsupported_tld", "rdap")]
    if status == "not_found":
        return [error_evidence(SPEC, "rdap_not_found", "rdap")]
    reg = _parse_dt(info.get("registered_at"))
    if reg is None:
        return [error_evidence(SPEC, "rdap_no_registration_date", "rdap")]
    now = datetime.fromtimestamp(get_clock(ctx)(), tz=UTC)
    age = max(0, (now - reg).days)
    polarity: Literal["risk", "trust", "neutral"] = "risk" if age < 30 else "trust" if age > 3650 else "neutral"
    en = f"Domain registered {age} days ago"
    ar = f"تم تسجيل النطاق قبل {age} يومًا"
    observed = {
        "age_days": age,
        "registered_at": info["registered_at"],
        "registrar": info.get("registrar"),
        "domain": t.domain,
    }
    return [
        Evidence(
            signal=SPEC.name,
            family="domain",
            observed=observed,
            display={"en": en, "ar": ar},
            polarity=polarity,
            source="rdap",
            tier="T1",
        )
    ]
