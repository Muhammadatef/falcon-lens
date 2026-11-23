"""T2 page evidence, brand check (H1 input), sandbox client and verdict assembly invariants."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from cascade_helpers import assert_valid

from falcon_core.cascade import HttpSandboxClient, SandboxError, SandboxFeatures, SandboxForm
from falcon_core.cascade.assemble import VerdictInvariantError, build_verdict, check_invariants
from falcon_core.cascade.ids import new_verdict_id
from falcon_core.cascade.page import field_kind, page_evidence, target_kind
from falcon_core.cascade.testing import benign_features, phish_features
from falcon_core.scoring.arbiter import ArbiterContext, score
from falcon_core.signals.brands.registry import default_registry

REG = default_registry()
LOOK = "falcon-demo-bank-login.test"


def _by_signal(evs: list[Any]) -> dict[str, Any]:
    return {e.signal: e for e in evs}


@pytest.mark.parametrize(
    ("descriptor", "kind"),
    [
        ("password", "password"),
        ({"type": "text", "autocomplete": "cc-number"}, "card"),
        ({"name": "cvv"}, "cvv"),
        ({"autocomplete": "one-time-code"}, "otp"),
        ({"label": "Emirates ID"}, "emirates_id"),
        ("text:username", None),
        ({"name": "spinner"}, None),
    ],
)
def test_field_kind(descriptor: Any, kind: str | None) -> None:
    assert field_kind(descriptor) == kind


def test_target_kind() -> None:
    assert target_kind("api.telegram.org") == "bot_api"
    assert target_kind("discord.com/api/webhooks/1/x") == "webhook"
    assert target_kind("discord.com/channels") is None
    assert target_kind("https://cdn.community-garden-club.test") is None


def test_phish_page_claims_brand_not_owned() -> None:
    evs = _by_signal(page_evidence(phish_features(), LOOK, REG))
    claim = evs["brand.claimed_not_owned"]
    assert claim.observed["brand_id"] == "falcon_demo_bank"
    assert claim.confidence >= 0.9
    assert "title" in claim.observed["claimed_in"]
    assert evs["page.cred_form"].observed["field_kinds"] == ["password"]
    # Observations never carry raw page text.
    blob = json.dumps([e.observed for e in evs.values()])
    assert "Welcome to" not in blob and "Online Banking Login" not in blob


def test_official_page_is_not_a_claim() -> None:
    feats = phish_features("https://falcon-demo-bank.test/login")
    evs = _by_signal(page_evidence(feats, "falcon-demo-bank.test", REG))
    assert "brand.claimed_not_owned" not in evs


def test_single_text_mention_stays_below_h1_threshold() -> None:
    feats = benign_features().model_copy(
        update={
            "visible_text": "News: Falcon Demo Bank opened a branch.",
            "forms": [SandboxForm(fields=["password"])],
        }
    )
    claim = _by_signal(page_evidence(feats, "community-garden-club.test", REG))["brand.claimed_not_owned"]
    assert claim.confidence < 0.7  # below theta: no H1 from one passing mention


def test_arabic_title_claim() -> None:
    feats = benign_features().model_copy(update={"title": "بنك الصقر التجريبي - تسجيل الدخول"})
    evs = _by_signal(page_evidence(feats, "community-garden-club.test", REG))
    assert evs["brand.claimed_not_owned"].observed["brand_id"] == "falcon_demo_bank"


def test_favicon_match_and_hotlink() -> None:
    fav = "ab" * 32
    feats = benign_features().model_copy(
        update={"favicon_sha256": fav, "hotlinked_origins": ["https://falcon-demo-bank.test"]}
    )
    evs = _by_signal(page_evidence(feats, "community-garden-club.test", REG, {fav: "falcon_demo_bank"}))
    assert evs["visual.favicon_match_brand"].observed["brand_id"] == "falcon_demo_bank"
    assert evs["page.hotlinked_brand_assets"].observed["origins"] == ["hxxps://falcon-demo-bank[.]test"]
    assert "favicon" in evs["brand.claimed_not_owned"].observed["claimed_in"]


def test_cross_origin_post_marks_credentials_and_bot() -> None:
    feats = benign_features().model_copy(
        update={
            "forms": [SandboxForm(fields=["password"], action_origin="api.telegram.org")],
            "post_targets": ["https://collector.other-host.test/x"],
        }
    )
    ev = _by_signal(page_evidence(feats, "community-garden-club.test", REG))["page.cross_origin_post"]
    assert ev.observed["bot"] is True and ev.observed["credentials"] is True
    assert ev.observed["target_kind"] == "bot_api"
    assert all("[.]" in t for t in ev.observed["targets"])


def test_cloaking_observation_is_scalars_only() -> None:
    feats = benign_features().model_copy(
        update={"cloaking": {"detected": True, "simhash_distance": 31, "note": "<script>"}}
    )
    ev = _by_signal(page_evidence(feats, "community-garden-club.test", REG))["page.cloaking"]
    assert ev.observed == {"detected": True, "simhash_distance": 31}


def test_sandbox_features_ignore_unknown_and_cap_text() -> None:
    f = SandboxFeatures.model_validate({"visible_text": "x" * 10_000, "new_feature": 1})
    assert len(f.visible_text) == 4096


# --- HTTP sandbox client ------------------------------------------------------------------------


async def test_http_sandbox_client_posts_and_parses() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        seen["key"] = req.headers.get("Authorization")
        return httpx.Response(200, json={"features": phish_features().model_dump()})

    c = HttpSandboxClient("http://sandbox:8000", token="k", transport=httpx.MockTransport(handler))
    feats = await c.render("https://falcon-demo-bank-login.test/", "vd_X")
    await c.aclose()
    assert seen == {"path": "/render", "body": {"url": "https://falcon-demo-bank-login.test/",
                                                 "verdict_id": "vd_X"}, "key": "Bearer k"}  # fmt: skip
    assert feats.title.startswith("Falcon Demo Bank")


@pytest.mark.parametrize(
    ("resp", "reason"),
    [(httpx.Response(503), "http_503"), (httpx.Response(200, content=b"nope"), "bad_json"),
     (httpx.Response(200, json={"forms": "x"}), "bad_shape")],
)  # fmt: skip
async def test_http_sandbox_client_errors(resp: httpx.Response, reason: str) -> None:
    c = HttpSandboxClient("http://sandbox:8000", transport=httpx.MockTransport(lambda r: resp))
    with pytest.raises(SandboxError) as ei:
        await c.render("https://x.test/", "vd_X")
    assert ei.value.reason == reason


async def test_http_sandbox_client_unreachable() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    c = HttpSandboxClient("http://sandbox:8000", transport=httpx.MockTransport(boom))
    with pytest.raises(SandboxError) as ei:
        await c.render("https://x.test/", "vd_X")
    assert ei.value.reason.startswith("unreachable")


# --- assembly invariants -------------------------------------------------------------------------


def _doc() -> dict[str, Any]:
    evs = page_evidence(phish_features(), LOOK, REG)
    result = score(evs, None, ArbiterContext(registrable_domain=LOOK))
    return build_verdict(
        result, verdict_id=new_verdict_id(), input_type="url", tier="T2", final=True,
        latency_ms=12, registry=REG, canonical_url_defanged="hxxps://falcon-demo-bank-login[.]test/",
    )  # fmt: skip


def test_build_verdict_valid() -> None:
    d = _doc()
    assert_valid(d)
    assert d["verdict"] == "dangerous" and d["reasons"]
    assert all(r["generated_by"] == "template" for r in d["reasons"])


def test_invariant_unknown_evidence_id_rejected() -> None:
    d = _doc()
    d["reasons"][0]["evidence_ids"] = ["ev_doesnotexist0"]
    with pytest.raises(VerdictInvariantError):
        check_invariants(d)


def test_invariant_url_must_be_defanged() -> None:
    d = _doc()
    d["canonical_url"] = "https://falcon-demo-bank-login.test/"
    with pytest.raises(VerdictInvariantError):
        check_invariants(d)


def test_invariant_degraded_no_warning_signs_rejected() -> None:
    d = _doc()
    d.update(verdict="no_warning_signs", degraded=True)
    d["actions"]["caution"] = {"ar": ["x"], "en": ["x"]}
    with pytest.raises(VerdictInvariantError):
        check_invariants(d)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://falcon-demo-bank.test/", "https://falcon-demo-bank.test/"),
        ("https://falcon-demo-bank.test", "https://falcon-demo-bank.test"),
        (
            "https://falcon-demo-bank.test/a/b?run=1f2e3d4c&lang=ar",
            "https://falcon-demo-bank.test/a/b?run=1f2e3d4c&lang=ar",
        ),
        ("https://falcon-demo-bank.test/x#section", "https://falcon-demo-bank.test/x"),
        (
            "http://falcon-demo-bank.test/reset?email=test.user@example.invalid&token=abc123",
            "http://falcon-demo-bank.test/reset?email=[EMAIL]&token=abc123",
        ),
        (
            "https://falcon-demo-bank.test/login?u=test.user%40example.invalid",
            "https://falcon-demo-bank.test/login?u=[EMAIL]",
        ),
        ("https://falcon-demo-bank.test/u/+971501234567/verify", "https://falcon-demo-bank.test/u/[PHONE]/verify"),
        ("https://falcon-demo-bank.test?id=784-1990-1234567-1", "https://falcon-demo-bank.test?id=[EMIRATES_ID]"),
        ("https://falcon-demo-bank.test/pay?card=4111111111111111", "https://falcon-demo-bank.test/pay?card=[CARD]"),
        (
            "https://falcon-demo-bank.test/%D8%AA%D8%AD%D9%82%D9%82?v=2.0.1",
            "https://falcon-demo-bank.test/%D8%AA%D8%AD%D9%82%D9%82?v=2.0.1",
        ),
        ("not a url", "not a url"),
    ],
)
def test_display_url_keeps_the_address_and_drops_personal_data(url: str, expected: str) -> None:
    from falcon_core.cascade.assemble import display_url

    assert display_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://test.user@example.invalid:pw@falcon-demo-bank.test/x",
        "https://user:pw@falcon-demo-bank.test/x",
        "https://a@b@c:d@falcon-demo-bank.test/x?q=1",
        "https://test.user%40example.invalid:p%3Aw@falcon-demo-bank.test/x",
        "https://%D8%B9%D8%B1%D8%A8%D9%8A:pw@falcon-demo-bank.test/x",
        "https://عربي:pw@falcon-demo-bank.test/x",
        "https://xn--mgbh0fb:pw@falcon-demo-bank.test",
        "https://test.user@example.invalid@falcon-demo-bank.test?x=1",
        "https://user@falcon-demo-bank.test#frag",
        "https://u:p@falcon-demo-bank.test:8443/x",
    ],
)
def test_display_url_strips_all_userinfo_keeping_the_real_host(url: str) -> None:
    from falcon_core.cascade.assemble import display_url

    out = display_url(url)
    authority = out.partition("://")[2].split("/")[0].split("?")[0]
    assert "@" not in authority
    assert authority.startswith("falcon-demo-bank.test")
    for leak in ("test.user", "example.invalid", "pw", "عربي", "xn--mgbh0fb", "%40", "%3A"):
        assert leak not in out
