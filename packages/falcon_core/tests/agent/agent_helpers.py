"""Shared helpers for agent/tools tests. Only the invented brand "Falcon Demo Bank" is used."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from falcon_core.contracts.evidence import Evidence
from falcon_core.llm.config import RouterConfig
from falcon_core.llm.metrics import InMemoryMetrics
from falcon_core.llm.router import LLMRouter
from falcon_core.llm.testing import Reply, ScriptedProvider
from falcon_core.scoring import ArbiterContext, from_contract, score
from falcon_core.scoring.hard_rules import InputType

DEMO_BRAND = "falcon_demo_bank"
DEMO_DOMAIN = "falcondemobank.example"
BRAND_IDS = frozenset({DEMO_BRAND})
VERIFIED = {DEMO_BRAND: frozenset({DEMO_DOMAIN})}
CANARY = "FLC-0123456789ab"

_counter = 0


def ev(
    signal: str,
    family: str,
    observed: Any = True,
    *,
    id: str | None = None,
    weight: float = 0.0,
    source: str = "computed",
    tier: str = "T1",
    confidence: float = 1.0,
    hard_rule: str | None = None,
    error: str | None = None,
) -> Evidence:
    global _counter
    _counter += 1
    return Evidence.model_validate(
        {
            "id": id or f"ev_h{_counter:09d}",
            "signal": signal,
            "family": family,
            "observed": observed,
            "weight": weight,
            "source": source,
            "tier": tier,
            "confidence": confidence,
            "hard_rule": hard_rule,
            "error": error,
        }
    )


def local_router(
    replies: Sequence[Reply], metrics: InMemoryMetrics | None = None, **provider_kw: Any
) -> tuple[LLMRouter, ScriptedProvider, InMemoryMetrics]:
    local = ScriptedProvider("local", list(replies), **provider_kw)
    mx = metrics or InMemoryMetrics()
    router = LLMRouter(RouterConfig(), local=local, metrics=mx, canary=CANARY)
    return router, local, mx


def j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def p_of(evidence: Sequence[Evidence], input_type: InputType = "url") -> float:
    """Arbiter probability for contract evidence (the arbiter is the only scorer)."""
    res = score(
        [from_contract(e.model_dump()) for e in evidence],
        None,
        ArbiterContext(input_type=input_type),
    )
    return res.calibrated_probability
