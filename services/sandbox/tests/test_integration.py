"""Integration tests against the compose stack (sandbox + egress-proxy + fixtures).

Run with the stack up (project name set, tools profile on):
  docker compose --profile core --profile tools up -d sandbox egress-proxy fixtures
  FL_INTEGRATION=1 uv run pytest -m integration services/sandbox

The sandbox is not published on the host (it only lives on internal networks), so requests are
issued from inside the sandbox container with ``docker compose exec``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from falcon_core.signals.page.evidence import build_page_evidence
from falcon_core.signals.page.features import Cloaking, RenderFeatures
from falcon_core.signals.visual import FIXTURE_BRAND, phash_from_gray32
from falcon_core.signals.visual.brands import BrandRef

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("FL_INTEGRATION"), reason="set FL_INTEGRATION=1"),
]

ROOT = Path(__file__).resolve().parents[3]
CLIENT = """
import json, os, sys, urllib.request, urllib.error
path, payload = sys.argv[1], sys.argv[2]
req = urllib.request.Request("http://127.0.0.1:8000" + path, data=payload.encode(), method="POST",
    headers={"content-type": "application/json", "x-sandbox-key": os.environ["FL_SANDBOX_TOKEN"]})
try:
    r = urllib.request.urlopen(req, timeout=30)
    print(json.dumps({"status": r.status, "body": json.loads(r.read())}))
except urllib.error.HTTPError as e:
    print(json.dumps({"status": e.code, "body": json.loads(e.read() or b"{}")}))
