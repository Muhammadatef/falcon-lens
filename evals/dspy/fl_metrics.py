"""Pure-Python metrics for the DSPy programs (no dspy import, so they are testable everywhere).

Faithfulness mirrors the production verifier in falcon_sentinel.graph (`_valid_ids`: a claim survives only if it
cites at least one id that exists in the evidence view) and is STRICTER: every cited id must exist, and entities
named in the claim text (rule ids, defanged domains, evidence ids) must be present in the evidence view and the
cited ids must support them. Nothing here is estimated; all numbers come from running these functions.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

SEVERITIES = ("low", "medium", "high", "critical")
SCRIPT_CATEGORIES = (
    "urgency",
    "fake_fine",
    "delivery_fee",
    "bank_otp",
    "digital_id_impersonation",
    "prize",
    "job",
    "investment",
    "none",
)
MAX_SUMMARY_CHARS = 1500  # SummaryOut.en / .ar
MAX_CLAIM_CHARS = 500  # ClaimOut.text_en
MAX_REASON_CHARS = 600  # Reason.en / .ar
FORBIDDEN_EN = re.compile(r"\bsafe\b|\bsafely\b|\bsafety\b", re.I)
FORBIDDEN_AR = re.compile("آمن")  # "safe"
ARABIC = re.compile("[؀-ۿ]")
_RULE = re.compile(r"\bR[1-9]\b")
_DEFANGED_DOMAIN = re.compile(r"[a-z0-9][a-z0-9\-]*(?:\[\.\][a-z0-9\-]+)*\[\.\]test", re.I)
_PLAIN_DOMAIN = re.compile(r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.test", re.I)
_EVT = re.compile(r"\bevt_[0-9A-Z]{26}\b")
_TYPE_WORDS = {
    "campaign": ("campaign",),
    "kit_reuse": ("kit", "reuse", "reused"),
    "report_burst": ("report", "burst"),
    "reputation_flip": ("flip", "upgraded", "reputation", "changed"),
    "quality": ("quality", "feedback"),
}
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}


def _norm_domain(value: str) -> str:
    return value.replace("[.]", ".").lower()


def valid_ids(view: Mapping[str, Any]) -> set[str]:
    return set(view["evidence_ids"])


def domain_values(view: Mapping[str, Any]) -> set[str]:
    return {_norm_domain(i["value_defanged"]) for i in view["indicators"] if i["kind"] == "domain"}


def n_domains(view: Mapping[str, Any]) -> int:
    return len(domain_values(view))


def gold_facts(view: Mapping[str, Any]) -> dict[str, Any]:
    """Key facts derived deterministically from the incident (= fixture truth after replay), never from a model."""
    return {
        "type": view["type"],
        "severity": view["severity"],
        "brand_id": view.get("brand_id"),
        "rule_ids": list(view["rule_ids"]),
        "n_domains": n_domains(view),
        "domains": sorted(domain_values(view)),
    }


# ---------------------------------------------------------------- summary pieces


def claim_supported(claim: Mapping[str, Any], view: Mapping[str, Any]) -> bool:
    """One claim is faithful iff it cites >=1 id, every cited id exists, and what it names is backed by evidence."""
    ids = list(claim.get("evidence_ids") or [])
    text = str(claim.get("text_en") or "")
    if not text.strip() or not ids:
        return False
    ok = valid_ids(view)
    if any(i not in ok for i in ids):
        return False
    for rid in set(_RULE.findall(text)):
        if rid not in view["rule_ids"] or f"rule:{rid}" not in ids:
            return False
    known = domain_values(view)
    for dom in _DEFANGED_DOMAIN.findall(text):
        if _norm_domain(dom) not in known:
            return False
    stripped = _DEFANGED_DOMAIN.sub(" ", text)
    for dom in _PLAIN_DOMAIN.findall(stripped):
        if dom.lower() not in known:
            return False
    return all(e in ok for e in _EVT.findall(text))


def faithfulness(claims: Sequence[Mapping[str, Any]], view: Mapping[str, Any]) -> float:
    """Share of supported claims; 0.0 when there are no claims (an empty summary is not faithful)."""
    if not claims:
        return 0.0
    return sum(claim_supported(c, view) for c in claims) / len(claims)


def _mentions_count(text: str, n: int) -> bool:
    if re.search(rf"\b{n}\b", text):
        return True
    return any(re.search(rf"\b{w}\b", text, re.I) for w, v in _NUMBER_WORDS.items() if v == n)


def coverage(pred: Mapping[str, Any], view: Mapping[str, Any]) -> float:
    """Fraction of key facts (type, brand, domain count, every rule id) present in the English summary + claims."""
    facts = gold_facts(view)
    text = " ".join([str(pred.get("summary_en", "")), *(str(c.get("text_en", "")) for c in pred.get("claims", []))])
    low = text.lower()
    hits: list[bool] = []
    typ = facts["type"]
    hits.append(typ.replace("_", " ") in low or typ in low or any(w in low for w in _TYPE_WORDS.get(typ, ())))
    if facts["brand_id"]:
        b = str(facts["brand_id"])
        hits.append(b in low or b.replace("_", " ") in low or b.replace("_", "-") in low)
    hits.append(_mentions_count(text, int(facts["n_domains"])) if facts["n_domains"] else True)
    hits.extend(rid in text for rid in facts["rule_ids"])
    return sum(hits) / len(hits)


def hygiene_violations(pred: Mapping[str, Any]) -> list[str]:
    """Arabic present and non-empty, no 'safe'/'آمن', production length limits."""
    bad: list[str] = []
    en, ar = str(pred.get("summary_en", "")), str(pred.get("summary_ar", ""))
    claims = [c for c in pred.get("claims", []) if isinstance(c, Mapping)]
    if not en.strip():
        bad.append("empty_en")
    if not ar.strip() or not ARABIC.search(ar):
        bad.append("arabic_missing")
    if len(en) > MAX_SUMMARY_CHARS or len(ar) > MAX_SUMMARY_CHARS:
        bad.append("summary_too_long")
    texts = [en, ar, str(pred.get("severity_reason", "")), *(str(c.get("text_en", "")) for c in claims)]
    if any(FORBIDDEN_EN.search(t) or FORBIDDEN_AR.search(t) for t in texts):
        bad.append("says_safe")
    if any(len(str(c.get("text_en", ""))) > MAX_CLAIM_CHARS for c in claims):
        bad.append("claim_too_long")
    if len(str(pred.get("severity_reason", ""))) > MAX_REASON_CHARS:
        bad.append("reason_too_long")
    return bad


WEIGHTS = {"faithfulness": 0.40, "coverage": 0.25, "arabic": 0.15, "severity": 0.10, "reason": 0.10}


def summary_components(pred: Mapping[str, Any], view: Mapping[str, Any]) -> dict[str, float]:
    claims = [c for c in pred.get("claims", []) if isinstance(c, Mapping)]
    reason = str(pred.get("severity_reason", "")).strip()
    reason_ok = float(bool(reason) and all(rid in view["rule_ids"] for rid in _RULE.findall(reason)))
    bad = hygiene_violations(pred)
    return {
        "faithfulness": faithfulness(claims, view),
        "coverage": coverage(pred, view),
        "arabic": float("arabic_missing" not in bad and "empty_en" not in bad),
        # echo only: severity is set by the rules, never by the LLM
        "severity": float(pred.get("severity") == view["severity"]),
        "reason": reason_ok,
        "hygiene_ok": float(not bad),
        "all_claims_faithful": float(bool(claims) and all(claim_supported(c, view) for c in claims)),
    }


def summary_score(pred: Mapping[str, Any], view: Mapping[str, Any]) -> float:
    """Composite in [0,1]. A hygiene violation (says 'safe', too long, no Arabic) zeroes it."""
    c = summary_components(pred, view)
    if not c["hygiene_ok"]:
        return 0.0
    return round(sum(WEIGHTS[k] * c[k] for k in WEIGHTS), 6)


# ---------------------------------------------------------------- classifier


def classifier_score(pred_category: str, pred_is_scam: bool, gold_category: str) -> float:
    gold_scam = gold_category != "none"
    if pred_category == gold_category and pred_is_scam == gold_scam:
        return 1.0
    return 0.5 if pred_is_scam == gold_scam else 0.0


def per_class_f1(gold: Sequence[str], pred: Sequence[str], labels: Iterable[str] = SCRIPT_CATEGORIES) -> dict[str, Any]:
    """Accuracy, per-class precision/recall/F1 and macro-F1 over the labels present in gold or pred."""
    out: dict[str, Any] = {}
    gc, pc = Counter(gold), Counter(pred)
    f1s: list[float] = []
    for lab in labels:
        tp = sum(1 for g, p in zip(gold, pred, strict=True) if g == lab and p == lab)
        prec = tp / pc[lab] if pc[lab] else 0.0
        rec = tp / gc[lab] if gc[lab] else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[lab] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4), "support": gc[lab]}
        if gc[lab] or pc[lab]:
            f1s.append(f1)
    n = len(gold)
    out["_accuracy"] = round(sum(g == p for g, p in zip(gold, pred, strict=True)) / n, 4) if n else 0.0
    out["_macro_f1"] = round(sum(f1s) / len(f1s), 4) if f1s else 0.0
    gs = [g != "none" for g in gold]
    ps = [p != "none" for p in pred]
    tp = sum(g and p for g, p in zip(gs, ps, strict=True))
    fp = sum((not g) and p for g, p in zip(gs, ps, strict=True))
    fn = sum(g and (not p) for g, p in zip(gs, ps, strict=True))
    out["_is_scam"] = {
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "fpr": round(fp / sum(not g for g in gs), 4) if any(not g for g in gs) else 0.0,
    }
    return out
