"""The fitted T1 classifier alone never produces ``dangerous`` (L1 decision, PR #47 review).

``score_with_model`` is the one entry point the cascade and the offline eval pipeline share, so both measure the
same thing.

* Corroboration = total positive evidence weight outside the ``url`` family (page, brand, domain, reputation,
  message, email, image, visual, injection) that is not of untrusted origin (LLM, user). Hard rules that floor
  ``dangerous`` (H1, H2, H4, H5) are always allowed to decide.
* Fitted mode (``model_cap`` in params.yaml, fitted on validation by ``make fit-thresholds``): the classifier
  probability is capped ``margin`` log-odds below ``tau_high``, and ``dangerous`` without a floor rule needs a
  corroboration of at least ``strong_adj``; otherwise the score is held just under ``tau_high`` (suspicious).
* Fallback mode (no ``model_cap`` section): no new constants. Model-only risk may reach ``dangerous`` when
  ``p >= tau_high`` AND some page/domain/other risk evidence exists; with no such evidence it is held at suspicious.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from falcon_core.scoring.arbiter import ArbiterContext, ArbiterResult, logit, score
from falcon_core.scoring.evidence import Evidence, untrusted_origin
from falcon_core.scoring.params import ScoringParams, load_params

HOLD_EPS = 0.001  # log-odds under tau_high used when a dangerous verdict is held


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def corroboration(result: ArbiterResult) -> float:
    return sum(
        e.weight
        for e in result.weighted_evidence
        if e.weight > 0 and e.family != "url" and not untrusted_origin(e) and e.error is None
    )


def score_with_model(
    evidence: Sequence[Evidence], p_clf: float | None, ctx: ArbiterContext | None = None
) -> ArbiterResult:
    ctx = ctx or ArbiterContext()
    params: ScoringParams = ctx.params or load_params()
    if p_clf is None:
        return score(evidence, None, ctx)
    capped = p_clf
    if params.model_only_margin is not None:
        capped = min(p_clf, _sigmoid(logit(params.tau_high) - params.model_only_margin))
    result = score(evidence, capped, ctx)
    if result.verdict != "dangerous" or any(r.effect == "floor_dangerous" for r in result.fired_rules):
        return result
    corr = corroboration(result)
    needed = params.strong_evidence_adj if params.strong_evidence_adj is not None else 0.0
    ok = corr >= needed and corr > 0.0
    if ok:
        return result
    # Held: total log-odds just under tau_high (suspicious). Rescore with the probability that gives it.
    held = _sigmoid(logit(params.tau_high) - result.logit_adjustment - HOLD_EPS)
    return score(evidence, min(held, capped), ctx)
