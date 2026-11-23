"""Feature models and helpers the sandbox uses: simhash, pHash, cloaking, hosts, text folding."""

from __future__ import annotations

from typing import Any

import pytest

from falcon_core.signals.page.cloaking import compare_profiles
from falcon_core.signals.page.features import (
    Cloaking,
    FormFeature,
    ProfileFeatures,
)
from falcon_core.signals.page.hosts import registrable_domain
from falcon_core.signals.page.simhash import dom_simhash, hamming_hex
from falcon_core.signals.page.text import normalize
from falcon_core.signals.visual import hamming64, phash_from_gray32


def test_simhash_structure_only() -> None:
    a = dom_simhash(["1:div", "html>div", "2:form", "div>form"] * 3)
    assert a == dom_simhash(["1:div", "html>div", "2:form", "div>form"] * 3)
    assert hamming_hex(a, a) == 0
    other = dom_simhash([f"{i}:section" for i in range(40)])
    assert hamming_hex(a, other) > 10


def test_phash_stable_and_discriminates() -> None:
    img = [
        [200.0 if 6 <= x < 20 and 4 <= y < 14 else (60.0 if y > 20 else 120.0) for x in range(32)] for y in range(32)
    ]
    checker = [[255.0 if (x // 4 + y // 4) % 2 else 0.0 for x in range(32)] for y in range(32)]
    assert phash_from_gray32(img) == phash_from_gray32(img)
    noisy = [[v + (1 if (x + y) % 7 == 0 else 0) for x, v in enumerate(r)] for y, r in enumerate(img)]
    assert hamming64(phash_from_gray32(img), phash_from_gray32(noisy)) <= 4
    assert hamming64(phash_from_gray32(img), phash_from_gray32(checker)) > 10
    with pytest.raises(ValueError):
        phash_from_gray32([[0.0] * 3])


def test_registrable_domain() -> None:
    assert registrable_domain("login.adpolice.gov.ae") == "adpolice.gov.ae"
    assert registrable_domain("a.b.falcon-demo-bank.test") == "falcon-demo-bank.test"


def test_normalize_folds_arabic() -> None:
    assert normalize("كَلِمَةُ الْمُرُورِ") == normalize("كلمه المرور")
    assert normalize("cardNumber") == " card number "
    assert normalize("٧٨٤") == " 784 "


def _profile(name: str = "desktop_en", url: str = "http://a.test/", **kw: Any) -> ProfileFeatures:
    return ProfileFeatures.model_validate(
        {"profile": name, "requested_url": url, "final_url": url, "status": 200, **kw}
    )


def test_cloaking_detects_cred_form_difference() -> None:
    benign = _profile("desktop_en", dom_simhash="0" * 16, visible_text="Coming soon")
    phish = _profile(
        "mobile_ar",
        forms=[FormFeature(cred_form=True, sensitive_kinds=["password"])],
        dom_simhash="f" * 16,
    )
    cl = compare_profiles(phish, benign)
    assert cl.diff and "cred_form_differs" in cl.reasons


def test_cloaking_ignores_identical_and_failed() -> None:
    a = _profile("desktop_en", dom_simhash="1" * 16, visible_text="one two three four five six")
    b = _profile("mobile_ar", dom_simhash="1" * 16, visible_text="one two three four five six")
    assert compare_profiles(a, b) == Cloaking(diff=False, simhash_distance=0, text_similarity=1.0)
    failed = ProfileFeatures(profile="mobile_ar", requested_url="x", error="timeout")
    assert not compare_profiles(a, failed).diff


def test_cloaking_skips_comparison_when_one_side_was_read_partially() -> None:
    """A half-loaded profile differs from a full one only by how much was read: that is not cloaking."""
    from falcon_core.signals.page.features import NetworkSummary

    full = _profile("desktop_en", dom_simhash="0" * 16, visible_text="one two three four five six seven")
    half = _profile(
        "mobile_ar",
        forms=[FormFeature(cred_form=True, sensitive_kinds=["password"])],
        dom_simhash="f" * 16,
        network=NetworkSummary(partial=True),
    )
    assert not compare_profiles(half, full).diff
    assert not compare_profiles(full, half).diff
    cut = _profile("mobile_ar", network=NetworkSummary(truncated=True))
    assert not compare_profiles(cut, full).diff
    elsewhere = _profile("mobile_ar", url="http://b.test/", network=NetworkSummary(partial=True))
    assert compare_profiles(elsewhere, full).diff  # a different final site is still a behavioural difference


def test_features_forbid_raw_html_fields() -> None:
    with pytest.raises(ValueError):
        ProfileFeatures.model_validate({"profile": "desktop_en", "requested_url": "x", "html": "<"})
