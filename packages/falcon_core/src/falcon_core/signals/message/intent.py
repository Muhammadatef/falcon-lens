# ruff: noqa: E501
"""``message.scam_intent``: one calibrated evidence item for link-free scam messages.

Features come from ``lexicon.RULES`` (strengthened) and ``intent_lexicon.FEATURES`` plus a few conjunctions
(authority claim AND an ask, ask AND pressure ...). A logistic model with weights fitted on the TRAIN split only
(``python -m evals.message_text.fit``, file ``intent_weights.json``) turns them into p. Evidence is emitted when
p >= theta (chosen on VAL); ``confidence`` = p. It is evidence, never a verdict: the arbiter weights it.

Observed carries feature NAMES and p only, never message text.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from falcon_core.signals.base import Evidence
from falcon_core.signals.message.extract import extract_urls
from falcon_core.signals.message.intent_lexicon import FEATURES, FROM_RULES
from falcon_core.signals.message.rules import find_rules

WEIGHTS_PATH = Path(__file__).with_name("intent_weights.json")

AUTHORITY = ("authority", "claim_bank_staff", "claim_service_role")
ASKS = ("otp_request", "ask_card_data", "remote_access", "pay_ask", "gift_card_crypto", "personal_account")
PRESSURE = ("urgency", "penalty")
PROTECTIVE = ("warning_never_share", "code_delivery")

# conjunction features (name -> (any-of A, any-of B))
CONJ: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "authority_and_ask": (AUTHORITY, ASKS),
    "ask_and_pressure": (ASKS, PRESSURE),
    "authority_and_pressure": (AUTHORITY, PRESSURE),
    "trouble_and_ask": (("account_trouble",), ASKS),
    "fee_and_offer": (("fee_word", "pay_ask"), ("prize", "job", "investment", "offer_visa_guaranteed")),
    "offplatform_and_offer": (("off_platform",), ("prize", "job", "investment", "offer_visa_guaranteed", "secrecy")),
}
FEATURE_ORDER: tuple[str, ...] = (*FROM_RULES, *FEATURES.keys(), *CONJ.keys())


_URL_RE = re.compile(r"(?i)\b(?:hxxps?|https?|ftp)://\S+|\bwww\.\S+|\b[\w-]+(?:\.|\[\.\])[a-z]{2,}(?:/\S*)?")


def strip_links(text: str) -> str:
    """Blank out links so words and digits inside a URL never count as message wording (the URL pipeline judges them)."""
    out = _URL_RE.sub(" ", text)
    for u in extract_urls(text):
        out = out.replace(u.value, " ")
    return out


def extract_features(text: str) -> dict[str, int]:
    """Binary features of one message (1 = fired)."""
    text = strip_links(text)
    f: dict[str, int] = {}
    for h in find_rules(text):
        if h.rule in FROM_RULES:
            f[h.rule] = 1
    for h in find_rules(text, FEATURES):
        f[h.rule] = 1
    for name, (a, b) in CONJ.items():
        if any(k in f for k in a) and any(k in f for k in b):
            f[name] = 1
    return f


# Floor pairs (L1-approved R-floor rules): BOTH halves must be present and no protective wording (a "never share"
# warning or a plain code delivery) may be present. name -> (rule id, half A, half B)
FLOOR_PAIRS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "pay_authority": ("RF1", ("pay_ask", "gift_card_crypto", "personal_account"), AUTHORITY),
    "remote_trouble": ("RF2", ("remote_access",), ("account_trouble",)),
    "secret_lure": ("RF3", ("otp_request", "ask_card_data"), ("urgency", "penalty", "prize", "fine")),
}
FLOOR_DISPLAY = {
    "pay_authority": {
        "en": "Asks for money while posing as an official body, bank or service",
        "ar": "يطلب مالا وهو ينتحل صفة جهة رسمية أو بنك أو شركة",
    },
    "remote_trouble": {
        "en": "Claims an account problem and asks you to install a remote-access app",
        "ar": "يدّعي مشكلة في الحساب ويطلب تثبيت تطبيق تحكم عن بعد",
    },
    "secret_lure": {
        "en": "Asks for a code, PIN or card details with pressure or a lure",
        "ar": "يطلب رمزا أو رقما سريا أو بيانات بطاقة مع ضغط أو إغراء",
    },
}


def floor_pairs(feats: dict[str, int]) -> dict[str, tuple[list[str], list[str]]]:
    """Which floor pairs hold, with the features that make up each half."""
    if any(k in feats for k in PROTECTIVE):
        return {}
    out: dict[str, tuple[list[str], list[str]]] = {}
    for name, (_rid, a, b) in FLOOR_PAIRS.items():
        pa, pb = [k for k in a if k in feats], [k for k in b if k in feats]
        if pa and pb:
            out[name] = (pa, pb)
    return out


def floor_evidence(text: str) -> list[Evidence]:
    """Zero-weight ``message.floor_pair`` evidence, one per pair that holds; the hard rule cites its id."""
    out = []
    for name, (pa, pb) in floor_pairs(extract_features(text)).items():
        rid = FLOOR_PAIRS[name][0]
        out.append(
            Evidence(
                signal="message.floor_pair",
                family="message",
                observed={"pair": name, "rule": rid, "ask": pa, "claim": pb},
                display=FLOOR_DISPLAY[name],
                hard_rule=rid,
            )
        )
    return out


@lru_cache(maxsize=1)
def load_weights() -> dict[str, Any] | None:
    try:
        w = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return w if isinstance(w, dict) and "bias" in w and "weights" in w else None


def probability(feats: dict[str, int], model: dict[str, Any]) -> float:
    z = float(model["bias"]) + sum(float(model["weights"].get(k, 0.0)) for k in feats)
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def scam_intent(text: str, model: dict[str, Any] | None = None) -> list[Evidence]:
    model = model or load_weights()
    if model is None or not text.strip():
        return []
    feats = extract_features(text)
    p = probability(feats, model)
    if p < float(model["theta"]):
        return []
    return [
        Evidence(
            signal="message.scam_intent",
            family="message",
            confidence=round(p, 4),
            observed={
                "p": round(p, 4),
                "features": sorted(k for k in feats if k not in PROTECTIVE),
                "protective": sorted(k for k in feats if k in PROTECTIVE),
            },
            display={
                "en": "The message asks for a code, money or access the way scam messages do",
                "ar": "الرسالة تطلب رمزا أو مالا أو وصولا بأسلوب رسائل الاحتيال",
            },
        )
    ]
