# ruff: noqa: E501
"""R-floor rules RF1-RF3 (L1-approved): both halves required, no protective wording, floor at `suspicious` only,
evidence ids cited. Invented brand and numbers only."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from falcon_core.cascade.evidence import from_signal
from falcon_core.scoring.arbiter import ArbiterContext, score
from falcon_core.scoring.params import load_params
from falcon_core.signals.message.analyze import analyze_message

RF_CASES = {
    "RF1": [
        "This is the fraud department of your bank. Send AED 500 to this personal account today.",
        "معك ضابط من الشرطة، باسمك قضية. حول مبلغ الكفالة الحين.",
        "ana men el shurta, 3endak qadiya bismak. idfa3 el kafala halhin.",
    ],
    "RF2": [
        "Your account has a technical problem. Install the remote support tool we sent so we can fix it.",
        "جهازك فيه فايروس يهدد حسابك. نزّل البرنامج اللي بنرسله لك عشان نتحكم بالجهاز.",
    ],
    "RF3": [
        "Reply with the code you just received. Your account will be blocked within 2 hours.",
        "ارسل لنا رمز التحقق الحين وإلا بيتم حظر حسابك.",
    ],
}
ONE_HALF = [
    "Send AED 500 to this account today, thanks.",
    "Your account has a technical problem.",
    "Please reply with the code you received.",
    "This is the fraud department of your bank.",
]
LEGIT = [
    "Falcon Demo Bank: your one-time code is XXXXXX. It expires in 5 minutes. Never share it with anyone, including bank staff.",
    "رمز التحقق الخاص بك هو XXXXXX وصالح لمدة 5 دقائق. لا تشاركه مع أي شخص بمن فيهم موظفو البنك.",
    "Falcon Demo Bank: ramz el ta7aqoq howa XXXXXX. la tshariko ma3 ay 7ad.",
    "Awareness: your bank will never ask for your PIN, card number or OTP, and will never ask you to install an app.",
    "Your parcel is out for delivery today between 2 and 6 PM. Please keep your phone nearby for the courier.",
    "تذكير: موعدك في المركز الصحي غدا الساعة 10:30 صباحا. نرجو الحضور قبل 15 دقيقة مع الهوية.",
    "Reminder: your bank appointment for the new account is at 11 AM tomorrow. Please bring your passport and Emirates ID.",
    "Receipt: your bill payment of AED 230 was received on 12 Nov. Reference XXXXXX. Thank you.",
    "Hey, did you get the money I sent for the groceries? I transferred it this morning.",
]


def fired(text: str) -> list[Any]:
    ev = [from_signal(e) for e in analyze_message(text).evidence]
    res = score(ev, None, ArbiterContext(input_type="message"))
    return [r for r in res.fired_rules if r.rule_id.startswith("RF")]


@pytest.mark.parametrize(("rid", "text"), [(r, t) for r, ts in RF_CASES.items() for t in ts])
def test_rf_floor_fires_and_cites_pair_evidence(rid: str, text: str) -> None:
    pairs = [e for e in analyze_message(text).evidence if e.signal == "message.floor_pair"]
    assert any(e.hard_rule == rid for e in pairs), text
    rules = {r.rule_id: r for r in fired(text)}
    assert rid in rules and rules[rid].effect == "floor_suspicious"
    assert rules[rid].evidence_ids and set(rules[rid].evidence_ids) <= {e.id for e in pairs}


def test_rf_floor_alone_is_never_dangerous() -> None:
    p = load_params()
    p = dataclasses.replace(p, weights={**p.weights, "message.scam_intent": 0.0, "message.script_match": 0.0})
    for ts in RF_CASES.values():
        for t in ts:
            ev = [from_signal(e) for e in analyze_message(t).evidence]
            v = score(ev, None, ArbiterContext(input_type="message", params=p)).verdict
            assert v in ("suspicious", "no_warning_signs") and v != "dangerous"


@pytest.mark.parametrize("text", ONE_HALF)
def test_rf_needs_both_halves(text: str) -> None:
    assert "message.floor_pair" not in {e.signal for e in analyze_message(text).evidence}, text
    assert fired(text) == []


@pytest.mark.parametrize("text", LEGIT)
def test_rf_does_not_floor_hard_negatives(text: str) -> None:
    assert "message.floor_pair" not in {e.signal for e in analyze_message(text).evidence}, text
    assert fired(text) == []


def test_rf_protective_wording_suppresses_even_with_both_halves() -> None:
    t = "Never share your code with anyone. Your bank will never ask: do not send money to a personal account, even if told your account is blocked within 2 hours."
    assert fired(t) == []
