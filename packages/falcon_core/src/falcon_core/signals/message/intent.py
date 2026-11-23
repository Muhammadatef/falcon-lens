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
