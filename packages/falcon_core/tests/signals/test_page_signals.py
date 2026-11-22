from __future__ import annotations

from typing import Any

import pytest

from falcon_core.signals.page.build import (
    build_forms,
    build_static_post_targets,
    js_obfuscation_indicators,
    truncate_utf8,
)
from falcon_core.signals.page.classify import FieldKind, classify_field
from falcon_core.signals.page.cloaking import compare_profiles
from falcon_core.signals.page.evidence import build_page_evidence
from falcon_core.signals.page.exfil import classify_post_target
from falcon_core.signals.page.features import (
    Cloaking,
    Favicon,
    JsIndicators,
    ProfileFeatures,
    RenderFeatures,
)
from falcon_core.signals.page.hosts import registrable_domain
from falcon_core.signals.page.simhash import dom_simhash, hamming_hex
from falcon_core.signals.visual import FIXTURE_BRAND, hamming64, phash_from_gray32
from falcon_core.signals.visual.brands import BrandRef

K = FieldKind


@pytest.mark.parametrize(
    ("desc", "kind"),
    [
        ({"type": "password", "name": "pw"}, K.PASSWORD),
        ({"type": "text", "label": "كلمة المرور"}, K.PASSWORD),
        ({"type": "text", "placeholder": "الرقم السري"}, K.PASSWORD),
        ({"type": "text", "name": "cardNumber"}, K.CARD),
        ({"type": "text", "autocomplete": "cc-number"}, K.CARD),
        ({"type": "text", "label": "رقم البطاقة"}, K.CARD),
        ({"type": "text", "label": "تاريخ الانتهاء"}, K.CARD),
        ({"type": "password", "name": "cvv"}, K.CVV),
        ({"type": "text", "label": "رمز الأمان"}, K.CVV),
        ({"type": "text", "autocomplete": "cc-csc"}, K.CVV),
        ({"type": "text", "name": "otp_code"}, K.OTP),
        ({"type": "text", "autocomplete": "one-time-code"}, K.OTP),
        ({"type": "text", "label": "رمز التحقق المرسل إلى جوالك"}, K.OTP),
        ({"type": "text", "label": "كود التحقق"}, K.OTP),
        ({"type": "text", "inputmode": "numeric", "maxlength": 6}, K.OTP),
        ({"type": "text", "name": "emirates_id"}, K.EMIRATES_ID),
        ({"type": "text", "label": "رقم الهوية الإماراتية"}, K.EMIRATES_ID),
        ({"type": "text", "placeholder": "784-XXXX-XXXXXXX-X"}, K.EMIRATES_ID),
        ({"type": "text", "name": "uaepass_user"}, K.UAE_PASS),
        ({"type": "text", "label": "UAE PASS"}, K.UAE_PASS),
        ({"type": "text", "label": "الهوية الرقمية"}, K.UAE_PASS),
        ({"type": "email"}, K.EMAIL),
        ({"type": "text", "label": "اسم المستخدم"}, K.USERNAME),
        ({"type": "tel"}, K.PHONE),
        ({"type": "hidden", "name": "password"}, K.OTHER),
        ({"type": "text", "name": "q", "placeholder": "Search"}, K.OTHER),
    ],
)
def test_classify_field(desc: dict[str, object], kind: FieldKind) -> None:
    assert classify_field(desc) == kind


def test_arabic_diacritics_and_alef_variants() -> None:
    assert classify_field({"type": "text", "label": "كَلِمَةُ الْمُرُورِ"}) == K.PASSWORD
    assert classify_field({"type": "text", "label": "رمز الامان"}) == K.CVV
    assert classify_field({"type": "text", "label": "الهويّة الإماراتيّة"}) in (
        K.EMIRATES_ID,
        K.OTHER,
    )


