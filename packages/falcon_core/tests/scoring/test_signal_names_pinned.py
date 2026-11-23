"""Pin scoring evidence names to the names the code actually emits (regression: the arbiter scored
``domain.age`` while the T1 signal emitted ``domain.age_days``, so domain age never carried a weight)."""

from __future__ import annotations

import re
from pathlib import Path

import falcon_core
import falcon_core.signals  # noqa: F401 - registers every signal
from falcon_core.scoring.arbiter import ArbiterContext, score
from falcon_core.scoring.evidence import SIGNAL_ALIASES, Evidence, canonical_signal
from falcon_core.scoring.params import load_params
from falcon_core.signals import REGISTRY

SRC = Path(falcon_core.__file__).parent
NAME = re.compile(
    r"""["']((?:url|domain|rep|page|visual|brand|registry|message|email|image|injection|llm)\.[a-z0-9_.]+)["']"""
)
# Emitted for fingerprints / display only; the arbiter gives them no weight on purpose (SCORING §2).
INFORMATIONAL = {"domain.cert_issuer", "domain.ct_siblings", "message.contains_url", "message.contains_phone"}


# Weighted in params.yaml but not emitted by any code yet (no sandbox feature produces them): L1 to decide whether to
# implement or drop. Listed explicitly so a NEW mismatch fails this test instead of silently never scoring.
NOT_YET_EMITTED = {"page.js_obfuscation", "page.anti_inspection"}
# Built with an f-string in cascade/inputs.py (``f"{kind}.link_verdict"``), so the literal scan cannot see them.
FSTRING_EMITTED = {"message.link_verdict", "email.link_verdict"}


def _emitted() -> set[str]:
    names = {n for spec, _ in REGISTRY.values() for n in spec.emits}
    for path in SRC.rglob("*.py"):
        if "scoring" in path.parts or "tests" in path.parts:
            continue  # the scorer itself must not vouch for its own names
        names |= set(NAME.findall(path.read_text(encoding="utf-8")))
    return names


def test_every_params_weight_key_is_an_emitted_evidence_name() -> None:
    emitted = _emitted()
    assert 'link_verdict"' in (SRC / "cascade" / "inputs.py").read_text(encoding="utf-8")
    missing = sorted(k for k in load_params().weights if k not in emitted | FSTRING_EMITTED | NOT_YET_EMITTED)
    assert not missing, f"params.yaml weights for names nothing emits: {missing}"


def test_every_emitted_domain_signal_is_scored_or_explicitly_informational() -> None:
    for spec, _ in REGISTRY.values():
        for name in spec.emits:
            if name.startswith("domain."):
                scored = canonical_signal(name) in SIGNAL_ALIASES.values()
                assert scored or name in INFORMATIONAL, f"{name} is emitted but neither scored nor informational"


def _ev(signal: str, observed: object) -> Evidence:
    return Evidence(
        id="ev_" + signal.replace(".", "_")[:20], signal=signal, family="domain", observed=observed,
        source="rdap", tier="T1",
    )  # fmt: skip


def test_emitted_domain_age_names_carry_the_documented_weights() -> None:
    p = load_params()
    young = score([_ev("domain.age_days", {"age_days": 3})], 0.2, ArbiterContext())
    assert young.weighted_evidence[0].weight == p.domain_age_lt7
    month = score([_ev("domain.age_days", {"age_days": 20})], 0.2, ArbiterContext())
    assert month.weighted_evidence[0].weight == p.domain_age_lt30
    old = score([_ev("domain.age_days", {"age_days": 5000})], 0.2, ArbiterContext())
    assert old.weighted_evidence[0].weight == p.domain_age_gt3650 < 0
    cert = score([_ev("domain.cert_age_days", {"age_days": 2})], 0.2, ArbiterContext())
    assert cert.weighted_evidence[0].weight == p.cert_age_lt7


def test_same_age_fact_under_both_spellings_counts_once() -> None:
    both = score([_ev("domain.age_days", {"age_days": 3}), _ev("domain.age", {"age_days": 3})], 0.2, ArbiterContext())
    one = score([_ev("domain.age_days", {"age_days": 3})], 0.2, ArbiterContext())
    assert both.logit_adjustment == one.logit_adjustment
    assert abs(sum(e.weight for e in both.weighted_evidence) - one.weighted_evidence[0].weight) < 1e-9
