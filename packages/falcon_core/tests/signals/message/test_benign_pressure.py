"""PR-88 review fixes: pressure words alone never warn; message wording alone never reaches `dangerous`."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest

from evals.message_text.run import verdict
from falcon_core.cascade.evidence import from_signal
from falcon_core.scoring.arbiter import ArbiterContext, score
from falcon_core.scoring.params import load_params
from falcon_core.signals.base import Evidence
from falcon_core.signals.message.analyze import analyze_message
from falcon_core.signals.message.intent import scam_intent

FAMILY = [
    "يبا وين صرت؟ العشا جاهز، تعال بسرعة قبل لا يبرد",
    "هلا والله، شحالك؟ بكرة عزيمة عند يدوه بعد صلاة المغرب، لا تتأخر",
    "الحين وصلت المطار، الرحلة تأخرت ساعتين، لا تشيل هم",
]
BENIGN = [
    "Hurry up, we're late for the flight.",
    "Don't be late, dinner is at eight.",
    "Our branches will be closed for the holiday and reopen on Sunday.",
    "Reminder: your appointment is tomorrow at 10 AM, please arrive early.",
    "Your code is 123456. Never share it with anyone, including bank staff.",
    "Falcon Demo Bank: your parcel will arrive today between 2 and 4 PM.",
    "تذكير بموعدك بكرة الساعة عشرة، يرجى عدم التأخر",
    "رمز التحقق 123456، لا تشاركه مع أحد",
    "تعال بسرعة، الجماعة ينتظرونك",
    "لا تتأخر على الدوام بكرة",
    "الحين وصلت البيت",
    "الفرع مغلق بمناسبة العطلة الرسمية",
    "Come quickly, the cake is being cut now!",
    "Last chance to sign up for the football night, space is limited.",
    "Late returns may carry a small fee, please return books by Friday.",
    "yalla ta3al besor3a el 3asha jaheez",
    "Parking is not allowed here this weekend; vehicles may be moved.",
    "We are closing early today, see you tomorrow at nine.",
    "عذرا على التأخير، وصلت الآن",
    "Please do not be late for the meeting at 9 AM.",
]
EML = Path(__file__).resolve().parents[5] / "evals/datasets/emails/legit_08_en_holiday_hours.eml"


@pytest.mark.parametrize("text", [*FAMILY, *BENIGN])
def test_benign_pressure_text_is_no_warning_signs(text: str) -> None:
    assert verdict(text) == "no_warning_signs"


def test_lone_pressure_features_give_no_intent_evidence() -> None:
    for t in ("Hurry up, you must come immediately or you will be fined", "تعال بسرعة وإلا ستتأخر"):
        assert scam_intent(t) == []


def test_holiday_hours_fixture_is_no_warning_signs() -> None:
    msg = BytesParser(policy=policy.default).parsebytes(EML.read_bytes())
    body = msg.get_body(preferencelist=("plain",))
    assert body is not None
    text = f"{msg['Subject']}\n{body.get_content()}"
    assert verdict(text) == "no_warning_signs"


def test_scam_intent_alone_never_dangerous() -> None:
    ev = [
        Evidence(signal="message.scam_intent", family="message", confidence=0.99, observed={"p": 0.99, "features": []}),
        Evidence(signal="message.script_match", family="message", confidence=0.99, observed={}),
    ]
    ctx = ArbiterContext(input_type="message", params=load_params())
    r = score([from_signal(e) for e in ev], None, ctx)
    assert r.verdict != "dangerous"


def test_scam_text_still_warns() -> None:
    t = "Falcon Demo Bank security: send us the 6-digit code you just received immediately or your card will be blocked."
    assert verdict(t) != "no_warning_signs"
    assert any(e.signal == "message.scam_intent" for e in analyze_message(t).evidence)