@pytest.mark.parametrize(
    ("url", "category"),
    [
        ("https://api.telegram.org/bot123456:ABCdef/sendMessage", "messaging_bot_api"),
        ("http://falcon-bot-relay.test/bot123456:FAKE/sendMessage", "messaging_bot_api"),
        ("https://discord.com/api/webhooks/123/abc", "webhook"),
        ("https://hooks.slack.com/services/T0/B0/xyz", "webhook"),
        ("https://formspree.io/f/abcd", "form_relay"),
        ("https://webhook.site/uuid", "webhook"),
    ],
)
def test_exfil_targets(url: str, category: str) -> None:
    c = classify_post_target(url)
    assert c.exfil and c.category == category


def test_non_exfil_targets() -> None:
    assert not classify_post_target("https://www.google-analytics.com/collect").exfil
    assert not classify_post_target("https://bank.example.com/login").exfil


def _form(action: str, fields: list[dict[str, object]]) -> dict[str, object]:
    return {"action": action, "method": "post", "fields": fields}


PW: dict[str, object] = {"type": "password", "name": "password"}
USER: dict[str, object] = {"type": "text", "name": "username"}


def test_build_forms_flags_cross_origin_and_exfil() -> None:
    forms = build_forms(
        [_form("http://falcon-bot-relay.test/bot123456:FAKE/sendMessage", [USER, PW])],
        "http://falcon-demo-bank-secure.test/login",
    )
    f = forms[0]
    assert f.cred_form and f.action_cross_origin and f.action_exfil
    assert f.sensitive_kinds == ["password"]


def test_build_forms_same_origin_search_is_not_cred() -> None:
    forms = build_forms(
        [_form("http://x.test/search", [{"type": "text", "name": "q"}])], "http://x.test/"
    )
    assert not forms[0].cred_form and not forms[0].action_cross_origin


def test_static_post_targets() -> None:
    t = build_static_post_targets(
        [{"kind": "fetch", "url": "http://falcon-bot-relay.test/bot123456:FAKE/sendMessage"}],
        ["https://cdn.example.com/lib.js", "https://discord.com/api/webhooks/1/x"],
        "http://phish.test/",
    )
    assert [x.exfil for x in t] == [True, True]
    assert t[1].kind == "script_literal"


def test_truncate_utf8_never_splits_characters() -> None:
    s = truncate_utf8("مرحبا " * 2000)
    assert len(s.encode()) <= 4096
    s.encode()  # valid


def test_js_indicators() -> None:
    assert js_obfuscation_indicators(JsIndicators()) == []
    ind = js_obfuscation_indicators(JsIndicators(eval_calls=1, atob_calls=1, contextmenu_block=1))
    assert "eval_of_decoded" in ind and "block_contextmenu" in ind


def test_simhash_structure_only() -> None:
    a = dom_simhash(["1:div", "html>div", "2:form", "div>form"] * 3)
    assert a == dom_simhash(["1:div", "html>div", "2:form", "div>form"] * 3)
    assert hamming_hex(a, a) == 0
    other = dom_simhash([f"{i}:section" for i in range(40)])
    assert hamming_hex(a, other) > 10


