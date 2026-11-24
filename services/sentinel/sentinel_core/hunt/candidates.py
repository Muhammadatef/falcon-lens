"""Hunt candidates: model, dedupe on registrable domain, defanging, status transitions (HUNTER.md section 4).

The live A-label name (``Candidate.domain``) exists only in memory and in Postgres. Every projection that leaves
the Sentinel (``to_contract``) carries the defanged name and its sha256 only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from falcon_core.contracts.hunt import HuntCandidate
from falcon_core.signals.url.canonical import psl_split

from ..ids import make_ulid

STATUSES = (
    "new",
    "unregistered",
    "queued",
    "submitted",
    "confirmed",
    "cleared",
    "already_known",
    "skipped_quota",
    "error",
)
# Allowed status moves. already_known is terminal: a person got there first, it is never "found before a report".
TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"unregistered", "queued", "skipped_quota", "error", "already_known"}),
    "unregistered": frozenset({"new", "error"}),
    "queued": frozenset({"submitted", "skipped_quota", "already_known", "error"}),
    "skipped_quota": frozenset({"queued", "error", "already_known"}),
    "submitted": frozenset({"confirmed", "cleared", "already_known", "error"}),
    "confirmed": frozenset({"confirmed", "cleared"}),  # a re-check may upgrade or clear
    "cleared": frozenset({"cleared", "confirmed"}),
    "error": frozenset({"new", "queued", "error"}),
    "already_known": frozenset(),
}
CONFIRMING = frozenset({"suspicious", "dangerous"})


class TransitionError(ValueError):
    pass


def registrable(name: str) -> str:
    """eTLD+1 of an A-label host per the PSL (private section included); "" if there is none."""
    host = name.strip().lower().rstrip(".")
    if not host or "." not in host:
        return ""
    _sub, dom, suf, _priv = psl_split(host)
    return f"{dom}.{suf}" if dom and suf else ""


def defang(domain: str) -> str:
    return domain.replace(".", "[.]")


def sha256_hex(domain: str) -> str:
    return hashlib.sha256(domain.lower().encode()).hexdigest()


def candidate_id(domain: str, first_seen: datetime) -> str:
    """Deterministic: the same name first seen at the same time gets the same id (stable across restarts)."""
    return "hc_" + make_ulid(first_seen, "hunt:" + domain.lower())


@dataclass(frozen=True)
class Candidate:
    domain: str  # live A-label registrable domain; never leaves the Sentinel
    brand_id: str
    discovery: str
    permutation_kind: str | None
    first_seen: datetime
    provenance: dict[str, Any]
    reasons: tuple[str, ...] = ()
    upstream_seen: datetime | None = None
    prescore: int = 0
    status: str = "new"
    verdict_id: str | None = None
    verdict: str | None = None
    verdict_at: datetime | None = None
    incident_id: str | None = None
    time_to_detection_s: float | None = None
    time_to_detection_basis: str | None = None
    checked_at: datetime | None = None  # last DNS / CT check (recheck scheduling)
    first_user_seen: datetime | None = None  # first person check of the same domain after the hunt verdict (lead)
    scheme: str = "https"  # how the cascade is asked to visit it (fixture hosts are plain http)
    candidate_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.candidate_id:
            object.__setattr__(self, "candidate_id", candidate_id(self.domain, self.first_seen))
        if self.status not in STATUSES:
            raise TransitionError(f"unknown status {self.status}")


def transition(c: Candidate, to: str, **changes: Any) -> Candidate:
    if to not in TRANSITIONS.get(c.status, frozenset()):
        raise TransitionError(f"{c.status} -> {to} not allowed")
    return replace(c, status=to, **changes)


def with_reasons(c: Candidate, *reasons: str) -> Candidate:
    return replace(c, reasons=tuple(sorted({*c.reasons, *reasons})))


def time_to_detection(
    verdict_at: datetime, cert_not_before: datetime | None, rdap_registered: datetime | None
) -> tuple[float | None, str | None]:
    """Verdict time minus the earliest upstream timestamp held; (None, None) when no basis is known."""
    basis: list[tuple[datetime, str]] = []
    if cert_not_before is not None:
        basis.append((cert_not_before, "cert_not_before"))
    if rdap_registered is not None:
        basis.append((rdap_registered, "rdap"))
    if not basis:
        return None, None
    at, name = min(basis)
    return max(0.0, (verdict_at - at).total_seconds()), name


def apply_verdict(
    c: Candidate, verdict_id: str, verdict: str, at: datetime, rdap_registered: datetime | None = None
) -> Candidate:
    """Arbiter result for a submitted candidate: confirmed (suspicious/dangerous) or cleared."""
    if c.status == "already_known":
        return c
    to = "confirmed" if verdict in CONFIRMING else "cleared"
    ttd, basis = time_to_detection(at, c.upstream_seen, rdap_registered)
    return transition(
        c,
        to,
        verdict_id=verdict_id,
        verdict=verdict,
        verdict_at=at,
        time_to_detection_s=ttd,
        time_to_detection_basis=basis,
    )


def _merge(a: Candidate, b: Candidate) -> Candidate:
    first, other = (a, b) if (a.first_seen, a.candidate_id) <= (b.first_seen, b.candidate_id) else (b, a)
    ups = [u for u in (a.upstream_seen, b.upstream_seen) if u is not None]
    return replace(
        first,
        reasons=tuple(sorted({*a.reasons, *b.reasons})),
        upstream_seen=min(ups) if ups else None,
        prescore=max(a.prescore, b.prescore),
        permutation_kind=first.permutation_kind or other.permutation_kind,
    )


def dedupe(cands: Iterable[Candidate]) -> list[Candidate]:
    """One candidate per registrable domain (earliest sighting wins; reasons merged). Stable order."""
    out: dict[str, Candidate] = {}
    for c in cands:
        reg = registrable(c.domain)
        if not reg:
            continue
        c = c if c.domain == reg else replace(c, domain=reg, candidate_id=candidate_id(reg, c.first_seen))
        out[reg] = _merge(out[reg], c) if reg in out else c
    return list(out.values())


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.isoformat().replace("+00:00", "Z")


def to_contract(c: Candidate) -> dict[str, Any]:
    """Projection onto contracts/hunt_candidate.schema.json (validated). Defanged name and sha256 only."""
    prov = dict(c.provenance)
    prov["retrieved_at"] = (
        _iso(prov["retrieved_at"]) if isinstance(prov.get("retrieved_at"), datetime) else prov.get("retrieved_at")
    )
    doc: dict[str, Any] = {
        "candidate_id": c.candidate_id,
        "domain_defanged": defang(c.domain),
        "domain_sha256": sha256_hex(c.domain),
        "brand_id": c.brand_id,
        "discovery": c.discovery,
        "permutation_kind": c.permutation_kind,
        "reasons": sorted(set(c.reasons)),
        "provenance": prov,
        "first_seen": _iso(c.first_seen),
        "upstream_seen": _iso(c.upstream_seen),
        "prescore": c.prescore,
        "status": c.status,
        "verdict_id": c.verdict_id,
        "verdict": c.verdict,
        "incident_id": c.incident_id,
        "time_to_detection_s": c.time_to_detection_s,
        "time_to_detection_basis": c.time_to_detection_basis,
    }
    HuntCandidate.model_validate(doc)
    return doc
