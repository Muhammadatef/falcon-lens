"""Hosting and full-registration evidence for the police evidence pack (informational, weight 0).

``infra.hosting``  -> ``infra.ip`` (public A/AAAA of the checked host) and ``infra.hosting_asn``
                      (ASN, AS name, country: Team Cymru IP-to-ASN, queried as DNS TXT over DNS-over-HTTPS).
``infra.rdap``     -> ``infra.rdap_registrar`` (registrar, dates, nameservers, status, registrar abuse contact).

All network I/O is ``ctx.http`` (egress proxy + SSRF guard); DNS is DoH JSON from dns.google/resolve because a
raw UDP/TCP DNS query would bypass the guarded path. Every IP found is re-checked with the SSRF IP rules and
non-public answers are dropped (counted, never reported). Only the registrar entity and its abuse contact are
read from RDAP: registrant, admin and tech entities (personal data) are never parsed.
Both signals are ``enrichment``: a failure is a gap in the pack, never a degraded verdict, and no scoring
rule uses these names (SCORING section 2, informational).
"""

from __future__ import annotations

import asyncio
import ipaddress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from falcon_core.security.ssrf import ip_block_reason
from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, async_signal
from falcon_core.signals.cache import get_cache, get_clock, single_flight
from falcon_core.signals.domain.common import FetchError, error_evidence, fetch_json, target_domain
from falcon_core.signals.domain.rdap import _bootstrap, _parse_dt
from falcon_core.signals.url.canonical import canonicalize

DOH_URL = "https://dns.google/resolve"
CYMRU_ORIGIN4 = "origin.asn.cymru.com"
CYMRU_ORIGIN6 = "origin6.asn.cymru.com"
CYMRU_ASN = "asn.cymru.com"
HOSTING_TTL_S = 6 * 3600
HOSTING_NEG_TTL_S = 900
RDAP_FULL_TTL_S = 24 * 3600
STEP_BUDGET_S = 0.9  # per hop; each signal is capped at 2 s
MAX_IPS = 4
MAX_ASN_LOOKUPS = 2

HOSTING_SPEC = SignalSpec(
    name="infra.hosting",
    family="domain",
    tier="T1",
    input_types=("url",),
    timeout_ms=2000,
    network="egress_proxy",
    emits=("infra.ip", "infra.hosting_asn"),
    cache_ttl_s=HOSTING_TTL_S,
    criticality="enrichment",
)
RDAP_SPEC = SignalSpec(
    name="infra.rdap",
    family="domain",
    tier="T1",
    input_types=("url",),
    timeout_ms=2000,
    network="egress_proxy",
    emits=("infra.rdap_registrar",),
    cache_ttl_s=RDAP_FULL_TTL_S,
    criticality="enrichment",
)


