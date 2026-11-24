# ruff: noqa: E501
"""T-036: official-number registry and ``brand.unofficial_contact_number``.

TEST FIXTURE: the only brand used for behaviour is the invented "Falcon Demo Bank" with an invented, fixture-only
number list (hosts under .test). Real registry numbers are only checked for shape, never used as message fixtures."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from schema_helper import run_async, validate_evidence

from falcon_core.cascade.evidence import from_signal
from falcon_core.scoring import ArbiterContext, score, template_reasons
from falcon_core.scoring.params import load_params
from falcon_core.signals import REGISTRY
from falcon_core.signals.brands.contacts import (
    E164_UAE,
    extract_numbers,
    mask_number,
    number_id,
    parse_contacts,
    to_e164,
)
from falcon_core.signals.brands.registry import BrandRegistry, default_registry
from falcon_core.signals.message.analyze import analyze_message
from falcon_core.signals.message.helpline import SIGNAL, SPEC, helpline_evidence

REPO = Path(__file__).resolve().parents[5]
SRC = "https://falcon-demo-bank.test/contact"  # TEST FIXTURE host, never resolves
DEMO_OFFICIAL = "+971800000001"  # invented, fixture-only
FAKE = "800 1234 567"
FAKE_E164 = "+9718001234567"
KEY = "test-only-hmac-key-0123456789abcdefghij"  # TEST FIXTURE, not a real secret

DEMO = {
    "brand_id": "falcon_demo_bank",
    "name_en": "Falcon Demo Bank",
    "name_ar": "بنك الصقر التجريبي",
    "category": "demo",
    "verified_domains": ["falcon-demo-bank.test"],
    "keywords_en": ["falcon demo bank"],
    "keywords_ar": ["بنك الصقر", "بنك الصقر التجريبي"],
    "official_contacts": [
        {"kind": "phone", "value": DEMO_OFFICIAL, "local": "800 000001", "label_en": "Call centre (TEST FIXTURE)",
         "label_ar": "مركز الاتصال (بيانات اختبار)", "source_url": SRC, "retrieved_at": "2026-11-24"},
        {"kind": "short_code", "value": "1234", "local": "1234", "label_en": "Short code (TEST FIXTURE)",
         "label_ar": "رقم مختصر (بيانات اختبار)", "source_url": SRC, "retrieved_at": "2026-11-24"},
    ],
}  # fmt: skip
# Same invented brand, but no verified numbers: the signal must stay silent.
DEMO_NO_NUMBERS = {k: v for k, v in DEMO.items() if k != "official_contacts"}


@pytest.fixture(autouse=True)
def _no_hmac_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FL_EVIDENCE_HMAC_KEY", raising=False)  # tests set it explicitly when they need it


def reg(entry: dict[str, Any] = DEMO) -> BrandRegistry:
    return BrandRegistry.from_entries([entry])


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


def flagged(text: str, r: BrandRegistry | None = None) -> list[Any]:
    return [e for e in analyze_message(text, r or reg()).evidence if e.signal == SIGNAL]


# --- normalisation --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "800 1234 567",
        "8001234567",
        "800-1234-567",
        "+971 800 1234 567",
        "00971 800 1234567",
        "971-800-1234567",
        "٨٠٠ ١٢٣٤ ٥٦٧",
        "۸۰۰۱۲۳۴۵۶۷",
        "+971 (0)800 1234 567",
    ],
)
def test_forms_of_one_toll_free_number_normalise_to_e164(raw: str) -> None:
    assert to_e164(raw) == FAKE_E164


@pytest.mark.parametrize(
    "raw",
    ["0501234567", "050 123 4567", "+971 50 123 4567", "00971501234567", "٠٥٠١٢٣٤٥٦٧", "+٩٧١٥٠١٢٣٤٥٦٧", "971501234567"],
)
def test_mobile_forms_normalise_to_the_same_number(raw: str) -> None:
    assert to_e164(raw) == "+971501234567"


def test_shared_cost_and_landline_forms() -> None:
    assert to_e164("600 50 0000") == to_e164("+971600500000") == "+971600500000"
    assert to_e164("04 200 0000") == to_e164("+971 4 200 0000") == "+97142000000"


@pytest.mark.parametrize(
    "raw", ["", "1234", "600 500", "+44 20 7946 0000", "12345678", "0412345", "AED 1,500", "2026-11-24"]
)
def test_non_uae_or_partial_numbers_are_rejected(raw: str) -> None:
    assert to_e164(raw) is None


def test_extract_splits_adjacent_numbers_and_dedupes() -> None:
    nums = [n for n, _ in extract_numbers("call 600 50 0000 600 50 0044 or ٦٠٠٥٠٠٠٠٠ today")]
    assert nums == ["+971600500000", "+971600500044"]


def test_extract_spans_point_at_the_number() -> None:
    text = "اتصل على ٨٠٠١٢٣٤٥٦٧ الآن"
    [(n, (a, b))] = extract_numbers(text)
    assert n == FAKE_E164 and text[a:b] == "٨٠٠١٢٣٤٥٦٧"


def test_mask_never_shows_the_full_number() -> None:
    m = mask_number(FAKE_E164)
    assert m == "+971 80••••••67" and re.sub(r"\D", "", m) == "9718067"
    assert mask_number("+971501234567") == "+971 50•••••67"


# --- registry ---------------------------------------------------------------------------------------


def test_every_official_contact_in_data_brands_yaml_is_complete() -> None:
    data = yaml.safe_load((REPO / "data" / "brands.yaml").read_text(encoding="utf-8"))
    total = 0
    for entry in data["brands"]:
        for c in entry.get("official_contacts") or []:
            total += 1
            assert str(c["source_url"]).startswith("https://"), (entry["brand_id"], c)
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c["retrieved_at"])), (entry["brand_id"], c)
            if c["kind"] == "phone":
                assert E164_UAE.match(c["value"]) and to_e164(c["value"]) == c["value"], c
                assert to_e164(c["local"]) == c["value"], c  # the form shown on the page maps to the stored value
            else:
                assert c["kind"] == "short_code" and re.fullmatch(r"\d{3,5}", c["value"]), c
    assert total > 0
    assert not any(b.official_contacts for b in default_registry().brands if b.is_demo)  # fixture numbers stay in tests


@pytest.mark.parametrize(
    ("bad", "msg"),
    [
        ({"kind": "phone", "value": "800 1234 567", "source_url": SRC, "retrieved_at": "2026-11-24"}, "E.164"),
        ({"kind": "phone", "value": FAKE_E164, "retrieved_at": "2026-11-24"}, "source_url"),
        (
            {
                "kind": "phone",
                "value": FAKE_E164,
                "source_url": "http://falcon-demo-bank.test/",
                "retrieved_at": "2026-11-24",
            },
            "source_url",
        ),
        ({"kind": "phone", "value": FAKE_E164, "source_url": SRC}, "retrieved_at"),
        ({"kind": "fax", "value": FAKE_E164, "source_url": SRC, "retrieved_at": "2026-11-24"}, "kind"),
        ({"kind": "short_code", "value": "12", "source_url": SRC, "retrieved_at": "2026-11-24"}, "short_code"),
    ],
)
def test_incomplete_entries_do_not_load(bad: dict[str, str], msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        parse_contacts("falcon_demo_bank", [bad])
    with pytest.raises(ValueError):
        BrandRegistry.from_entries([{**DEMO, "official_contacts": [bad]}])


def test_registry_maps_numbers_to_brands() -> None:
    r = reg()
    assert r.number_brands(DEMO_OFFICIAL) == ["falcon_demo_bank"]
    assert r.number_brands(FAKE_E164) == []
    assert r.number_brands("1234") == []  # short codes are listed but never matched as phone numbers


# --- evidence ------------------------------------------------------------------------------------------


def test_fake_number_claiming_the_bank_is_flagged_once_masked() -> None:
    text = f"Falcon Demo Bank: your card is blocked. Call our helpline {FAKE} now."
    [ev] = flagged(text)
    validate_evidence([ev])
    assert ev.family == "brand" and ev.polarity == "risk" and ev.tier == "T1" and ev.weight == 0.0
    assert ev.observed == {
        "brands": ["falcon_demo_bank"],
        "numbers": [{"masked": "+971 80••••••67"}],
        "count": 1,
    }
    blob = json.dumps(ev.to_dict(), ensure_ascii=False)
    assert "1234567" not in blob and "8001234" not in blob and FAKE not in blob
    assert ev.display and ev.display["en"] and re.search(r"[؀-ۿ]", ev.display["ar"])


def test_arabic_message_with_arabic_indic_digits_is_flagged() -> None:
    [ev] = flagged("بنك الصقر التجريبي: تم إيقاف بطاقتك. اتصل بخدمة العملاء على ٨٠٠ ١٢٣٤ ٥٦٧")
    assert ev.observed["numbers"][0]["masked"] == "+971 80••••••67"


@pytest.mark.parametrize("form", ["+971 800 1234 567", "00971-800-1234567", "٨٠٠١٢٣٤٥٦٧", "800.1234.567"])
def test_every_written_form_gives_the_same_keyed_id(form: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_EVIDENCE_HMAC_KEY", KEY)
    [ev] = flagged(f"Falcon Demo Bank support: {form}")
    assert ev.observed["numbers"][0] == {"masked": "+971 80••••••67", "id": number_id(FAKE_E164, KEY)}


def test_mobile_number_with_brand_is_flagged() -> None:
    [ev] = flagged("بنك الصقر: للتحقق من حسابك تواصل واتساب ٠٥٠ ١٢٣ ٤٥٦٧")
    assert ev.observed["numbers"][0]["masked"] == "+971 50•••••67"


@pytest.mark.parametrize("form", ["800 000001", "+971800000001", "٨٠٠٠٠٠٠٠١", "00971 800 000 001"])
def test_official_number_emits_nothing(form: str) -> None:
    assert flagged(f"Falcon Demo Bank: call us on {form}") == []


def test_official_and_fake_together_flags_only_the_fake() -> None:
    [ev] = flagged(f"Falcon Demo Bank: 800 000001 is busy, call {FAKE} instead")
    assert ev.observed["count"] == 1 and ev.observed["numbers"][0]["masked"] == "+971 80••••••67"


def test_number_without_a_brand_emits_nothing() -> None:
    assert flagged(f"Your parcel is waiting. Call {FAKE} to reschedule.") == []
    assert flagged("اتصل على ٨٠٠١٢٣٤٥٦٧ لاستلام الجائزة") == []


def test_brand_without_verified_numbers_emits_nothing() -> None:
    assert flagged(f"Falcon Demo Bank: call {FAKE}", reg(DEMO_NO_NUMBERS)) == []


def test_brand_without_a_number_emits_nothing() -> None:
    assert flagged("Falcon Demo Bank: your statement is ready.") == []
    assert flagged("Falcon Demo Bank: pay AED 600 500 by 24-11-2026, ref 12345678") == []


def test_number_official_for_another_brand_is_not_flagged() -> None:
    other = {
        "brand_id": "falcon_demo_post", "name_en": "Falcon Demo Post", "name_ar": "بريد الصقر التجريبي",
        "category": "demo", "verified_domains": ["falcon-demo-post.test"], "keywords_en": ["falcon demo post"],
        "official_contacts": [{"kind": "phone", "value": FAKE_E164, "source_url": "https://falcon-demo-post.test/c",
                               "retrieved_at": "2026-11-24"}],
    }  # fmt: skip
    r = BrandRegistry.from_entries([DEMO, other])
    assert flagged(f"Falcon Demo Bank: or call {FAKE}", r) == []


def test_confusable_brand_spelling_is_matched_like_brand_mention() -> None:
    text = f"FALCON-DEMO-BANK alert: call {FAKE}"
    ev = analyze_message(text, reg()).evidence
    assert any(e.signal == "message.brand_mention" for e in ev)
    assert any(e.signal == SIGNAL for e in ev)


def test_many_numbers_are_capped_and_counted() -> None:
    text = "Falcon Demo Bank: " + " / ".join(f"050 000 00{i:02d}" for i in range(8))
    [ev] = flagged(text)
    assert ev.observed["count"] == 8 and len(ev.observed["numbers"]) == 5


def test_page_text_tier_is_passed_through() -> None:
    [ev] = helpline_evidence(f"Falcon Demo Bank customer care {FAKE}", reg(), tier="T2")
    assert ev.tier == "T2"


def test_no_full_number_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    analyze_message(f"Falcon Demo Bank: call {FAKE} / ٨٠٠١٢٣٤٥٦٧", reg())
    assert "1234567" not in caplog.text and "١٢٣٤٥٦٧" not in caplog.text


# --- registration, timeout, scoring ----------------------------------------------------------------------


def test_registered_with_declared_names_and_budget() -> None:
    spec, run = REGISTRY["brand.contact_number"]
    assert spec is SPEC and spec.network == "none" and spec.timeout_ms <= 100 and spec.family == "brand"
    out = run_async(run(Ctx(text=f"Falcon Demo Bank: call {FAKE}", brands=reg())))
    assert [e.signal for e in out] == [SIGNAL] and out[0].error is None and out[0].latency_ms is not None
    assert {e.signal for e in out} <= set(spec.emits)
    assert run_async(run(Ctx(text=None, brands=reg()))) == []


def test_long_input_stays_within_budget() -> None:
    import time

    text = "Falcon Demo Bank " + ("050 000 0000 " * 20_000)
    t0 = time.perf_counter()
    helpline_evidence(text, reg())
    assert time.perf_counter() - t0 < 1.0


def test_weight_zero_leaves_the_arbiter_output_unchanged() -> None:
    assert SIGNAL not in load_params().weights  # shipped at weight 0: params.yaml is written only by the fit
    [sig] = flagged(f"Falcon Demo Bank: call {FAKE}")
    new = from_signal(sig)
    ctx = ArbiterContext(input_type="message")
    without = score([], 0.4, ctx)
    with_ = score([new], 0.4, ctx)
    assert with_.calibrated_probability == without.calibrated_probability
    assert with_.verdict == without.verdict and with_.fired_rules == without.fired_rules
    assert with_.weighted_evidence[0].weight == 0.0
    assert template_reasons(with_, "en") == template_reasons(without, "en")


# --- privacy: no bare hash, keyed id only with a configured key ---------------------------------------------


def test_no_bare_hash_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FL_EVIDENCE_HMAC_KEY", raising=False)
    [ev] = flagged(f"Falcon Demo Bank: call {FAKE}")
    assert ev.observed["numbers"] == [{"masked": "+971 80••••••67"}]
    blob = json.dumps(ev.to_dict(), ensure_ascii=False)
    for h in (hashlib.sha256, hashlib.sha1, hashlib.md5):
        for form in (FAKE_E164, FAKE_E164[1:], "8001234567", FAKE):
            assert h(form.encode()).hexdigest()[:16] not in blob


def test_keyed_id_is_hmac_and_depends_on_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import hmac

    a = number_id(FAKE_E164, KEY)
    assert a == "hm_" + hmac.new(KEY.encode(), FAKE_E164.encode(), hashlib.sha256).hexdigest()[:32]
    assert a != number_id(FAKE_E164, KEY + "x")
    assert hashlib.sha256(FAKE_E164.encode()).hexdigest()[:32] not in str(a)
    assert number_id(FAKE_E164, "short") is None  # a weak key is ignored, never used
    monkeypatch.setenv("FL_EVIDENCE_HMAC_KEY", KEY)
    [ev] = flagged(f"Falcon Demo Bank: call {FAKE}")
    assert ev.observed["numbers"][0]["id"] == a
    assert "1234567" not in json.dumps(ev.to_dict(), ensure_ascii=False)