def test_phash_stable_and_discriminates() -> None:
    grad = [
        [200.0 if 6 <= x < 20 and 4 <= y < 14 else (60.0 if y > 20 else 120.0) for x in range(32)]
        for y in range(32)
    ]
    checker = [[255.0 if (x // 4 + y // 4) % 2 else 0.0 for x in range(32)] for y in range(32)]
    assert phash_from_gray32(grad) == phash_from_gray32(grad)
    noisy = [
        [v + (1 if (x + y) % 7 == 0 else 0) for x, v in enumerate(r)] for y, r in enumerate(grad)
    ]
    assert hamming64(phash_from_gray32(grad), phash_from_gray32(noisy)) <= 4
    assert hamming64(phash_from_gray32(grad), phash_from_gray32(checker)) > 10
    with pytest.raises(ValueError):
        phash_from_gray32([[0.0] * 3])


def test_registrable_domain() -> None:
    assert registrable_domain("login.adpolice.gov.ae") == "adpolice.gov.ae"
    assert registrable_domain("a.b.falcon-demo-bank.test") == "falcon-demo-bank.test"


# ------------------------------------------------------------------ evidence + cloaking


def _profile(
    name: str = "desktop_en",
    url: str = "http://falcon-demo-bank-secure.test/login",
    **kw: Any,
) -> ProfileFeatures:
    return ProfileFeatures.model_validate(
        {"profile": name, "requested_url": url, "final_url": url, "status": 200, **kw}
    )


def _phish_profile(name: str = "mobile_ar") -> ProfileFeatures:
    forms = build_forms(
        [_form("http://falcon-bot-relay.test/bot123456:FAKE/sendMessage", [USER, PW])],
        "http://falcon-demo-bank-secure.test/login",
    )
    return _profile(
        name,
        title="Falcon Demo Bank - Secure Login",
        forms=forms,
        asset_origins=["falcon-demo-bank.test"],
        favicon=Favicon(sha256="a" * 64, phash="00ff00ff00ff00ff"),
        js=JsIndicators(eval_calls=1, atob_calls=1),
        visible_text="Falcon Demo Bank secure login",
    )


def _signals(ev: list) -> set[str]:  # type: ignore[type-arg]
    return {e.signal for e in ev}


def test_phish_evidence_and_hard_rules() -> None:
    brand = BrandRef(
        **{
            **FIXTURE_BRAND.__dict__,
            "favicon_sha256": ("a" * 64,),
            "favicon_phash": ("00ff00ff00ff00ff",),
        }
    )
    feats = RenderFeatures(url="x", profiles={"mobile_ar": _phish_profile()})
    ev = build_page_evidence(feats, [brand])
    assert _signals(ev) == {
        "page.cred_form",
        "page.cross_origin_post",
        "page.hotlinked_brand_assets",
        "page.js_obfuscation",
        "visual.favicon_match_brand",
        "brand.claimed_not_owned",
    }
    by = {e.signal: e for e in ev}
    assert by["page.cross_origin_post"].hard_rule == "H4"
    assert by["brand.claimed_not_owned"].hard_rule == "H1"
    assert by["visual.favicon_match_brand"].polarity == "risk"
    assert all(e.weight == 0 and e.source == "sandbox" for e in ev)


def test_official_site_yields_no_page_evidence() -> None:
    url = "http://falcon-demo-bank.test/"
    p = _profile(
        "desktop_en",
        url,
        title="Falcon Demo Bank",
        favicon=Favicon(sha256="a" * 64),
        visible_text="Falcon Demo Bank welcome",
    )
    brand = BrandRef(**{**FIXTURE_BRAND.__dict__, "favicon_sha256": ("a" * 64,)})
    ev = build_page_evidence(RenderFeatures(url=url, profiles={"desktop_en": p}), [brand])
    assert {e.signal for e in ev} <= {"visual.favicon_match_brand"}
    assert all(e.polarity != "risk" for e in ev)


def test_cloaking_signal() -> None:
    benign = _profile(
        "desktop_en", "http://c.test/", dom_simhash="0" * 16, visible_text="Coming soon"
    )
    phish = _phish_profile("mobile_ar")
    cl = compare_profiles(phish, benign)
    assert cl.diff and "cred_form_differs" in cl.reasons
    ev = build_page_evidence(
        RenderFeatures(url="x", profiles={"mobile_ar": phish, "desktop_en": benign}, cloaking=cl),
        [FIXTURE_BRAND],
    )
    assert "page.cloaking" in _signals(ev)


def test_cloaking_ignores_identical_and_failed() -> None:
    a = _profile("desktop_en", dom_simhash="1" * 16, visible_text="one two three four five six")
    b = _profile("mobile_ar", dom_simhash="1" * 16, visible_text="one two three four five six")
    assert compare_profiles(a, b) == Cloaking(diff=False, simhash_distance=0, text_similarity=1.0)
    failed = ProfileFeatures(profile="mobile_ar", requested_url="x", error="timeout")
    assert not compare_profiles(a, failed).diff


def test_features_forbid_raw_html_fields() -> None:
    with pytest.raises(ValueError):
        ProfileFeatures(profile="desktop_en", requested_url="x", html="<html>")  # type: ignore[call-arg]