def _iso(ctx: Any) -> str:
    return datetime.fromtimestamp(get_clock(ctx)(), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ DNS over HTTPS


def parse_doh(doc: Any, rtype: int) -> list[str]:
    """DoH JSON answer -> record data strings of the requested type (quotes stripped from TXT)."""
    if not isinstance(doc, dict) or doc.get("Status") != 0:
        return []
    out: list[str] = []
    for a in doc.get("Answer", []) or []:
        if isinstance(a, dict) and a.get("type") == rtype and isinstance(a.get("data"), str):
            out.append(a["data"].strip().strip('"'))
    return out


async def doh(ctx: SignalContext, name: str, rtype: str) -> list[str]:
    code = {"A": 1, "AAAA": 28, "TXT": 16}[rtype]
    doc = await fetch_json(
        ctx.http,
        f"{DOH_URL}?name={quote(name, safe='.-_')}&type={rtype}",
        timeout_s=STEP_BUDGET_S,
        max_bytes=64 * 1024,
    )
    return parse_doh(doc, code)


def cymru_origin_name(ip: str) -> str:
    addr = ipaddress.ip_address(ip)
    rev = addr.reverse_pointer
    if isinstance(addr, ipaddress.IPv4Address):
        return rev.removesuffix(".in-addr.arpa") + "." + CYMRU_ORIGIN4
    return rev.removesuffix(".ip6.arpa") + "." + CYMRU_ORIGIN6


def _fields(txt: str) -> list[str]:
    return [p.strip() for p in txt.split("|")]


def parse_cymru_origin(txt: str) -> dict[str, Any] | None:
    """'15169 | 8.8.8.0/24 | US | arin | 2023-12-28' -> {asn, prefix, country, registry} (first ASN if several)."""
    f = _fields(txt)
    if len(f) < 3 or not f[0]:
        return None
    asn = f[0].split()[0]
    if not asn.isdigit():
        return None
    return {
        "asn": int(asn),
        "prefix": f[1][:64],
        "country": f[2][:2].upper() or None,
        "registry": f[3][:16] if len(f) > 3 else None,
    }


def parse_cymru_asn(txt: str) -> str | None:
    """'15169 | US | arin | 2000-03-30 | GOOGLE, US' -> 'GOOGLE, US'."""
    f = _fields(txt)
    return f[4][:120] if len(f) >= 5 and f[4] else None


async def asn_for_ip(ctx: SignalContext, ip: str) -> dict[str, Any] | None:
    origin = await doh(ctx, cymru_origin_name(ip), "TXT")
    info = next((p for p in map(parse_cymru_origin, origin) if p), None)
    if info is None:
        return None
    name: str | None = None
    try:
        recs = await doh(ctx, f"AS{info['asn']}.{CYMRU_ASN}", "TXT")
        name = next((n for n in map(parse_cymru_asn, recs) if n), None)
    except FetchError:
        name = None  # the ASN number alone is still evidence
    return {"ip": ip, **info, "as_name": name}


def _public(ips: list[str]) -> tuple[list[str], int]:
    keep: list[str] = []
    dropped = 0
    for ip in dict.fromkeys(ips):
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            dropped += 1
            continue
        if ip_block_reason(ip) is None:
            keep.append(ip)
        else:
            dropped += 1
    return keep[:MAX_IPS], dropped


async def _resolve(ctx: SignalContext, host: str) -> dict[str, Any]:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        ips, dropped = _public([host.strip("[]")])
        return {"ips": ips, "non_public_dropped": dropped}
    a, aaaa = await asyncio.gather(doh(ctx, host, "A"), doh(ctx, host, "AAAA"), return_exceptions=True)
    if isinstance(a, BaseException) and isinstance(aaaa, BaseException):
        raise a if isinstance(a, FetchError) else FetchError("dns_failed")
    recs = [x for r in (a, aaaa) if not isinstance(r, BaseException) for x in r]
    ips, dropped = _public(recs)
    return {"ips": ips, "non_public_dropped": dropped}


async def hosting_lookup(ctx: SignalContext, host: str) -> dict[str, Any]:
    cache = get_cache(ctx)
    key = f"infra:hosting:{host}"
    hit = await cache.get(key)
    if isinstance(hit, dict):
        return hit

    async def work() -> dict[str, Any]:
        res = await _resolve(ctx, host)
        if res["ips"]:
            try:  # keeps the IPs even when the ASN hops run out of the 2 s budget
                got = await asyncio.wait_for(
                    asyncio.gather(
                        *(asn_for_ip(ctx, ip) for ip in res["ips"][:MAX_ASN_LOOKUPS]), return_exceptions=True
                    ),
                    timeout=0.95,
                )
            except TimeoutError:
                got = []
            res["asns"] = [g for g in got if isinstance(g, dict)]
        else:
            res["asns"] = []
        res["retrieved_at"] = _iso(ctx)
        await cache.set(key, res, HOSTING_TTL_S if res["ips"] else HOSTING_NEG_TTL_S)
        return res

    return await single_flight(key, work)


def _host_of(ctx: SignalContext) -> str | None:
    c = canonicalize(ctx.url or "")
    if not c.ok or c.is_data_uri or not c.host_ascii:
        return None
    return c.host_ascii.lower()


@async_signal(HOSTING_SPEC)
async def run_hosting(ctx: SignalContext) -> list[Evidence]:
    host = _host_of(ctx)
    if host is None:
        return []
    try:
        info = await hosting_lookup(ctx, host)
    except FetchError as exc:
        return [error_evidence(HOSTING_SPEC, f"hosting_{exc.code}", "dns")]
    ips = info["ips"]
    if not ips:
        return [error_evidence(HOSTING_SPEC, "hosting_no_public_ip", "dns")]
    out = [
        Evidence(
            signal="infra.ip",
            family="domain",
            observed={
                "host": host,
                "resolved_ips": ips,
                "non_public_dropped": info.get("non_public_dropped", 0),
                "hosting_source": "dns.google DoH",
                "retrieved_at": info["retrieved_at"],
            },
            display={"en": f"Resolves to {', '.join(ips[:2])}", "ar": f"يُحلّ إلى {'، '.join(ips[:2])}"},
            polarity="neutral",
            source="dns",
            tier="T1",
        )
    ]
    asns = info.get("asns") or []
    if asns:
        top = asns[0]
        label = f"AS{top['asn']} {top.get('as_name') or ''}".strip()
        out.append(
            Evidence(
                signal="infra.hosting_asn",
                family="domain",
                observed={
                    "asn": top["asn"],
                    "as_name": top.get("as_name"),
                    "country": top.get("country"),
                    "prefix": top.get("prefix"),
                    "ip": top["ip"],
                    "asns": asns,
                    "hosting_source": "Team Cymru IP-to-ASN (DNS TXT via DoH)",
                    "retrieved_at": info["retrieved_at"],
                },
                display={"en": f"Hosted on {label}", "ar": f"مُستضاف على {label}"},
                polarity="neutral",
                source="cymru",
                tier="T1",
            )
        )
    else:
        out.append(error_evidence(HOSTING_SPEC, "asn_lookup_failed", "cymru"))
    return out


# ------------------------------------------------------------------ RDAP, registrar view only


def _vcard(ent: dict[str, Any], prop: str) -> str | None:
    vc = ent.get("vcardArray")
    if isinstance(vc, list) and len(vc) == 2 and isinstance(vc[1], list):
        for p in vc[1]:
            if isinstance(p, list) and len(p) >= 4 and p[0] == prop and isinstance(p[3], str) and p[3].strip():
                return p[3].strip().removeprefix("tel:").removeprefix("mailto:")[:200]
    return None


def _roles(ent: Any) -> set[str]:
    return {str(r).lower() for r in (ent.get("roles") or [])} if isinstance(ent, dict) else set()


def parse_rdap_full(doc: Any, retrieved_at: str, source: str) -> dict[str, Any]:
    """RDAP domain object -> registrar-level facts only. Registrant/admin/tech entities are never read."""
    if not isinstance(doc, dict):
        raise FetchError("rdap_bad_object")
    dates: dict[str, str | None] = {"registration": None, "expiration": None, "last changed": None}
    for ev in doc.get("events") or []:
        if isinstance(ev, dict):
            action = str(ev.get("eventAction", "")).strip().lower()
            dt = _parse_dt(ev.get("eventDate"))
            if action in dates and dt is not None and dates[action] is None:
                dates[action] = dt.isoformat()
    registrar = iana_id = abuse_email = abuse_phone = None
    for ent in doc.get("entities") or []:
        if not isinstance(ent, dict) or "registrar" not in _roles(ent):
            continue
        registrar = _vcard(ent, "fn") or (str(ent["handle"])[:200] if ent.get("handle") else None)
        for pid in ent.get("publicIds") or []:
            if isinstance(pid, dict) and "iana" in str(pid.get("type", "")).lower():
                iana_id = str(pid.get("identifier"))[:16]
        for sub in ent.get("entities") or []:
            if "abuse" in _roles(sub):
                abuse_email = abuse_email or _vcard(sub, "email")
                abuse_phone = abuse_phone or _vcard(sub, "tel")
        break
    ns = sorted(
        {
            str(n["ldhName"]).lower().rstrip(".")[:253]
            for n in doc.get("nameservers") or []
            if isinstance(n, dict) and n.get("ldhName")
        }
    )
    return {
        "registrar": registrar,
        "registrar_iana_id": iana_id,
        "created": dates["registration"],
        "expires": dates["expiration"],
        "updated": dates["last changed"],
        "nameservers": ns[:13],
        "status": [str(s)[:64] for s in (doc.get("status") or [])][:12],
        "abuse_email": abuse_email,
        "abuse_phone": abuse_phone,
        "rdap_source": source,
        "retrieved_at": retrieved_at,
    }


async def rdap_full_lookup(ctx: SignalContext, domain: str, tld: str) -> dict[str, Any]:
    cache = get_cache(ctx)
    key = f"infra:rdap:{domain}"
    hit = await cache.get(key)
    if isinstance(hit, dict):
        return hit

    async def work() -> dict[str, Any]:
        base = (await _bootstrap(ctx)).get(tld)
        if base is None:
            res: dict[str, Any] = {"status_code": "unsupported_tld"}
            await cache.set(key, res, 3600)
            return res
        try:
            doc = await fetch_json(ctx.http, f"{base}domain/{domain}", timeout_s=STEP_BUDGET_S)
        except FetchError as exc:
            if exc.code == "not_found":
                res = {"status_code": "not_found"}
                await cache.set(key, res, 3600)
                return res
            raise
        res = parse_rdap_full(doc, _iso(ctx), f"{base}domain/{domain}")
        await cache.set(key, res, RDAP_FULL_TTL_S)
        return res

    return await single_flight(key, work)


@async_signal(RDAP_SPEC)
async def run_rdap(ctx: SignalContext) -> list[Evidence]:
    t = target_domain(ctx.url)
    if t is None:
        return []
    try:
        info = await rdap_full_lookup(ctx, t.domain, t.tld)
    except FetchError as exc:
        return [error_evidence(RDAP_SPEC, f"rdap_{exc.code}", "rdap")]
    if info.get("status_code"):
        return [error_evidence(RDAP_SPEC, f"rdap_{info['status_code']}", "rdap")]
    reg = info.get("registrar") or "unknown registrar"
    return [
        Evidence(
            signal="infra.rdap_registrar",
            family="domain",
            observed={**info, "domain": t.domain},
            display={"en": f"Registrar: {reg}", "ar": f"مسجّل النطاق: {reg}"},
            polarity="neutral",
            source="rdap",
            tier="T1",
        )
    ]
