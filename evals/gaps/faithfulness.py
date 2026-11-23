"""Faithfulness of user-facing explanations (deterministic checker) and of Sentinel LLM summaries.

User-facing reasons are template-only (L1 decision D3), so faithfulness here is a structural and semantic check
that needs no model: for every reason of a verdict document

  R1  it cites at least one evidence id and every cited id exists in the document's own evidence list;
  R2  its text (AR and EN) is exactly one catalog template and both languages are the same template;
  R3  the template's claim matches the cited evidence: a signal reason cites only evidence of that template's
      signal, present (no error, positive observation), with a weight whose sign agrees with the verdict side;
      a hard-rule reason cites only evidence tagged with that rule; a 'degraded' reason needs ``degraded``;
  R4  generated_by is ``template`` and there are at most three reasons.

A checker that passes everything proves nothing, so the module also mutates verdicts (unknown id, swapped template,
evidence removed, wrong tag) and reports how many mutants the checker catches.

Sentinel summaries (LLM text over an incident) are measured separately in ``sentinel_faithfulness``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from evals.gaps.common import rate
from falcon_core.i18n import load_catalog
from falcon_core.scoring.evidence import canonical_signal, from_contract, is_present, to_contract
from falcon_core.scoring.reasons import CLASSIFIER_SIGNAL, contract_reasons

HARD_KEY_TO_RULE = {"H5s": "H5"}


@lru_cache(maxsize=1)
def _catalog_index() -> dict[str, dict[str, tuple[str, str]]]:
    """lang -> template text -> (section, key)."""
    out: dict[str, dict[str, tuple[str, str]]] = {}
    for lang in ("en", "ar"):
        cat = load_catalog(lang)  # type: ignore[arg-type]
        idx: dict[str, tuple[str, str]] = {}
        for k, t in cat.reasons.items():
            idx[t] = ("reasons", k)
        for k, t in cat.hard_rules.items():
            idx[t] = ("hard_rules", k)
        idx[cat.degraded] = ("degraded", "degraded")
        out[lang] = idx
    return out


def _signal_matches(key: str, signal: str, weight: float) -> bool:
    if key == "rep.feed_hit":
        return signal.startswith("rep.")
    if key in ("domain.age.new", "domain.age.old"):
        return canonical_signal(signal) == "domain.age" and (weight > 0) == (key == "domain.age.new")
    return signal == key


def check_doc(doc: Mapping[str, Any]) -> list[str]:
    """Violations of R1-R4 for one verdict document ([] = faithful)."""
    out: list[str] = []
    ev_by_id = {e["id"]: e for e in doc.get("evidence", [])}
    reasons = list(doc.get("reasons", []))
    risk_verdict = doc.get("verdict") != "no_warning_signs"
    if len(reasons) > 3:
        out.append("R4:more_than_three_reasons")
    idx = _catalog_index()
    for n, r in enumerate(reasons):
        tag = f"reason{n}"
        ids = list(r.get("evidence_ids", []))
        if not ids:
            out.append(f"R1:{tag}:no_evidence_ids")
        for i in ids:
            if i not in ev_by_id:
                out.append(f"R1:{tag}:unknown_id")
        if r.get("generated_by") != "template":
            out.append(f"R4:{tag}:not_template")
        en_hit, ar_hit = idx["en"].get(r.get("en", "")), idx["ar"].get(r.get("ar", ""))
        if en_hit is None or ar_hit is None:
            out.append(f"R2:{tag}:text_not_in_catalog")
            continue
        if en_hit != ar_hit:
            out.append(f"R2:{tag}:languages_differ")
            continue
        section, key = en_hit
        cited = [ev_by_id[i] for i in ids if i in ev_by_id]
        if section == "degraded":
            if not doc.get("degraded"):
                out.append(f"R3:{tag}:degraded_text_on_non_degraded_verdict")
        elif section == "hard_rules":
            rule = HARD_KEY_TO_RULE.get(key, key)
            if any(e.get("hard_rule") != rule for e in cited):
                out.append(f"R3:{tag}:evidence_not_tagged_{rule}")
        else:
            for e in cited:
                sc = from_contract(dict(e))
                if key == CLASSIFIER_SIGNAL:
                    if e["signal"] != CLASSIFIER_SIGNAL:
                        out.append(f"R3:{tag}:signal_mismatch")
                    continue
                if not _signal_matches(key, e["signal"], float(e["weight"])):
                    out.append(f"R3:{tag}:signal_mismatch")
                if e.get("error") is not None or not is_present(sc):
                    out.append(f"R3:{tag}:evidence_not_present")
                w = float(e["weight"])
                if w == 0 or (risk_verdict and w < 0) or (not risk_verdict and w > 0):
                    out.append(f"R3:{tag}:polarity_vs_verdict")
    return out


def mutants(doc: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Deliberately unfaithful copies of a document (the checker must reject each)."""
    out: list[tuple[str, dict[str, Any]]] = []
    reasons = doc.get("reasons") or []
    if not reasons:
        return out
    d = copy.deepcopy(dict(doc))
    d["reasons"][0]["evidence_ids"] = ["ev_00000000zz"]
    out.append(("unknown_evidence_id", d))
    d = copy.deepcopy(dict(doc))
    d["reasons"][0]["evidence_ids"] = []
    out.append(("no_evidence_ids", d))
    d = copy.deepcopy(dict(doc))
    d["reasons"][0]["en"] = "This site is completely fine."
    out.append(("free_text_not_a_template", d))
    d = copy.deepcopy(dict(doc))
    d["reasons"][0]["generated_by"] = "llm"
    out.append(("not_template", d))
    d = copy.deepcopy(dict(doc))
    d["evidence"] = [e for e in d["evidence"] if e["id"] not in set(d["reasons"][0]["evidence_ids"])]
    out.append(("cited_evidence_removed", d))
    if len(reasons) >= 2:
        d = copy.deepcopy(dict(doc))
        d["reasons"][0]["evidence_ids"], d["reasons"][1]["evidence_ids"] = (
            list(doc["reasons"][1]["evidence_ids"]),
            list(doc["reasons"][0]["evidence_ids"]),
        )
        if d["reasons"][0]["evidence_ids"] != doc["reasons"][0]["evidence_ids"]:
            out.append(("evidence_ids_swapped_between_reasons", d))
    d = copy.deepcopy(dict(doc))
    d["reasons"][0]["ar"] = d["reasons"][0]["ar"] + " "
    out.append(("ar_text_altered", d))
    return out


