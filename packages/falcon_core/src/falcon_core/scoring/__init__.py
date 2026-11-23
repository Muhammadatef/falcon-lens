"""Deterministic arbiter, hard rules and template explanations (docs/SCORING.md)."""

from falcon_core.scoring.arbiter import (
    ArbiterContext,
    ArbiterResult,
    Verdict,
    band,
    has_brand_conflict,
    score,
    t1_risk_evidence,
    t1_should_exit,
    t2_should_exit,
)
from falcon_core.scoring.evidence import Evidence, from_contract, to_contract
from falcon_core.scoring.hard_rules import FiredRule
from falcon_core.scoring.params import ScoringParams, load_params
from falcon_core.scoring.reasons import (
    contract_reasons,
    template_actions,
    template_reasons,
    verdict_core_fields,
)

__all__ = [
    "ArbiterContext",
    "ArbiterResult",
    "Evidence",
    "FiredRule",
    "ScoringParams",
    "Verdict",
    "band",
    "contract_reasons",
    "from_contract",
    "has_brand_conflict",
    "load_params",
    "score",
    "t1_risk_evidence",
    "t1_should_exit",
    "t2_should_exit",
    "template_actions",
    "template_reasons",
    "to_contract",
    "verdict_core_fields",
]
