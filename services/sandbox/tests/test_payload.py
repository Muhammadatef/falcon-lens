"""`page.cross_origin_post` is about the PAYLOAD (user-entered form data), not the destination.

Real Chromium against a loopback server with Falcon Demo Bank-style pages (each labelled TEST FIXTURE; nothing is
typed or submitted, the sandbox only watches what the page's own scripts try to send, and every POST is refused).
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from falcon_core.cascade.models import SandboxFeatures
from falcon_core.cascade.page import page_evidence
from falcon_core.security.ssrf import GuardPolicy
from falcon_core.signals.brands.registry import default_registry
from falcon_core.signals.page.features import ProfileFeatures, RenderFeatures
from falcon_sandbox.browser import SandboxBrowser
from falcon_sandbox.build import body_carries_form_data, body_field_names, build_dynamic_post_target
from falcon_sandbox.compat import to_flat
from falcon_sandbox.settings import Settings

LABEL = '<div class="fl-banner">TEST FIXTURE, not a real site / صفحة اختبار، ليست موقعاً حقيقياً</div>'
FORM = (
    '<form action="/nowhere" method="post"><input type="text" name="username" id="user">'
    '<input type="password" name="password" id="pw"><button>Sign in</button></form>'
)


def page(body: str, script: str) -> bytes:
    return (
        f"<!doctype html><html><head><meta charset=utf-8><title>Falcon Demo Bank</title></head>"
        f"<body>{LABEL}{body}<script>{script}</script></body></html>"
    ).encode()


XPOST = "fetch('http://localhost:'+location.port+'/g/collect',{method:'POST',body:'v=2&en=page_view'});"

PAGES = {
    # a credential page whose script sends the form values off to a collector (never triggered by a user here)
    "/steal": page(
        FORM,
        "fetch('/collect',{method:'POST',body:new URLSearchParams({user:document.getElementById('user').value,"
        "password:document.getElementById('pw').value})});",
    ),
    # only analytics-style beacons: no form fields in the body
    "/stats": page(
        "<p>Falcon Demo Bank news</p>",
        "fetch('/g/collect',{method:'POST',body:'v=2&tid=T-TEST&en=page_view&dl=home'});"
        "navigator.sendBeacon('/log',JSON.stringify({event:'view',ms:12}));",
    ),
    # the same analytics call sent to ANOTHER site (localhost vs 127.0.0.1), with and without a password field
    "/xlogin": page(FORM, XPOST),
    "/xstats": page("<p>Falcon Demo Bank news</p>", XPOST),
    # a login page that ALSO has analytics: form fields exist, the beacon does not carry them
    "/login-stats": page(FORM, "fetch('/g/collect',{method:'POST',body:'v=2&en=page_view'});"),
}


class _H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None: ...

    def do_GET(self) -> None:  # noqa: N802
        body = PAGES.get(self.path.split("?")[0])
        self.send_response(200 if body else 404)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body or b"")))
        self.end_headers()
        self.wfile.write(body or b"")


class _S(Settings):
    port: int = 0

    @property
    def guard(self) -> GuardPolicy:
        return GuardPolicy(
            allowed_ports=frozenset({80, 443, self.port}),
            allow_hosts=frozenset({"127.0.0.1"}),
            allow_host_ips=frozenset({"127.0.0.1"}),
        )


@pytest.fixture
def base() -> Iterator[str]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
async def sandbox(tmp_path: Path, base: str) -> AsyncIterator[SandboxBrowser]:
    s = _S(snapshot_dir=tmp_path)
    s.port = int(base.rsplit(":", 1)[1])
    sb = SandboxBrowser(s)
    try:
        await sb.start()
        await sb._get_browser()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"chromium unavailable: {exc}")
    sb._active -= 1
    yield sb
    await sb.stop()


async def test_script_post_with_form_values_carries_form_data(base: str, sandbox: SandboxBrowser) -> None:
    f = (await sandbox.visit(f"{base}/steal", "desktop_en")).features
    assert f.network.non_get_blocked >= 1 and f.network.non_get_sent == 0  # refused, never sent
    assert f.script_post_targets and all(t.carries_form_data for t in f.script_post_targets)
    assert all(t.basis == "payload" for t in f.script_post_targets)  # the body carried field names: not the rule


async def test_analytics_style_beacons_do_not_carry_form_data(base: str, sandbox: SandboxBrowser) -> None:
    for path in ("/stats", "/login-stats"):
        f = (await sandbox.visit(f"{base}{path}", "desktop_en")).features
        assert f.script_post_targets, path  # still recorded, so nothing is hidden
        assert not any(t.carries_form_data for t in f.script_post_targets), path


def test_body_field_names_never_keep_values() -> None:
    assert body_field_names('{"a":{"password":"x"},"b":1}') == ["a", "password", "b"]
    assert body_field_names("user=u&otp=1&x=") == ["user", "otp", "x"]
    assert body_field_names(
        '--b\r\nContent-Disposition: form-data; name="card"\r\n\r\n4\r\n', "multipart/form-data"
    ) == ["card"]
    assert body_field_names(None) == [] and body_field_names("") == []


def test_payload_rule() -> None:
    assert body_carries_form_data(["v", "tid", "en"], set()) is False
    assert body_carries_form_data(["password"], set()) is True  # credential-like name
    assert body_carries_form_data(["otp_code"], set()) is True
    assert body_carries_form_data(["acct"], {"acct"}) is True  # the page's own field name
    assert body_carries_form_data(["event", "ms"], {"user", "pw1"}) is False


def test_known_bot_endpoint_always_counts() -> None:
    t = build_dynamic_post_target(
        "hxxps://api[.]telegram[.]org/bot123456:ABCdef-ghi/sendMessage".replace("hxxp", "http").replace("[.]", "."),
        "fetch",
        "http://a.test/",
    )
    assert t is not None and t.exfil and t.carries_form_data and t.cross_origin


def _flat(targets: list[Any]) -> dict[str, Any]:
    p = ProfileFeatures(profile="desktop_en", requested_url="http://a.test/", final_url="http://a.test/")
    p.script_post_targets = targets
    return to_flat(RenderFeatures(url="http://a.test/", profiles={"desktop_en": p}, elapsed_ms=1))


def _t(origin: str, carries: bool) -> Any:
    from falcon_core.signals.page.features import PostTarget

    return PostTarget(origin=origin, kind="fetch", source="dynamic", cross_origin=True, carries_form_data=carries)


def _signals(flat: dict[str, Any]) -> dict[str, Any]:
    ev = page_evidence(SandboxFeatures.model_validate(flat), "a.test", default_registry())
    return {e.signal: e for e in ev}


def test_beacons_become_informational_evidence_not_cross_origin_post() -> None:
    sig = _signals(_flat([_t("https://stats.example.test", False), _t("https://px.example.test", False)]))
    assert "page.cross_origin_post" not in sig
    assert sig["page.telemetry_beacon"].observed["count"] == 2


def test_form_data_post_is_cross_origin_post() -> None:
    sig = _signals(_flat([_t("https://collector.example.test", True), _t("https://stats.example.test", False)]))
    assert sig["page.cross_origin_post"].observed["credentials"] is False
    assert "hxxps://collector[.]example[.]test" in sig["page.cross_origin_post"].observed["targets"]
    assert "page.telemetry_beacon" in sig


async def test_cross_site_script_post_on_a_credential_page_always_counts(base: str, sandbox: SandboxBrowser) -> None:
    """Fail closed: with a password field on the page, an innocent-looking cross-site POST still counts;
    without one, the body analysis decides and an analytics-style beacon does not."""
    login = (await sandbox.visit(f"{base}/xlogin", "desktop_en")).features
    assert any(x.cred_form for x in login.forms)
    cross = [t for t in login.script_post_targets if t.cross_origin]
    assert cross and all(t.carries_form_data and t.basis == "credential_page_rule" for t in cross)
    stats = (await sandbox.visit(f"{base}/xstats", "desktop_en")).features
    cross = [t for t in stats.script_post_targets if t.cross_origin]
    assert cross and not any(t.carries_form_data for t in cross)


def test_flat_view_lists_only_rule_only_origins_as_credential_rule_origins() -> None:
    from falcon_core.signals.page.features import PostTarget

    def tgt(origin: str, basis: str | None) -> Any:
        return PostTarget(
            origin=origin, kind="fetch", source="dynamic", cross_origin=True, carries_form_data=True, basis=basis
        )

    flat = _flat(
        [
            tgt("https://rule-only.example.test", "credential_page_rule"),
            tgt("https://both.example.test", "credential_page_rule"),
            tgt("https://both.example.test", "payload"),
            tgt("https://relay.example.test", "relay"),
        ]
    )
    assert flat["credential_rule_origins"] == ["https://rule-only.example.test"]
    assert set(flat["post_targets"]) >= {"https://both.example.test", "https://relay.example.test"}
