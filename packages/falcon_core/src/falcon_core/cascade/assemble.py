"""Assemble a ``contracts/verdict.schema.json`` document from an arbiter result.

The arbiter owns verdict/score/evidence weights/reasons/actions (``verdict_core_fields``); this
module adds ids, tier, timing, trace, brand and the defanged canonical URL, then validates the
result against the pydantic contract plus the CONTRACTS.md invariants before it is published.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import unquote

from falcon_core.contracts.verdict import Verdict as VerdictModel
from falcon_core.llm.redaction import redact
from falcon_core.scoring.arbiter import ArbiterResult
from falcon_core.scoring.evidence import is_present, observed_get
from falcon_core.scoring.reasons import ReportingChannels, verdict_core_fields
from falcon_core.signals.brands.registry import BrandRegistry

Tier = Literal["T0", "T1", "T2", "T3"]


def display_url(url: str) -> str:
    """The copy of a checked URL that is stored, returned and shown: host kept, personal data removed.

    Phishing links often carry the recipient in the address (``?email=...``, ``/u/<phone>``). The verdict's
    ``canonical_url`` is "for display" (contracts/verdict.schema.json), so everything after the host is passed
    through the same redaction as text sent to a cloud model (emails, UAE phones, Emirates ID, cards, IBAN),
    also when percent-encoded, and the fragment is dropped (it is never sent to a server). The check itself
    and the cache key still use the full canonical URL; only this copy is reduced.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    host, slash, tail = rest.partition("/")
    if not slash:
        host, q, query = rest.partition("?")
        tail = f"?{query}" if q else ""
    else:
        tail = "/" + tail
    tail = tail.split("#", 1)[0]
    if not tail:
        return f"{scheme}://{host}"
    res = redact(tail)
    if "%" in tail:
        decoded = redact(unquote(tail))
        if decoded.redacted:
            res = decoded
    return f"{scheme}://{host}{res.text if res.redacted else tail}"


BRAND_SIGNALS = frozenset(
    [
        "brand.claimed_not_owned",
        "url.homograph",
        "url.typosquat",
        "url.combosquat",
        "url.brand_in_subdomain_or_path",
        "visual.favicon_match_brand",
        "page.hotlinked_brand_assets",
    ]
)


class VerdictInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TraceStep:
    name: str
    summary: str
    evidence_added: tuple[str, ...] = ()
    ms: int | None = None
    kind: Literal["tier", "tool", "llm", "rule"] = "tier"


def impersonated_brand(result: ArbiterResult, registry: BrandRegistry) -> dict[str, Any] | None:
    if result.verdict == "no_warning_signs":
        return None
    best: tuple[float, str] | None = None
    for e in result.weighted_evidence:
        if e.signal in BRAND_SIGNALS and e.weight > 0 and is_present(e):
            bid = observed_get(e, "brand_id")
            if isinstance(bid, str) and (best is None or e.weight > best[0]):
                best = (e.weight, bid)
    if best is None:
        return None
    brand = next((b for b in registry.brands if b.brand_id == best[1]), None)
    if brand is None:
        return None
    return {
        "brand_id": brand.brand_id,
        "name_ar": brand.name_ar,
        "name_en": brand.name_en,
        "official_domains": list(brand.verified_domains),
    }


def build_verdict(
    result: ArbiterResult,
    *,
    verdict_id: str,
    input_type: Literal["url", "message", "email", "image"],
    tier: Tier,
    final: bool,
    latency_ms: int,
    registry: BrandRegistry,
    canonical_url_defanged: str | None = None,
    input_fingerprint: str | None = None,
    trace: Sequence[TraceStep] = (),
    source: str = "live",
    channels: ReportingChannels | None = None,
    created_at: datetime | None = None,
    reasons: Sequence[dict[str, Any]] | None = None,
    model_route: Literal["cloud", "local", "none"] = "none",
) -> dict[str, Any]:
    core = verdict_core_fields(result, channels)
    if reasons is not None:  # responder output (already verified against the evidence); template otherwise
        core["reasons"] = list(reasons)
    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "verdict_id": verdict_id,
        "input_type": input_type,
        "canonical_url": canonical_url_defanged,
        **core,
        "impersonated_brand": impersonated_brand(result, registry),
        "tier_reached": tier,
        "model_route": model_route,
        "final": final,
        "screenshot_url": None,
        "source": source,
        "latency_ms": max(0, int(latency_ms)),
        "created_at": (created_at or datetime.now(UTC)).isoformat(),
    }
    if input_fingerprint:
        doc["input_fingerprint"] = input_fingerprint
    if trace:
        steps = []
        for i, t in enumerate(trace, start=1):
            s: dict[str, Any] = {
                "step": i,
                "kind": t.kind,
                "name": t.name,
                "summary": t.summary[:240],
            }
            if t.evidence_added:
                s["evidence_added"] = list(t.evidence_added)
            if t.ms is not None:
                s["ms"] = max(0, int(t.ms))
            steps.append(s)
        doc["trace"] = steps
    check_invariants(doc)
    return doc


def reissue(
    prior: dict[str, Any],
    *,
    verdict_id: str,
    source: str,
    latency_ms: int,
    note: str,
    input_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Re-issue a previous final verdict (cache hit or single-flight follower) under a new id.

    Evidence, score and reasons are unchanged (the arbiter decided them); only identity, timing
    and the trace change.
    """
    doc = dict(prior)
    prev = [dict(s) for s in list(doc.get("trace") or [])[-19:]]
    for i, s in enumerate(prev, start=1):
        s["step"] = i
    prev.append({"step": len(prev) + 1, "kind": "tier", "name": "T0", "summary": note[:240]})
    doc.update(
        verdict_id=verdict_id,
        final=True,
        latency_ms=max(0, int(latency_ms)),
        created_at=datetime.now(UTC).isoformat(),
        source=source,
        trace=prev,
        screenshot_url=None,
    )
    if input_fingerprint:
        doc["input_fingerprint"] = input_fingerprint
    check_invariants(doc)
    return doc


def check_invariants(doc: dict[str, Any]) -> None:
    """Pydantic contract + CONTRACTS.md invariants 1-5. Raises ``VerdictInvariantError``."""
    try:
        VerdictModel.model_validate(doc)
    except ValueError as exc:
        raise VerdictInvariantError(f"contract: {exc}") from exc
    ids = {e["id"] for e in doc["evidence"]}
    if len(ids) != len(doc["evidence"]):
        raise VerdictInvariantError("duplicate evidence ids")
    for r in doc["reasons"]:
        missing = [i for i in r["evidence_ids"] if i not in ids]
        if missing:
            raise VerdictInvariantError(f"reason cites unknown evidence {missing}")
    if doc["verdict"] == "no_warning_signs":
        if not doc["actions"].get("caution"):
            raise VerdictInvariantError("no_warning_signs without caution")
        if doc["degraded"]:
            raise VerdictInvariantError("degraded verdict shown as no_warning_signs")
    cu = doc.get("canonical_url")
    if cu and (cu.startswith(("http://", "https://")) or "." in cu.replace("[.]", "")):
        raise VerdictInvariantError("canonical_url is not defanged")