"""


def call(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    out = subprocess.run(  # noqa: S603
        ["docker", "compose", "--profile", "core", "--profile", "tools", "exec", "-T", "sandbox",  # noqa: S607
         "python", "-c", CLIENT, path, json.dumps(payload)],
        cwd=ROOT, capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    data = json.loads(out.stdout.strip().splitlines()[-1])
    return data["status"], data["body"]


def fixtures_log() -> str:
    return subprocess.run(  # noqa: S603
        ["docker", "compose", "--profile", "tools", "logs", "--no-log-prefix", "fixtures"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
    ).stdout  # fmt: skip


def favicon_brand() -> BrandRef:
    from falcon_sandbox.browser import image_phash

    data = (ROOT / "services/fixtures/sites/official/assets/favicon.png").read_bytes()
    import hashlib

    return BrandRef(
        **{
            **FIXTURE_BRAND.__dict__,
            "favicon_sha256": (hashlib.sha256(data).hexdigest(),),
            "favicon_phash": (image_phash(data) or "",),
        }
    )


def render(url: str, **kw: Any) -> RenderFeatures:
    status, body = call("/render", {"url": url, "verdict_id": "vd_test", **kw})
    assert status == 200, body
    c = body["cloaking"]
    return RenderFeatures(
        url=url,
        profiles=body["profiles"],
        cloaking=Cloaking(diff=c["diff"], reasons=c["reasons"], simhash_distance=c["simhash_distance"]),
    )


def signals(f: RenderFeatures) -> set[str]:
    return {e.signal for e in build_page_evidence(f, [favicon_brand()])}


def test_phish_fixture_evidence() -> None:
    f = render("http://falcon-demo-bank-secure.test/login")
    ev = {e.signal: e for e in build_page_evidence(f, [favicon_brand()])}
    assert {
        "page.cred_form",
        "page.cross_origin_post",
        "page.hotlinked_brand_assets",
        "brand.claimed_not_owned",
        "visual.favicon_match_brand",
        "page.js_obfuscation",
    } <= set(ev)
    assert "page.cloaking" not in ev
    assert ev["page.cross_origin_post"].observed["exfil_channel"] is True
    assert ev["page.cross_origin_post"].hard_rule == "H4"
    assert ev["brand.claimed_not_owned"].hard_rule == "H1"
    d = f.profiles["desktop_en"]
    assert {"password", "card", "cvv", "otp"} <= {k for fm in d.forms for k in fm.sensitive_kinds}
    assert d.favicon.sha256 and d.screenshot_phash and d.dom_simhash
    assert len(d.visible_text.encode()) <= 4096


def test_official_fixture_has_no_phish_evidence() -> None:
    f = render("http://falcon-demo-bank.test/")
    sig = signals(f)
    assert not sig & {
        "page.cred_form",
        "page.cross_origin_post",
        "page.hotlinked_brand_assets",
        "page.cloaking",
        "brand.claimed_not_owned",
    }
    login = signals(render("http://falcon-demo-bank.test/login"))
    assert "page.cred_form" in login and "page.cross_origin_post" not in login


def test_cloaked_fixture() -> None:
    f = render("http://falcon-demo-bank-cloak.test/")
    assert f.cloaking.diff, f.cloaking
    assert "page.cloaking" in signals(f)
    assert not any(fm.cred_form for fm in f.profiles["desktop_en"].forms)
    assert any(fm.cred_form for fm in f.profiles["mobile_ar"].forms)
    assert "emirates_id" in {k for fm in f.profiles["mobile_ar"].forms for k in fm.sensitive_kinds}


def test_smoke_paths_on_fixtures_host() -> None:
    assert "page.cred_form" in signals(render("http://fixtures/phish/"))
    assert not signals(render("http://fixtures/official/")) & {"page.cred_form"}


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest/meta-data/", "http://redis:6379/", "http://10.0.0.1/"])
def test_internal_targets_refused(url: str) -> None:
    status, body = call("/render", {"url": url})
    assert status == 400 and body["detail"]["error"] == "blocked"


def test_private_subresources_recorded_and_blocked() -> None:
    f = render("http://falcon-demo-bank.test/blocked-assets.html", profiles=["desktop_en"])
    blocked = f.profiles["desktop_en"].network.blocked
    assert {b.host for b in blocked} >= {"10.0.0.1", "169.254.169.254", "redis"}
    assert all(b.reason.startswith("ssrf_") for b in blocked)


def test_redirect_cap_stops_at_ten() -> None:
    f = render("http://falcon-demo-bank.test/redir/1", profiles=["desktop_en"])
    p = f.profiles["desktop_en"]
    assert p.network.redirect_limit_hit and p.error
    assert len(p.redirect_chain) - 1 <= 11


def test_never_submits_forms_or_posts() -> None:
    before = fixtures_log()
    f = render("http://falcon-demo-bank-secure.test/login")
    for p in f.profiles.values():
        assert p.network.non_get_sent == 0
        assert p.network.non_get_blocked >= 1  # the on-load beacon was attempted and blocked
        assert any(t.source == "dynamic" and t.exfil for t in p.script_post_targets)
    new = fixtures_log()[len(before) :]
    assert '"POST' not in new and "POST /" not in new


def test_capture_writes_private_snapshot() -> None:
    status, body = call("/capture", {"url": "http://falcon-demo-bank-secure.test/login"})
    assert status == 200 and set(body) >= {"snapshot_id", "dom_sha256", "screenshot_sha256"}
    assert "<html" not in json.dumps(body)
    out = subprocess.run(  # noqa: S603
        ["docker", "compose", "--profile", "core", "exec", "-T", "sandbox", "ls",  # noqa: S607
         f"/data/snapshots/{body['snapshot_id']}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert set(out.stdout.split()) == {
        "dom.html", "screenshot.png", "redirects.json", "network.json", "features.json"
    }  # fmt: skip
    assert (ROOT / "data/private/snapshots" / body["snapshot_id"] / "dom.html").exists()


def test_injection_fixture_text_is_data_only() -> None:
    f = render("http://falcon-demo-bank-injection.test/", profiles=["desktop_en"])
    text = f.profiles["desktop_en"].visible_text
    assert "Ignore all previous instructions" in text  # carried as untrusted data for the extractor
    assert "HIDDEN:" not in text  # display:none is not visible text
    assert signals(f) == set()


def test_phash_helper_importable() -> None:
    assert phash_from_gray32([[0.0] * 32 for _ in range(32)])
