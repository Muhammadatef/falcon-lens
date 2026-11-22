"""Deterministic correlation keys and bucketing (ADR-002 "Correlate").

Keys: dom_simhash (Hamming <= 6), brand, registrable-domain pattern (brand skeleton + affix),
ASN, registrar, cert issuer, script embedding cluster (cosine >= 0.88), time window.
No randomness, no LLM; same input gives the same buckets.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar

from .events import Event

SIMHASH_MAX_HAMMING = 6
SCRIPT_MIN_COSINE = 0.88
_LEET = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SLD_PREFIXES = {"co", "com", "gov", "net", "org", "ac", "edu"}

T = TypeVar("T")


def refang(value: str) -> str:
    return value.strip().lower().replace("[.]", ".").replace("(.)", ".").removeprefix("hxxps://").removeprefix("hxxp://")


def defang(domain: str) -> str:
    return domain.replace(".", "[.]")


def registrable_domain(host: str) -> str:
    """Small heuristic (no PSL dependency): last two labels, three for co.ae style."""
    labels = [p for p in refang(host).split("/")[0].split(".") if p]
    if len(labels) >= 3 and labels[-2] in _SLD_PREFIXES and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def brand_skeleton(brand_id: str) -> str:
    return re.sub(r"[^a-z0-9]", "", brand_id.lower())


def _levenshtein(a: str, b: str, cap: int = 3) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def domain_pattern(domain: str, brand_id: str | None, official: frozenset[str] = frozenset()) -> tuple[bool, str | None]:
    """(is_lookalike, affix). Lookalike = brand skeleton + affix inside the registrable label,
    or a label within edit distance 1 of the skeleton (typosquat). Official domains are excluded."""
    if not brand_id:
        return False, None
    reg = registrable_domain(domain)
    if not reg or reg in official:
        return False, None
    skel = brand_skeleton(brand_id)
    label = reg.split(".")[0]
    norm = re.sub(r"[^a-z0-9]", "", label.translate(_LEET))
    if skel and skel in norm:
        affix = norm.replace(skel, "", 1)
        return True, affix
    if skel and _levenshtein(norm, skel, 1) <= 1:
        return True, ""
    return False, None


def parse_simhash(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).removeprefix("0x"), 16)
    except ValueError:
        return None


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


def cluster(items: Sequence[T], linked: Callable[[T, T], bool], key: Callable[[T], Hashable]) -> dict[Hashable, str]:
    """Single-linkage clustering (union-find). Returns item-key -> cluster label (min member key as str).
    Order independent, so replays produce identical labels."""
    keys = sorted({key(i) for i in items}, key=str)
    by_key = {key(i): i for i in items}
    parent = {k: k for k in keys}

    def find(k: Hashable) -> Hashable:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, ka in enumerate(keys):
        for kb in keys[i + 1 :]:
            if linked(by_key[ka], by_key[kb]):
                ra, rb = find(ka), find(kb)
                if ra != rb:
                    lo, hi = sorted((ra, rb), key=str)
                    parent[hi] = lo
    return {k: str(find(k)) for k in keys}


@dataclass(frozen=True)
class Features:
    """Correlation-relevant view of one event."""

    event: Event
    domain: str | None
    brand_id: str | None
    lookalike: bool
    affix: str | None
    dom_simhash: int | None
    asn: str | None
    registrar: str | None
    cert_issuer: str | None
    script_fp: str | None
    verdict: str | None
    prev_verdict: str | None
    signal: str | None
    kind: str | None

    def get(self, name: str) -> Any:
        return getattr(self, name, None)


def extract(event: Event, official: frozenset[str] = frozenset()) -> Features:
    p = event.payload
    fp = event.fingerprints
    domain: str | None = None
    brand: str | None = p.get("brand_id")
    if event.type == "domain.observed":
        if p.get("domain_defanged"):
            domain = registrable_domain(p["domain_defanged"])
        cands = p.get("brand_candidates") or []
        brand = brand or (cands[0] if cands else None)
    elif p.get("registrable_domain"):
        domain = registrable_domain(p["registrable_domain"])
    look, affix = domain_pattern(domain, brand, official) if domain else (False, None)
    asn = fp.get("asn")
    return Features(
        event=event,
        domain=domain,
        brand_id=brand,
        lookalike=look,
        affix=affix,
        dom_simhash=parse_simhash(fp.get("dom_simhash")),
        asn=None if asn is None else str(asn),
        registrar=fp.get("registrar"),
        cert_issuer=fp.get("cert_issuer"),
        script_fp=p.get("script_fingerprint") or fp.get("script_embedding_id"),
        verdict=p.get("verdict"),
        prev_verdict=p.get("previous_verdict"),
        signal=p.get("signal"),
        kind=p.get("kind"),
    )


def group_label(
    feats: Sequence[Features], group_by: str, vectors: dict[str, list[float]] | None = None
) -> dict[str, str | None]:
    """event_id -> bucket label for the given group_by key. Clustered keys use single linkage."""
    vectors = vectors or {}
    out: dict[str, str | None] = {}
    if group_by == "dom_simhash":
        have = [f for f in feats if f.dom_simhash is not None]
        lab = cluster(
            have,
            lambda a, b: hamming(a.dom_simhash or 0, b.dom_simhash or 0) <= SIMHASH_MAX_HAMMING,
            key=lambda f: f.dom_simhash,
        )
        for f in feats:
            out[f.event.event_id] = None if f.dom_simhash is None else f"sh:{int(lab[f.dom_simhash]):016x}"
    elif group_by == "script_cluster":
        have = [f for f in feats if f.script_fp]

        def linked(a: Features, b: Features) -> bool:
            va, vb = vectors.get(a.script_fp or ""), vectors.get(b.script_fp or "")
            return va is not None and vb is not None and cosine(va, vb) >= SCRIPT_MIN_COSINE

        lab = cluster(have, linked, key=lambda f: f.script_fp)
        for f in feats:
            out[f.event.event_id] = f"sc:{lab[f.script_fp]}" if f.script_fp else None
    else:
        for f in feats:
            v = f.get(group_by)
            out[f.event.event_id] = None if v in (None, "") else f"{group_by}:{v}"
    return out


def window_trigger(times: Sequence[tuple[datetime, str]], window: timedelta, min_count: int) -> datetime | None:
    """Time at which some span <= window first holds >= min_count distinct units, else None.
    times = [(datetime, unit)] sorted by time."""
    lo = 0
    for hi in range(len(times)):
        while times[hi][0] - times[lo][0] > window:
            lo += 1
        if len({u for _, u in times[lo : hi + 1]}) >= min_count:
            return times[hi][0]
    return None


def sessions(feats: Sequence[Features], gap: timedelta) -> list[list[Features]]:
    """Chain events (sorted by time) into sessions where consecutive gaps are <= gap."""
    out: list[list[Features]] = []
    for f in sorted(feats, key=lambda x: (x.event.occurred_at, x.event.event_id)):
        if out and f.event.occurred_at - out[-1][-1].event.occurred_at <= gap:
            out[-1].append(f)
        else:
            out.append([f])
    return out


def correlation_keys(feats: Sequence[Features]) -> dict[str, Any]:
    def uniq(vals: Any) -> list[Any]:
        return sorted({v for v in vals if v not in (None, "")}, key=str)

    times = [f.event.occurred_at for f in feats]
    return {
        "brand": uniq(f.brand_id for f in feats),
        "dom_simhash": uniq(f"{f.dom_simhash:016x}" for f in feats if f.dom_simhash is not None),
        "domain_pattern": uniq(f"{f.brand_id}+{f.affix}" for f in feats if f.lookalike),
        "asn": uniq(f.asn for f in feats),
        "registrar": uniq(f.registrar for f in feats),
        "cert_issuer": uniq(f.cert_issuer for f in feats),
        "script_cluster": uniq(f.script_fp for f in feats),
        "window": {
            "start": min(times).isoformat().replace("+00:00", "Z"),
            "end": max(times).isoformat().replace("+00:00", "Z"),
        },
    }
