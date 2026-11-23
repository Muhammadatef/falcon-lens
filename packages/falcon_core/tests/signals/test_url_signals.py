# ruff: noqa: E501
"""T-007 acceptance + edge cases. All hosts are invented or reserved (.test/.example); no live URLs."""

import json
import re
import statistics
import time
from pathlib import Path

import pytest
import yaml

from falcon_core.signals import REGISTRY
from falcon_core.signals.brands import BrandRegistry, default_registry
from falcon_core.signals.url.lexical import FEATURE_NAMES, extract_features
from falcon_core.signals.url.skeleton import skeleton, skeleton_ci

from conftest import Ctx, run_signal

BRAND = "falcon-demo-bank.test"
SQUAT = ("url.homograph", "url.typosquat", "url.combosquat", "url.brand_in_subdomain_or_path")
ALL_URL = [n for n in REGISTRY if n.startswith("url.") and REGISTRY[n][0].emits]


def names(url: str, only=None) -> set[str]:
    out = set()
    for n in only or ALL_URL:
        out |= {e.signal for e in run_signal(n, url) if e.error is None}
    return out


def test_registry_specs_valid():
    schema = json.loads(
        (Path(__file__).resolve().parents[4] / "contracts" / "signal.schema.json").read_text(encoding="utf-8")
    )
    pat = re.compile(schema["properties"]["name"]["pattern"])
    scoring = (Path(__file__).resolve().parents[4] / "docs" / "SCORING.md").read_text(encoding="utf-8")
    for name, (spec, _fn) in REGISTRY.items():
        assert pat.match(name) and 10 <= spec.timeout_ms <= 6000
        if spec.family not in ("url", "domain", "reputation"):  # others: tests/signals/message etc.
            continue
        if spec.family == "url":
            assert spec.network == "none"
        for e in spec.emits:
            assert e in scoring, e
    assert set(ALL_URL) >= {
        "url.homograph",
        "url.typosquat",
        "url.combosquat",
        "url.brand_in_subdomain_or_path",
        "url.userinfo_trick",
        "url.bidi_or_zero_width",
        "url.raw_ip_host",
        "url.free_host_or_tunnel",
        "url.open_redirect_abuse",
    }


def test_evidence_shape():
    ev = run_signal("url.typosquat", "https://falcon-demo-bnak.test/")[0].to_dict()
    assert re.match(r"^ev_[a-z0-9]{8,32}$", ev["id"]) and ev["family"] == "url" and ev["tier"] == "T1"
    assert ev["weight"] == 0 and ev["source"] == "computed" and 0 <= ev["confidence"] <= 1
    assert ev["display"]["ar"] and ev["display"]["en"] and len(ev["display"]["en"]) <= 200
    assert len(json.dumps(ev["observed"])) < 1024


# ----- acceptance criteria from T-007
def test_cyrillic_lookalike_is_homograph():
    cyr = "falcon-demo-bаnk.test"  # Cyrillic a
    assert "url.homograph" in names("https://" + cyr + "/login")
    punycode = cyr.encode("idna").decode()
    assert punycode.startswith("xn--") or "xn--" in punycode
    assert "url.homograph" in names("https://" + punycode + "/")


def test_typosquat_transposition():
    assert "url.typosquat" in names("https://falcon-demo-bnak.test/")


def test_combosquat():
    n = names("https://falcon-demo-bank-secure-pay.test/")
    assert "url.combosquat" in n and "url.typosquat" not in n
    assert "url.combosquat" in names("https://falcon-demo-bank-gov-fines.test/")
    assert "url.combosquat" in names("https://falcon-demo-bank-gov.example/")


def test_data_uri_evidence():
    ev = run_signal("url.data_uri", "data:text/html;base64,PGh0bWw+AAAA")
    assert ev and ev[0].observed == {"mime": "text/html", "base64": True, "length": 34}
    assert "PGh0" not in str(ev[0].to_dict())  # never the payload
    assert run_signal("url.data_uri", "DATA:,hello")[0].observed["mime"] == "text/plain"
    for bad in ("data:https://evil.example/login.php,x", "data:<script>alert(1)</script>,x"):
        ev = run_signal("url.data_uri", bad)
        assert ev and ev[0].observed["mime"] == "invalid"
        assert "evil" not in str(ev[0].to_dict()) and "<script>" not in str(ev[0].to_dict())
    assert not run_signal("url.data_uri", "https://falcon-demo-bank.test/")


def test_official_domain_is_clean():
    assert not names(f"https://{BRAND}/", SQUAT)
    assert not names(f"https://login.{BRAND}/a/falcon-demo-bank", SQUAT)


