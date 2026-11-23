"""Integration tests against the compose stack (sandbox + egress-proxy + fixtures).

Run with the stack up (project name set, tools profile on):
  docker compose --profile core --profile tools up -d sandbox egress-proxy fixtures
  FL_INTEGRATION=1 uv run pytest -m integration services/sandbox/tests/test_integration.py

The sandbox is not published on the host (it only lives on internal networks), so requests are
issued from inside the sandbox container with ``docker compose exec``. Evidence is built by the
cascade's own ``page_evidence`` (the single evidence builder), fed with the sandbox response.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from falcon_core.cascade.models import SandboxFeatures
from falcon_core.cascade.page import page_evidence
from falcon_core.signals.brands.registry import default_registry
from falcon_core.signals.page.features import ProfileFeatures
from falcon_core.signals.page.hosts import host_of, registrable_domain

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
PHISH = "http://falcon-demo-bank-secure.test/login"


def call(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    out = subprocess.run(  # noqa: S603
        ["docker", "compose", "--profile", "core", "--profile", "tools", "exec", "-T", "sandbox",  # noqa: S607
         "python", "-c", CLIENT, path, json.dumps(payload)],
        cwd=ROOT, capture_output=True, text=True, timeout=90, check=True,
    )  # fmt: skip
    data = json.loads(out.stdout.strip().splitlines()[-1])
    return data["status"], data["body"]


def fixtures_log() -> str:
    return subprocess.run(  # noqa: S603
        ["docker", "compose", "--profile", "tools", "logs", "--no-log-prefix", "fixtures"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
    ).stdout  # fmt: skip


def favicons() -> dict[str, str]:
    data = (ROOT / "services/fixtures/sites/official/assets/favicon.png").read_bytes()
    return {hashlib.sha256(data).hexdigest(): "falcon_demo_bank"}


class Render:
    """A /render response: the flat cascade keys plus per-profile detail."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.profiles = {k: ProfileFeatures.model_validate(v) for k, v in body["profiles"].items()}
        self.cloaking: dict[str, Any] = body["cloaking"]

    def evidence(self, url: str) -> dict[str, Any]:
        feats = SandboxFeatures.model_validate(self.body)
        reg = registrable_domain(host_of(url))
        return {e.signal: e for e in page_evidence(feats, reg, default_registry(), favicons())}


def render(url: str, **kw: Any) -> Render:
    status, body = call("/render", {"url": url, "verdict_id": "vd_test", **kw})
    assert status == 200, body
    return Render(body)


def signals(url: str, **kw: Any) -> set[str]:
    return set(render(url, **kw).evidence(url))


def test_phish_fixture_evidence() -> None:
    r = render(PHISH)
    ev = r.evidence(PHISH)
    assert {
        "page.cred_form",
        "page.cross_origin_post",
        "page.hotlinked_brand_assets",
        "brand.claimed_not_owned",
        "visual.favicon_match_brand",
    } <= set(ev)
    assert "page.cloaking" not in ev
    assert ev["page.cross_origin_post"].observed["bot"] is True
    d = r.profiles["desktop_en"]
    assert {"password", "card", "cvv", "otp"} <= {k for fm in d.forms for k in fm.sensitive_kinds}
    assert d.favicon.sha256 and d.screenshot_phash and d.dom_simhash
    assert len(d.visible_text.encode()) <= 4096
    assert len(r.body["exfil_targets"]) == 1  # deduplicated


def test_official_fixture_has_no_phish_evidence() -> None:
    sig = signals("http://falcon-demo-bank.test/")
    assert not sig & {
        "page.cred_form",
        "page.cross_origin_post",
        "page.hotlinked_brand_assets",
        "page.cloaking",
        "brand.claimed_not_owned",
    }
    login = signals("http://falcon-demo-bank.test/login")
    assert "page.cred_form" in login and "page.cross_origin_post" not in login


