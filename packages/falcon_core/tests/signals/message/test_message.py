# ruff: noqa: E501
"""Message pipeline: normalisation, rules (AR Gulf/MSA, EN, Arabizi), extraction, brand mentions.
Fixtures use only the invented brand Falcon Demo Bank, example.test links and placeholder numbers."""

from dataclasses import dataclass
from typing import Any

import pytest
from schema_helper import run_async, validate_evidence

from falcon_core.signals import REGISTRY
from falcon_core.signals.message.analyze import analyze_message
from falcon_core.signals.message.extract import extract_phones, extract_urls
from falcon_core.signals.message.normalize import arabizi_fold, normalize
from falcon_core.signals.message.rules import find_rules


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


def rules(text: str) -> set[str]:
    return {h.rule for h in find_rules(text)}


def test_normalize_variants_digits_tatweel() -> None:
    n = normalize("إِدفَـع ٥٠ درهـم، أُلغِيَت المؤسّسة ة ى")
    assert "ادفع" in n.text and "50" in n.text and "ـ" not in n.text
    assert normalize("مدرسة").text == normalize("مدرسه").text  # taa marbuta
    assert normalize("على").text == normalize("علي").text  # alef maqsura / yaa
    assert normalize("أحمد إبراهيم آدم").text == "احمد ابراهيم ادم"
    assert normalize("هلااااا").text == "هلاا"  # elongation
    assert normalize("۱۲۳").text == "123"  # Persian-Indic digits


def test_index_map_points_into_original() -> None:
    text = "  عَاجِل جدا"
    n = normalize(text)
    s = n.text.index("عاجل")
    a, b = n.original_span(s, s + 4, len(text))
    assert text[a:b].startswith("عَ") and text[a:b].endswith("ل")


def test_arabizi_fold_only_mixed_tokens() -> None:
    assert arabizi_fold("3ajil") == "aajil"
    assert arabizi_fold("7esab 2024") == "hesab 2024"  # standalone numbers untouched
    assert arabizi_fold("5") == "5"


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("عاجل: سيتم ايقاف حسابك خلال 24 ساعة", "urgency"),
        ("لازم تسوي الحين وإلا بيتم تعليق الخدمة", "urgency"),
        ("لا تخبر أحدا بهذه المكالمة", "secrecy"),
        ("لا تقول لأحد أبدا", "secrecy"),
        ("Please do not tell anyone about this", "secrecy"),
        ("ارسل لنا رمز التحقق الذي وصلك", "otp_request"),
        ("Share the code you received (OTP)", "otp_request"),
        ("حمل تطبيق AnyDesk وأعطنا الرقم", "remote_access"),
        ("Install TeamViewer QuickSupport now", "remote_access"),
        ("قم بالدفع عبر الرابط وحدث بيانات البطاقة", "payment"),
        ("This is Dubai Police cyber crime unit", "authority"),
        ("معك قسم الاحتيال في البنك", "authority"),
        ("مبروك! فزت بجائزة قدرها مليون درهم", "prize"),
        ("Congratulations, you have won a prize", "prize"),
        ("فرصة عمل من المنزل براتب عالي", "job"),
        ("We are hiring, work from home, salary 5000", "job"),
        ("استثمر معنا ارباح يومية مضمونة تداول عملات رقمية", "investment"),
        ("Guaranteed profit with our trading platform", "investment"),
        ("تعذر توصيل شحنتك، ادفع رسوم التوصيل", "delivery_fee"),
        ("Your parcel is held, pay customs fees", "delivery_fee"),
        ("لديك مخالفة مرورية غير مسددة", "fine"),
        ("You have an unpaid traffic fine", "fine"),
    ],
)
def test_rule_positive(text: str, rule: str) -> None:
    assert rule in rules(text)


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("ana 3ndi mokhalafa mrorya", "fine"),
        ("3ajil ya sa7bi", "urgency"),
        ("irsil el ramz? ersel el code", "otp_request"),
        ("nazzel barnameg any desk", "remote_access"),
        ("la t2ol l a7ad", "secrecy"),
        ("mabrook rabe7t jaeza", "prize"),
        ("7awel el flos", "payment"),
        ("arba7 istithmar", "investment"),
        ("wazifa bi raatib", "job"),
    ],
)
def test_rule_arabizi(text: str, rule: str) -> None:
    assert rule in rules(text)


@pytest.mark.parametrize(
    "text",
    [
        "مرحبا، كيف حالك؟ نلتقي غدا على الغداء",
        "See you at lunch tomorrow, I'm fine thanks",
        "الاجتماع الساعة الخامسة مساء",
        "",
        "tard",  # one half of the delivery pair is not enough
        "رسوم الجامعة",  # fee word without a parcel word
    ],
)
def test_benign_text_has_no_rules(text: str) -> None:
    assert rules(text) == set()