def doc_from_result(result: Any, verdict: str) -> dict[str, Any]:
    """The reasons and evidence of an arbiter result in the verdict-contract shape (what the cascade publishes)."""
    return {
        "verdict": verdict,
        "degraded": bool(result.degraded),
        "evidence": [to_contract(e) for e in result.weighted_evidence],
        "reasons": contract_reasons(result),
    }


def summarise(docs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """R1-R4 pass rates over a set of verdict documents."""
    viol = [check_doc(d) for d in docs]
    n_reasons = sum(len(d.get("reasons", [])) for d in docs)
    bad_reasons = 0
    for v in viol:
        bad_reasons += len({x.split(":")[1] for x in v if x.split(":")[1].startswith("reason")})
    by_rule: dict[str, int] = {}
    for v in viol:
        for x in v:
            by_rule[x.split(":")[0]] = by_rule.get(x.split(":")[0], 0) + 1
    with_reason = [d for d in docs if d.get("reasons")]
    return {
        "verdicts": len(docs),
        "verdicts_with_reasons": len(with_reason),
        "reasons": n_reasons,
        "verdicts_fully_faithful": rate(sum(1 for v in viol if not v), len(docs)),
        "reasons_faithful": rate(n_reasons - bad_reasons, n_reasons),
        "reasons_citing_evidence_present_in_verdict": rate(
            n_reasons - sum(1 for v in viol for x in v if x.startswith(("R1:",))), n_reasons
        ),
        "violations_by_rule": by_rule,
        "verdicts_without_reasons": len(docs) - len(with_reason),
        "verdicts_without_reasons_by_verdict": {
            v: sum(1 for d in docs if not d.get("reasons") and d.get("verdict") == v)
            for v in ("dangerous", "suspicious", "no_warning_signs")
        },
        "reason_count_distribution": {str(k): sum(1 for d in docs if len(d.get("reasons", [])) == k) for k in range(4)},
    }


def mutation_report(docs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    caught: dict[str, list[int]] = {}
    for d in docs:
        for name, m in mutants(d):
            c = caught.setdefault(name, [0, 0])
            c[1] += 1
            if check_doc(m):
                c[0] += 1
    return {k: rate(v[0], v[1]) for k, v in sorted(caught.items())}