def test_cloaked_fixture() -> None:
    url = "http://falcon-demo-bank-cloak.test/"
    r = render(url)
    assert r.cloaking["detected"], r.cloaking
    assert "page.cloaking" in r.evidence(url)
    assert not any(fm.cred_form for fm in r.profiles["desktop_en"].forms)
    assert any(fm.cred_form for fm in r.profiles["mobile_ar"].forms)
    assert "emirates_id" in {k for fm in r.profiles["mobile_ar"].forms for k in fm.sensitive_kinds}


def test_smoke_paths_on_fixtures_host() -> None:
    assert "page.cred_form" in signals("http://fixtures/phish/")
    assert "page.cred_form" not in signals("http://fixtures/official/")


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest/meta-data/", "http://redis:6379/", "http://10.0.0.1/"])
def test_internal_targets_refused(url: str) -> None:
    status, body = call("/render", {"url": url})
    assert status == 400 and body["detail"]["error"] == "blocked"


def test_private_subresources_recorded_and_blocked() -> None:
    r = render("http://falcon-demo-bank.test/blocked-assets.html", profiles=["desktop_en"])
    blocked = r.profiles["desktop_en"].network.blocked
    assert {b.host for b in blocked} >= {"10.0.0.1", "169.254.169.254", "redis"}
    assert all(b.reason.startswith("ssrf_") for b in blocked)


def test_redirect_cap_stops_at_ten() -> None:
    r = render("http://falcon-demo-bank.test/redir/1", profiles=["desktop_en"])
    p = r.profiles["desktop_en"]
    assert p.network.redirect_limit_hit and p.error == "too_many_redirects"
    assert r.body["final_url"] is None  # the cascade degrades instead of judging a half-followed chain
    assert len(p.redirect_chain) - 1 <= 11


def test_proxy_ssrf_denial_is_blocked_by_policy_with_reason() -> None:
    """localtest[.]me resolves to 127.0.0.1: it passes the sandbox's syntactic check and is denied by the
    egress proxy (403 + X-Falcon-Block-Reason), which must surface as blocked_by_policy:<reason>."""
    r = render("hxxp://localtest[.]me/".replace("hxxp", "http").replace("[.]", "."), profiles=["desktop_en"])
    assert r.body["error"].startswith("blocked_by_policy:"), r.body["error"]
    assert r.body["final_url"] is None


@pytest.mark.parametrize(
    "url",
    ["hxxps://localtest[.]me/", "hxxps://nonexistent-falcon-lens-test-host-8431[.]com/"],
)
def test_egress_refusal_or_dns_failure_is_an_error_not_an_empty_page(url: str) -> None:
    r = render(url.replace("hxxp", "http").replace("[.]", "."), profiles=["desktop_en"])
    assert r.body["error"].startswith("blocked_by_policy:"), r.body["error"]
    if "nonexistent" in url:
        assert r.body["error"] == "blocked_by_policy:dns_failure"  # proxy DNS failure stays hard (fail closed)
    assert r.body["final_url"] is None


def test_never_submits_forms_or_posts() -> None:
    before = fixtures_log()
    r = render(PHISH)
    for p in r.profiles.values():
        assert p.network.non_get_sent == 0
        assert p.network.non_get_blocked >= 1  # the on-load beacon was attempted and blocked
        assert any(t.source == "dynamic" and t.exfil for t in p.script_post_targets)
    new = fixtures_log()[len(before) :]
    assert '"POST' not in new and "POST /" not in new


def test_capture_writes_private_snapshot() -> None:
    status, body = call("/capture", {"url": PHISH})
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
    url = "http://falcon-demo-bank-injection.test/"
    r = render(url, profiles=["desktop_en"])
    text = r.profiles["desktop_en"].visible_text
    assert "Ignore all previous instructions" in text  # carried as untrusted data for the extractor
    assert "HIDDEN:" not in text  # display:none is not visible text
    assert set(r.evidence(url)) <= {"brand.claimed_not_owned"}