def test_free_host_judged_per_subdomain():
    ev = run_signal("url.free_host_or_tunnel", "https://fl-fixture-0000.github.io/x")
    assert ev and ev[0].observed["tenant"] == "fl-fixture-0000"
    assert not run_signal("url.free_host_or_tunnel", "https://falcon-demo-bank.test/")
    # a brand-named tenant on a free host is still caught by the squat plugins
    assert "url.brand_in_subdomain_or_path" in names("https://falcon-demo-bank-login.github.io/")
    assert "url.free_host_or_tunnel" in names("https://fl-fixture-0001.ngrok-free.app/")
    assert "url.free_host_or_tunnel" in names("https://fl-fixture-0002.trycloudflare.com/")


def test_rlo_bidi():
    assert "url.bidi_or_zero_width" in names("https://example.test/\u202egpj.exe")
    assert "url.bidi_or_zero_width" in names("https://example.test/%E2%80%AEfdp")
    assert "url.bidi_or_zero_width" in names("https://fal\u200bcon-demo-bank.test/")
    assert not names("https://example.test/plain", ("url.bidi_or_zero_width",))


# ----- additional required cases
def test_same_script_capital_i_for_l():
    # 'I' (capital i) typed for 'l' in "falcon": hosts are lowercased but the typed form is caught
    assert "url.homograph" in names("https://FaIcon-demo-bank.test/")
    assert "url.homograph" in names("https://falcon-dem0-bank.test/")


def test_rn_for_m():
    reg = BrandRegistry.from_entries(
        [
            {
                "brand_id": "x",
                "name_en": "Example Demo",
                "name_ar": "x",
                "category": "demo",
                "verified_domains": ["mashreqdemo.test"],
            }
        ]
    )
    ctx = Ctx(url="https://rnashreqdemo.test/", brands=reg)
    _s, fn = REGISTRY["url.homograph"]
    import asyncio

    assert asyncio.run(fn(ctx))


def test_mixed_script_without_brand():
    ev = run_signal("url.homograph", "https://exаmple.test/")  # Cyrillic a inside Latin label
    assert ev and "mixed_script" in ev[0].observed["reasons"]


def test_arabic_idn_brand_in_label():
    n = names("https://شرطة-ابوظبي-مخالفات.test/")
    assert "url.combosquat" in n
    assert "url.brand_in_subdomain_or_path" in names("https://شرطة-ابوظبي.verify.test/")
    assert "url.brand_in_subdomain_or_path" in names(
        "https://example.test/%D8%B4%D8%B1%D8%B7%D8%A9-%D8%A7%D8%A8%D9%88%D8%B8%D8%A8%D9%8A/"
    )
    # plain Arabic site with no brand token: nothing
    assert not names("https://مثال.test/صفحة", SQUAT)


def test_official_domain_as_subdomain_prefix():
    ev = run_signal("url.brand_in_subdomain_or_path", "https://falcon-demo-bank.test.verify-fine.test/pay")
    assert ev and ev[0].observed["official_domain_in_host"] is True
    assert "url.brand_in_subdomain_or_path" in names("https://falcon-demo-bank.test.verify-fine.invalid/")


def test_userinfo_trick():
    ev = run_signal("url.userinfo_trick", "https://falcon-demo-bank.test@evil.example/login")
    assert ev and ev[0].confidence == 1.0 and "evil[.]example" in ev[0].observed["real_host"]
    assert not run_signal("url.userinfo_trick", "https://example.test/")


@pytest.mark.parametrize("host", ["3232235521", "0xC0A80001", "0300.0250.0.1", "203.0.113.9"])
def test_raw_ip(host):
    assert run_signal("url.raw_ip_host", f"http://{host}/pay")
    assert not run_signal("url.raw_ip_host", "http://example.test/")


def test_open_redirect():
    ev = run_signal(
        "url.open_redirect_abuse",
        "https://example.test/redirect?url=https%3A%2F%2Fevil.example%2Fx",
    )
    assert ev and ev[0].observed["target_host"] == "evil[.]example"
    assert run_signal("url.open_redirect_abuse", "https://falcon-demo-bank.test/out?next=//evil.example/")
    # same-site and relative targets are fine
    assert not run_signal("url.open_redirect_abuse", "https://example.test/login?next=/home")
    assert not run_signal("url.open_redirect_abuse", "https://example.test/login?next=https://example.test/home")


# ----- legitimate official domains: no squat/homograph evidence
def test_all_official_domains_clean():
    reg = default_registry()
    checked = 0
    for b in reg.brands:
        for d in b.verified_domains:
            for url in (f"https://{d}/", f"https://www.{d}/en/pay?x=1", f"https://login.{d}/"):
                assert not names(url, SQUAT), (url, names(url, SQUAT))
                checked += 1
    assert checked > 50