def test_spans_are_offsets_not_text() -> None:
    text = "عاجل جدا: ادفع الان"
    ev = [e for e in analyze_message(text).evidence if e.signal == "message.rule.urgency"][0]
    assert ev.observed["spans"][0] == [0, 4]
    assert "عاجل" not in str(ev.observed)  # raw text never in evidence
    assert all(0 <= a < b <= len(text) for a, b in ev.observed["spans"])


def test_h6_flag_otp_plus_authority() -> None:
    res = analyze_message("هنا شرطة ابوظبي. ارسل رمز التحقق الان")
    flagged = {e.signal for e in res.evidence if e.hard_rule == "H6"}
    assert flagged == {"message.rule.otp_request"}
    plain = analyze_message("Send the OTP code to me")
    assert not any(e.hard_rule for e in plain.evidence)


def test_all_evidence_validates_against_schema() -> None:
    res = analyze_message(
        "عاجل شرطة ابوظبي ارسل رمز التحقق hxxps://falcon-demo[.]test/x 0500000000 بنك الصقر"
    )
    assert res.evidence
    validate_evidence(res.evidence)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hxxps://pay.example[.]test/a?b=1", "https://pay.example.test/a?b=1"),
        ("hxxp://example(.)test/x", "http://example.test/x"),
        ("visit example[dot]test now", "example.test"),
        ("go to example . test/pay today", "example.test/pay"),
        ("زوروا www.example.test/ar، شكرا", "www.example.test/ar"),
        ("اضغط https://example.test/pay.", "https://example.test/pay"),
        ("hxxps[:]//example[.]test", "https://example.test"),
        ("ادخل falcon-demo.test/login", "falcon-demo.test/login"),
    ],
)
def test_url_extraction(text: str, expected: str) -> None:
    assert expected in [u.value for u in extract_urls(text)]


def test_url_extraction_ignores_plain_prose() -> None:
    assert extract_urls("e.g. this is fine. Next sentence, file.txt and 3.5 stars") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("اتصل على +971 50 000 0000", "+971500000000"),
        ("call 050-000-0000", "+971500000000"),
        ("00971500000000", "+971500000000"),
        ("اتصل ٠٥٠ ٠٠٠ ٠٠٠٠", "+971500000000"),
        ("tel 04 000 0000", "+97140000000"),
        ("800 0000", "8000000"),
    ],
)
def test_phone_extraction(text: str, expected: str) -> None:
    assert expected in [p.value for p in extract_phones(text)]


def test_phone_rejects_non_uae_and_masks_in_evidence() -> None:
    assert extract_phones("+44 20 0000 0000 or 12345678") == []
    ev = analyze_message("call 0500000000").evidence
    obs = next(e for e in ev if e.signal == "message.contains_phone").observed
    assert "0500000000" not in str(obs) and "***" in obs["phones"][0]


def test_children_are_returned_for_url_pipeline() -> None:
    res = analyze_message("pay at hxxps://example[.]test/p or 0500000000")
    kinds = {(c.kind, c.value) for c in res.children}
    assert ("url", "https://example.test/p") in kinds and ("phone", "+971500000000") in kinds


def test_brand_mention_and_url_mismatch() -> None:
    res = analyze_message("Falcon Demo Bank: verify at https://falcon-demo-bank.example.test/login")
    names = {e.signal for e in res.evidence}
    assert "message.brand_mention" in names and "message.brand_url_mismatch" in names
    ok = analyze_message("بنك الصقر التجريبي يدعوكم https://falcon-demo-bank.test/")
    assert "message.brand_mention" in {e.signal for e in ok.evidence}
    assert "message.brand_url_mismatch" not in {e.signal for e in ok.evidence}
    assert not [
        e for e in analyze_message("hello there").evidence if e.signal.startswith("message.brand")
    ]


def test_registered_signals_run_async() -> None:
    for name in ("message.rules", "message.children", "message.brand_mention"):
        spec, fn = REGISTRY[name]
        assert spec.network == "none" and spec.timeout_ms > 0
        out = run_async(fn(Ctx(text="عاجل ارسل رمز التحقق Falcon Demo Bank example.test")))
        assert all(e.error is None for e in out)
    out = run_async(REGISTRY["message.rules"][1](Ctx(text="urgent: pay now")))
    assert {e.signal for e in out} >= {"message.rule.urgency", "message.rule.payment"}


def test_oversized_message_is_truncated_not_crashing() -> None:
    res = analyze_message("عاجل " * 5000)
    assert res.truncated
    assert any(e.signal == "message.rule.urgency" for e in res.evidence)
