"""Arbiter parameters from ``params.yaml`` (draft until fitted by ``make fit-thresholds``)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

import yaml

DEFAULT_PARAMS_PATH = Path(__file__).with_name("params.yaml")


class ParamsError(ValueError):
    """Raised when params.yaml is missing a field or holds an inconsistent value."""


@dataclass(frozen=True, slots=True)
class ScoringParams:
    draft: bool
    tau_high: float
    tau_low: float
    eps_low: float
    eps_high: float
    t2_margin_low: float
    t2_margin_high: float
    logit_clip: float
    draft_intercept: float
    calibrator_kind: str
    h1_brand_claim_min_confidence: float
    h1_p_floor: float
    h2_max_feed_age_s: float
    h3_p_cap: float
    domain_age_lt7: float
    domain_age_lt30: float
    domain_age_gt3650: float
    cert_age_lt7: float
    message_rule_weight: float
    message_rule_cap: float
    message_rule_names: frozenset[str]
    weights: dict[str, float]
    attachment_risky_weight: float = 1.5
    attachment_executable_types: frozenset[str] = frozenset()
    informational_errors: frozenset[str] = frozenset()
    degrading_signals: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not 0.0 < self.tau_low < self.tau_high < 1.0:
            raise ParamsError("need 0 < tau_low < tau_high < 1")
        if not 0.0 <= self.eps_low < self.eps_high <= 1.0:
            raise ParamsError("need 0 <= eps_low < eps_high <= 1")
        if not self.tau_high <= self.h1_p_floor <= 1.0:
            raise ParamsError("h1_p_floor must be in [tau_high, 1]")
        if not 0.0 <= self.h3_p_cap < self.tau_low:
            raise ParamsError("h3_p_cap must be below tau_low")
        if self.logit_clip <= 0:
            raise ParamsError("logit_clip must be positive")
        if self.calibrator_kind != "identity":
            # TODO(T-022): support fitted isotonic/Platt calibrators written by make fit-thresholds.
            raise ParamsError(f"unsupported calibrator kind: {self.calibrator_kind}")


def _section(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ParamsError(f"params.yaml: missing section '{key}'")
    return cast(dict[str, object], value)


def _num(section: dict[str, object], key: str) -> float:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ParamsError(f"params.yaml: '{key}' must be a number")
    return float(value)


def _str_set(raw: dict[str, object], key: str) -> frozenset[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ParamsError(f"params.yaml: '{key}' must be a list of strings")
    return frozenset(cast(list[str], value))


def params_from_mapping(raw: dict[str, object]) -> ScoringParams:
    bands = _section(raw, "bands")
    cascade = _section(raw, "cascade")
    draft_clf = _section(raw, "draft_classifier")
    calibrator = _section(raw, "calibrator")
    hard = _section(raw, "hard_rules")
    dage = _section(raw, "domain_age")
    cage = _section(raw, "cert_age")
    mrules = _section(raw, "message_rules")
    weights_raw = _section(raw, "weights")
    attach = _section(raw, "email_attachment")
    names = mrules.get("names")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ParamsError("params.yaml: message_rules.names must be a list of strings")
    clip = raw.get("logit_clip")
    if isinstance(clip, bool) or not isinstance(clip, int | float):
        raise ParamsError("params.yaml: 'logit_clip' must be a number")
    return ScoringParams(
        draft=bool(raw.get("draft", True)),
        tau_high=_num(bands, "tau_high"),
        tau_low=_num(bands, "tau_low"),
        eps_low=_num(cascade, "eps_low"),
        eps_high=_num(cascade, "eps_high"),
        t2_margin_low=_num(cascade, "t2_margin_low"),
        t2_margin_high=_num(cascade, "t2_margin_high"),
        logit_clip=float(clip),
        draft_intercept=_num(draft_clf, "intercept"),
        calibrator_kind=str(calibrator.get("kind", "identity")),
        h1_brand_claim_min_confidence=_num(hard, "h1_brand_claim_min_confidence"),
        h1_p_floor=_num(hard, "h1_p_floor"),
        h2_max_feed_age_s=_num(hard, "h2_max_feed_age_s"),
        h3_p_cap=_num(hard, "h3_p_cap"),
        domain_age_lt7=_num(dage, "lt7_days"),
        domain_age_lt30=_num(dage, "lt30_days"),
        domain_age_gt3650=_num(dage, "gt3650_days"),
        cert_age_lt7=_num(cage, "lt7_days"),
        message_rule_weight=_num(mrules, "weight_each"),
        message_rule_cap=_num(mrules, "cap"),
        message_rule_names=frozenset(cast(list[str], names)),
        weights={str(k): _num(weights_raw, str(k)) for k in weights_raw},
        attachment_risky_weight=_num(attach, "risky_weight"),
        attachment_executable_types=_str_set(attach, "executable_types"),
        informational_errors=_str_set(raw, "informational_errors"),
        degrading_signals=_str_set(raw, "degrading_signals"),
    )


def load_params(path: Path | None = None) -> ScoringParams:
    """Load params from ``path`` (default: the packaged ``params.yaml``). Cached per path."""
    return _load_cached(str(path or DEFAULT_PARAMS_PATH))


@lru_cache(maxsize=8)
def _load_cached(path: str) -> ScoringParams:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ParamsError(f"{path}: expected a mapping")
    return params_from_mapping(cast(dict[str, object], raw))
