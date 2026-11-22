"""Internal evidence type for the arbiter plus a thin adapter to ``contracts/evidence.schema.json``.

TODO(T-002): replace ``Evidence`` with the pydantic ``falcon_core.contracts`` model once it merges.
Only ``from_contract`` / ``to_contract`` should need to change; the arbiter reads plain attributes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast

Family = Literal[
    "url",
    "domain",
    "reputation",
    "page",
    "visual",
    "brand",
    "message",
    "email",
    "image",
    "injection",
    "llm",
]
Tier = Literal["T0", "T1", "T2", "T3"]
Polarity = Literal["risk", "trust", "neutral"]

FAMILIES: frozenset[str] = frozenset(
    [
        "url",
        "domain",
        "reputation",
        "page",
        "visual",
        "brand",
        "message",
        "email",
        "image",
        "injection",
        "llm",
    ]
)
TIERS: frozenset[str] = frozenset(["T0", "T1", "T2", "T3"])

# Expected family for each signal prefix. Evidence whose family does not match its signal prefix
# gets weight 0 and cannot trigger a hard rule (defence against forged / mislabelled evidence).
PREFIX_FAMILY: dict[str, str] = {
    "rep": "reputation",
    "url": "url",
    "domain": "domain",
    "page": "page",
    "sandbox": "page",
    "visual": "visual",
    "brand": "brand",
    "registry": "brand",
    "message": "message",
    "email": "email",
    "injection": "injection",
    "image": "image",
    "llm": "llm",
}


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    signal: str
    family: Family
    observed: object
    source: str
    tier: Tier
    weight: float = 0.0
    polarity: Polarity = "neutral"
    hard_rule: str | None = None
    confidence: float = 1.0
    error: str | None = None
    display: Mapping[str, str] | None = None
    latency_ms: int | None = None

    def with_scoring(self, weight: float, polarity: Polarity, hard_rule: str | None) -> Evidence:
        return replace(self, weight=weight, polarity=polarity, hard_rule=hard_rule)


def family_matches(ev: Evidence) -> bool:
    prefix = ev.signal.split(".", 1)[0]
    return PREFIX_FAMILY.get(prefix) == ev.family


def untrusted_origin(ev: Evidence) -> bool:
    """Evidence that may only raise risk: LLM output, user input, injection findings."""
    return ev.source.startswith("llm") or ev.source == "user" or ev.family in ("llm", "injection")


def observed_get(ev: Evidence, key: str) -> object:
    if isinstance(ev.observed, Mapping):
        return cast(Mapping[str, object], ev.observed).get(key)
    return None


def observed_number(ev: Evidence, key: str) -> float | None:
    """Return a numeric observation: either ``observed`` itself or ``observed[key]``."""
    value = ev.observed if not isinstance(ev.observed, Mapping) else observed_get(ev, key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def is_present(ev: Evidence) -> bool:
    """True when the signal ran and reported a positive observation (not an error, not a miss)."""
    if ev.error is not None:
        return False
    obs = ev.observed
    if obs is None or obs is False:
        return False
    if isinstance(obs, Mapping):
        if not obs:
            return False
        flags = cast(Mapping[str, object], obs)
        return all(flags.get(flag) is not False for flag in ("hit", "match_found", "present"))
    if isinstance(obs, list | str):
        return len(obs) > 0
    return True


def confidence_of(ev: Evidence) -> float:
    c = float(ev.confidence)
    if math.isnan(c):
        return 0.0
    return min(1.0, max(0.0, c))


def from_contract(d: Mapping[str, object]) -> Evidence:
    """Build an ``Evidence`` from a contract-shaped dict (evidence.schema.json)."""
    family = str(d["family"])
    tier = str(d["tier"])
    if family not in FAMILIES:
        raise ValueError(f"unknown evidence family: {family}")
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    polarity = str(d.get("polarity", "neutral"))
    if polarity not in ("risk", "trust", "neutral"):
        raise ValueError(f"unknown polarity: {polarity}")
    conf = d.get("confidence", 1.0)
    weight = d.get("weight", 0.0)
    latency = d.get("latency_ms")
    display = d.get("display")
    hard_rule = d.get("hard_rule")
    error = d.get("error")
    return Evidence(
        id=str(d["id"]),
        signal=str(d["signal"]),
        family=cast(Family, family),
        observed=d.get("observed"),
        source=str(d["source"]),
        tier=cast(Tier, tier),
        weight=float(weight) if isinstance(weight, int | float) else 0.0,
        polarity=cast(Polarity, polarity),
        hard_rule=str(hard_rule) if hard_rule is not None else None,
        confidence=float(conf) if isinstance(conf, int | float) else 1.0,
        error=str(error) if error is not None else None,
        display=cast(Mapping[str, str], display) if isinstance(display, Mapping) else None,
        latency_ms=int(latency) if isinstance(latency, int) else None,
    )


def to_contract(ev: Evidence) -> dict[str, object]:
    """Serialise to the evidence.schema.json shape."""
    out: dict[str, object] = {
        "id": ev.id,
        "signal": ev.signal,
        "family": ev.family,
        "observed": ev.observed,
        "weight": round(ev.weight, 4),
        "polarity": ev.polarity,
        "hard_rule": ev.hard_rule,
        "source": ev.source,
        "tier": ev.tier,
        "confidence": confidence_of(ev),
        "error": ev.error,
    }
    if ev.display is not None:
        out["display"] = dict(ev.display)
    if ev.latency_ms is not None:
        out["latency_ms"] = ev.latency_ms
    return out
