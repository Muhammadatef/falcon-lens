# ruff: noqa: E501
"""message.scam_intent and the offline message.script_match: link-free scam texts in Arabic (MSA, Gulf), Arabizi and
English, hard negatives, confusable spellings, no-weights behaviour. Invented brand and numbers only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from schema_helper import run_async, validate_evidence

from falcon_core.cascade.evidence import from_signal
from falcon_core.scoring.arbiter import ArbiterContext, score
from falcon_core.signals import REGISTRY
from falcon_core.signals.message import intent
from falcon_core.signals.message.analyze import analyze_message
from falcon_core.signals.message.scripts import LocalScriptIndex, script_match_offline


@dataclass
class Ctx:
    text: str | None = None
    url: str | None = None
    input_type: str = "message"
    http: Any = None
    cache: Any = None
    mirror: Any = None
    clock: Any = None
    brands: Any = None


def verdict(text: str) -> str:
    ev = [from_signal(e) for e in analyze_message(text).evidence]
    return str(score(ev, None, ArbiterContext(input_type="message")).verdict)


SCAMS = [
    "Falcon Demo Bank security: we blocked a payment on your card. Reply with the 6-digit code you just received to cancel it.",
    "من فريق أمن بنك الصقر التجريبي: لإلغاء العملية المشبوهة يرجى تزويدنا برمز التحقق المرسل إلى هاتفك.",
    "جهازك فيه فايروس يهدد حسابك البنكي. نزّل البرنامج اللي بنرسله لك عشان نتحكم بالجهاز ونصلحه.",
    "Falcon Demo Bank: fi 7araka ghalat 3ala hesabak, ersel lena el code elli wasalak halhin 3shan nwaqqfha.",
    "Congratulations! You won AED 100,000 in our lucky draw. To release the prize send AED 500 processing fee and a copy of your ID.",
    "مبروك فزت بسيارة في السحب! عشان تستلمها دفع رسوم التسجيل 1000 درهم وارسل صورة الهوية.",
    "Buy 4 gift cards of AED 500 each and send me the codes by message. It is urgent, I cannot talk now.",
    "حسابك انوقف! اتصل بنا على 0500000000 الحين عشان نرجعه.",
]
LEGIT = [
    "Falcon Demo Bank: your one-time code is XXXXXX. It expires in 5 minutes. Never share it with anyone, including bank staff.",
    "رمز التحقق الخاص بك هو XXXXXX وصالح لمدة 5 دقائق. لا تشاركه مع أي شخص بمن فيهم موظفو البنك.",
    "Falcon Demo Bank: ramz el ta7aqoq howa XXXXXX. la tshariko ma3 ay 7ad.",
    "Awareness: your bank will never ask for your PIN, card number or OTP, and will never ask you to install an app.",
    "Your parcel is out for delivery today between 2 and 6 PM. Please keep your phone nearby for the courier.",
    "تذكير: موعدك في المركز الصحي غدا الساعة 10:30 صباحا. نرجو الحضور قبل 15 دقيقة مع الهوية.",
    "Hey, are we still on for dinner tonight? I can pick you up at 8 if you want.",
    "Receipt: your bill payment of AED 230 was received on 12 Nov. Reference XXXXXX. Thank you.",
]


@pytest.mark.parametrize("text", SCAMS)
def test_link_free_scams_get_scam_intent(text: str) -> None:
    names = {e.signal for e in analyze_message(text).evidence}
    assert "message.scam_intent" in names, text
    assert verdict(text) != "no_warning_signs"


@pytest.mark.parametrize("text", LEGIT)
def test_hard_negatives_get_no_scam_intent(text: str) -> None:
    names = {e.signal for e in analyze_message(text).evidence}
    assert "message.scam_intent" not in names, text
    assert verdict(text) == "no_warning_signs"


def test_confusable_spellings_still_match() -> None:
    # tatweel + diacritics + Arabic-Indic digits + alef variants in an OTP ask
    t = "من فريق أمـــن بنك الصقر: يرجى تزويدنا بـرَمز التحقق المرسل إلى هاتفك. ٦ أرقام"
    assert "message.scam_intent" in {e.signal for e in analyze_message(t).evidence}


def test_evidence_validates_and_carries_no_text() -> None:
    text = SCAMS[0]
    (ev,) = [e for e in analyze_message(text).evidence if e.signal == "message.scam_intent"]
    validate_evidence([ev])
    blob = str(ev.to_dict())
    assert "6-digit" not in blob and "Falcon" not in blob
    assert 0.65 <= ev.confidence <= 1.0
    assert "otp_request" in ev.observed["features"]


def test_registered_runner_and_timeout_budget() -> None:
    spec, run = REGISTRY["message.scam_intent"]
    assert spec.network == "none" and spec.timeout_ms <= 100
    out = run_async(run(Ctx(text=SCAMS[0])))
    assert out and out[0].signal == "message.scam_intent" and out[0].error is None
    assert run_async(run(Ctx(text=""))) == []


def test_missing_weights_means_no_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent, "load_weights", lambda: None)
    assert intent.scam_intent(SCAMS[0]) == []


def test_protective_features_lower_probability() -> None:
    model = intent.load_weights()
    assert model is not None
    base = intent.extract_features("Reply with the code you received. Falcon Demo Bank security.")
    safe = dict(base) | {"warning_never_share": 1}
    assert intent.probability(safe, model) < intent.probability(base, model)


def test_offline_script_match_fires_on_near_copy_not_on_unrelated() -> None:
    rows = [{"id": "s1", "label": "otp_request", "text": SCAMS[0]}]
    idx = LocalScriptIndex(rows)
    (hit,) = script_match_offline(SCAMS[0].replace("6-digit", "six digit"), idx, theta=0.6)
    assert hit.signal == "message.script_match" and hit.observed["matches"][0]["id"] == "s1"
    validate_evidence([hit])
    assert script_match_offline(LEGIT[6], idx, theta=0.6) == []
    assert script_match_offline("", idx, theta=0.1) == []


def test_script_match_appears_in_the_message_path() -> None:
    from falcon_core.signals.message.scripts import default_index

    idx = default_index()
    assert idx is not None and idx.rows, "scam_scripts.jsonl must ship"
    rid, _lab, _g = idx.rows[0]
    row = next(r for r in __import__("evals.message_text.data", fromlist=["x"]).load_all() if r["id"] == rid)
    assert "message.script_match" in {e.signal for e in analyze_message(row["text"]).evidence}


def test_words_inside_a_link_are_not_message_wording() -> None:
    t = "Have a look at this page when you have a moment hxxps://pay-gift-cards-telegram[.]test/1234567890123/call-now"
    assert intent.extract_features(t) == {}
    assert "message.scam_intent" not in {e.signal for e in analyze_message(t).evidence}
