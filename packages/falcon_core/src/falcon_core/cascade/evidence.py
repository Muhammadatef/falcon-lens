"""Evidence at the cascade boundary.

Three evidence types meet here: ``signals.base.Evidence`` (mutable dataclass emitted by T1
plugins), ``scoring.evidence.Evidence`` (frozen dataclass the arbiter reads) and the pydantic
``contracts.Evidence`` (the wire contract). The cascade works in the scoring type and validates
the final dicts against the pydantic contract when it assembles a verdict.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from falcon_core.cascade.ids import evidence_id
from falcon_core.scoring.evidence import Evidence, Family, Tier, from_contract
from falcon_core.signals.base import Evidence as SignalEvidence


def make_evidence(
    signal: str,
    family: Family,
    observed: Any,
    *,
    tier: Tier,
    source: str,
    confidence: float = 1.0,
    en: str | None = None,
    ar: str | None = None,
    error: str | None = None,
    latency_ms: int | None = None,
) -> Evidence:
    display = None
    if en is not None or ar is not None:
        display = {k: v[:200] for k, v in (("en", en), ("ar", ar)) if v is not None}
    return Evidence(
        id=evidence_id(signal, observed if error is None else {"error": error}),
        signal=signal,
        family=family,
        observed=observed,
        source=source,
        tier=tier,
        confidence=confidence,
        error=error,
        display=display,
        latency_ms=latency_ms,
    )


def from_signal(ev: SignalEvidence) -> Evidence:
    """Convert a T1 plugin's evidence. Weight/polarity are reset: only the arbiter assigns them."""
    d = ev.to_dict()
    d["weight"] = 0.0
    d["polarity"] = "neutral"
    d["hard_rule"] = None
    return from_contract(d)


def dedupe(evidence: Iterable[Evidence]) -> list[Evidence]:
    """Keep the first evidence per id (ids are deterministic per signal + observation)."""
    seen: set[str] = set()
    out: list[Evidence] = []
    for e in evidence:
        if e.id not in seen:
            seen.add(e.id)
            out.append(e)
    return out