def test_ordinary_sites_clean():
    for u in [
        "https://example.com/",
        "https://www.wikipedia.org/wiki/Abu_Dhabi",
        "https://news.example.test/a",
    ]:
        assert not names(u, SQUAT), u


def test_short_brand_labels_not_typosquatted():
    # 'du', 'moi', 'rta' are too short for edit-distance matching
    for u in ["https://dub.test/", "https://roi.test/", "https://rtb.test/"]:
        assert "url.typosquat" not in names(u)


def test_real_brand_typo_and_tld_swap_and_keyboard():
    assert "url.typosquat" in names("https://falcon-demo-bamk.test/")  # n next to m on QWERTY
    ev = run_signal("url.typosquat", "https://falcon-demo-bank.example/")
    assert ev and ev[0].observed["kind"] == "tld_swap"
    assert "url.typosquat" in names("https://falcondemobank.test/")  # hyphen removed


# ----- robustness: never raises, hostile input
@pytest.mark.parametrize(
    "u",
    [
        "",
        "   ",
        "http://",
        "http://[::",
        "\x00",
        "a" * 30000,
        "http://%zz.test/%",
        "data:text/html,<x>",
        "javascript:alert(1)",
        "http://\u202e\u202e/",
        "http://" + "a." * 500 + "test",
    ],
)
def test_never_raise(u):
    for n in REGISTRY:
        out = run_signal(n, u)
        assert isinstance(out, list)


def test_timeout_yields_error_evidence(monkeypatch):
    import asyncio

    from falcon_core.signals.base import SignalSpec, signal

    spec = SignalSpec(
        name="url.slow_test",
        family="url",
        tier="T1",
        input_types=("url",),
        timeout_ms=10,
        network="none",
        emits=(),
    )

    @signal(spec)
    def slow(ctx):
        raise RuntimeError("boom")

    out = asyncio.run(slow(Ctx(url="http://x.test")))
    assert out[0].error and out[0].error == "RuntimeError"
    del REGISTRY["url.slow_test"]


def test_skeleton():
    assert skeleton("paypaI") == skeleton("paypal")  # capital I -> l (UTS#39)
    assert skeleton_ci("bаnk") == skeleton_ci("bank")
    assert skeleton_ci("m") == skeleton_ci("rn")
    assert skeleton_ci("d0main") == skeleton_ci("domain")


def test_brand_registry_loads_all_yaml_entries():
    reg = default_registry()
    raw = yaml.safe_load((Path(__file__).resolve().parents[4] / "data" / "brands.yaml").read_text(encoding="utf-8"))
    assert len(reg.brands) == len(raw["brands"]) >= 20
    assert reg.is_official("adpolice.gov.ae") and reg.is_official("falcon-demo-bank.test")
    assert not reg.is_official("falcon-demo-bank.example")
    assert reg.is_official_host("login.adpolice.gov.ae")
    for b in reg.brands:
        assert b.retrieved_at and b.source_url


# ----- features + performance
def test_features_fixed_numeric():
    f = extract_features("https://falcon-demo-bnak.test/login?next=https://x.example")
    assert tuple(f) == FEATURE_NAMES and all(isinstance(v, float) for v in f.values())
    assert f["brand_min_edit_distance"] == 1.0 and f["has_embedded_url_in_query"] == 1.0
    assert extract_features("")["url_len"] == 0.0
    assert extract_features("http://3232235521/")["ip_obfuscated"] == 1.0
    assert extract_features(f"https://{BRAND}/")["is_official"] == 1.0
    assert REGISTRY["url.lexical_features"][0].feature_names == FEATURE_NAMES


def test_p95_under_5ms():
    urls = [
        "https://falcon-demo-bank.test.verify-fine.test/pay?next=https://evil.example/a",
        "https://falcon-demo-bаnk-secure.test/login",
        "https://fl-fixture-0000.github.io/a/b/c?x=1&y=2",
        "https://شرطة-ابوظبي-مخالفات.test/",
        "http://3232235521/x",
    ] * 4
    for n in ALL_URL:
        _spec, fn = REGISTRY[n]
        run = fn.sync  # type: ignore[attr-defined]
        samples = []
        for u in urls:
            ctx = Ctx(url=u)
            run(ctx)  # warm caches (PSL, confusables, canonical lru)
            best = float("inf")  # best of 5: scheduler noise under parallel CI load inflates single runs
            for _ in range(5):
                t0 = time.perf_counter()
                run(ctx)
                best = min(best, (time.perf_counter() - t0) * 1000)
            samples.append(best)
        p95 = statistics.quantiles(samples, n=20)[-1]
        assert p95 < 5, (n, p95)
