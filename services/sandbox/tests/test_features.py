"""Sandbox feature extraction helpers + the contract with the cascade's page evidence builder."""

from __future__ import annotations

from typing import Any

import pytest

from falcon_core.cascade.models import SandboxFeatures
from falcon_core.cascade.page import page_evidence
from falcon_core.signals.brands.registry import default_registry
from falcon_core.signals.page.features import (
    Favicon,
    JsIndicators,
    ProfileFeatures,
    RenderFeatures,
)
from falcon_sandbox.build import (
    build_forms,
    build_static_post_targets,
    js_obfuscation_indicators,
    truncate_utf8,
)
from falcon_sandbox.classify import FieldKind, classify_field
from falcon_sandbox.compat import to_flat
from falcon_sandbox.exfil import classify_post_target

K = FieldKind


def refang(url: str) -> str:
    """Test URLs are stored defanged (hxxp / [.]) so the repo holds no live URLs."""
    return url.replace("hxxp", "http").replace("[.]", ".")


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


@pytest.mark.parametrize(
    ("url", "category"),
    [
        ("hxxps://api[.]telegram[.]org/bot123456:ABCdef/sendMessage", "messaging_bot_api"),
        ("hxxp://falcon-bot-relay[.]test/bot123456:FAKE/sendMessage", "messaging_bot_api"),
        ("hxxps://discord[.]com/api/webhooks/123/abc", "webhook"),
        ("hxxps://hooks[.]slack[.]com/services/T0/B0/xyz", "webhook"),
        ("hxxps://formspree[.]io/f/abcd", "form_relay"),
        ("hxxps://webhook[.]site/uuid", "webhook"),
    ],
)
def test_exfil_targets(url: str, category: str) -> None:
    c = classify_post_target(refang(url))
    assert c.exfil and c.category == category


def test_non_exfil_targets() -> None:
    assert not classify_post_target(refang("hxxps://www[.]google-analytics[.]com/collect")).exfil
    assert not classify_post_target(refang("hxxps://bank[.]example[.]com/login")).exfil


RELAY = refang("hxxp://falcon-bot-relay[.]test/bot123456:FAKE/sendMessage")
PW: dict[str, object] = {"type": "password", "name": "password"}
USER: dict[str, object] = {"type": "text", "name": "username"}


def _form(action: str, fields: list[dict[str, object]]) -> dict[str, object]:
    return {"action": action, "method": "post", "fields": fields}


def test_build_forms_flags_cross_origin_and_exfil() -> None:
    f = build_forms([_form(RELAY, [USER, PW])], "http://falcon-demo-bank-secure.test/login")[0]
    assert f.cred_form and f.action_cross_origin and f.action_exfil
    assert f.sensitive_kinds == ["password"]


def test_build_forms_same_origin_search_is_not_cred() -> None:
    f = build_forms([_form("http://x.test/search", [{"type": "text", "name": "q"}])], "http://x.test/")
    assert not f[0].cred_form and not f[0].action_cross_origin


def test_static_post_targets() -> None:
    t = build_static_post_targets(
        [{"kind": "fetch", "url": RELAY}],
        ["https://cdn.example.com/lib.js", refang("hxxps://discord[.]com/api/webhooks/1/x")],
        "http://phish.test/",
    )
    assert [x.exfil for x in t] == [True, True]
    assert t[1].kind == "script_literal"


def test_truncate_utf8_never_splits_characters() -> None:
    s = truncate_utf8("مرحبا " * 2000)
    assert len(s.encode()) <= 4096
    s.encode()


def test_js_indicators() -> None:
    assert js_obfuscation_indicators(JsIndicators()) == []
    ind = js_obfuscation_indicators(JsIndicators(eval_calls=1, atob_calls=1, contextmenu_block=1))
    assert "eval_of_decoded" in ind and "block_contextmenu" in ind


# ---- contract with main's cascade evidence builder (single evidence builder) -------------------


def _phish() -> ProfileFeatures:
    forms = build_forms([_form(RELAY, [USER, PW, {"type": "text", "name": "cvv"}])],
                        "http://falcon-demo-bank-secure.test/login")  # fmt: skip
    targets = build_static_post_targets([{"kind": "fetch", "url": RELAY}], [], "http://falcon-demo-bank-secure.test/login")  # fmt: skip
    return ProfileFeatures(
        profile="mobile_ar",
        requested_url="http://falcon-demo-bank-secure.test/login",
        final_url="http://falcon-demo-bank-secure.test/login",
        status=200,
        title="Falcon Demo Bank - Secure Login",
        forms=forms,
        script_post_targets=targets + targets,
        asset_origins=["falcon-demo-bank.test"],
        favicon=Favicon(sha256="a" * 64, phash="00ff00ff00ff00ff"),
        visible_text="Falcon Demo Bank secure login. Falcon Demo Bank",
        dom_simhash="1" * 16,
    )


def test_flat_features_feed_cascade_page_evidence() -> None:
    flat = to_flat(RenderFeatures(url="x", profiles={"mobile_ar": _phish()}), "vd_1")
    assert flat["exfil_targets"] == [{"origin": "http://falcon-bot-relay.test", "category": "messaging_bot_api"}]
    feats = SandboxFeatures.model_validate(flat)
    ev = {
        e.signal: e
        for e in page_evidence(
            feats, "falcon-demo-bank-secure.test", default_registry(), {"a" * 64: "falcon_demo_bank"}
        )
    }
    assert {
        "page.cred_form",
        "page.cross_origin_post",
        "page.hotlinked_brand_assets",
        "visual.favicon_match_brand",
        "brand.claimed_not_owned",
    } <= set(ev)
    assert ev["page.cross_origin_post"].observed["bot"] is True


def test_failed_profile_reports_error_and_no_final_url() -> None:
    failed = ProfileFeatures(profile="desktop_en", requested_url="http://x.test/", error="egress_blocked")
    flat: dict[str, Any] = to_flat(RenderFeatures(url="x", profiles={"desktop_en": failed}), None)
    assert flat["error"] == "egress_blocked" and flat["final_url"] is None
    assert SandboxFeatures.model_validate(flat).error == "egress_blocked"
