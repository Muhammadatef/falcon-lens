"""Shared factory for arbiter tests (imported by conftest and the tests).

Fixtures only use the invented brand "Falcon Demo Bank".
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

from falcon_core.scoring.evidence import PREFIX_FAMILY, Evidence

DEMO_BRAND = "falcon_demo_bank"
DEMO_OFFICIAL = "falcon-demo-bank.test"
DEMO_LOOKALIKE = "falcon-demo-bnak.test"

_TIER_BY_FAMILY = {
    "reputation": "T0",
    "url": "T1",
    "domain": "T1",
    "message": "T1",
    "email": "T1",
    "page": "T2",
    "visual": "T2",
    "brand": "T2",
    "image": "T2",
    "injection": "T2",
    "llm": "T3",
}

_counter = itertools.count(1)

Factory = Callable[..., Evidence]


def make_evidence(
    signal: str,
    observed: Any = True,
    *,
    family: str | None = None,
    tier: str | None = None,
    confidence: float = 1.0,
    source: str = "computed",
    error: str | None = None,
    id: str | None = None,
) -> Evidence:
    fam = family or PREFIX_FAMILY[signal.split(".", 1)[0]]
    return Evidence(
        id=id or f"ev_{next(_counter):010d}",
        signal=signal,
        family=fam,  # type: ignore[arg-type]
        observed=observed,
        source=source,
        tier=(tier or _TIER_BY_FAMILY[fam]),  # type: ignore[arg-type]
        confidence=confidence,
        error=error,
    )
