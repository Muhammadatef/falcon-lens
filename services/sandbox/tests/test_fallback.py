"""Retry + static fallback: a render that fails after the target answered is still read (no JavaScript), a policy
block or NXDOMAIN is final, and nothing is ever submitted.

Real Chromium against a loopback server serving the Falcon Demo Bank fixtures (invented brand, labelled TEST FIXTURE).
Skipped when no Chromium is installed.
"""

from __future__ import annotations

import http.server
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from falcon_core.security.ssrf import GuardPolicy
from falcon_sandbox.browser import SandboxBrowser
from falcon_sandbox.policy import RequestPolicy, fallback_allowed, is_transient
from falcon_sandbox.settings import Settings
from falcon_sandbox.static import StaticFetchError, extract_static, fetch_main_document

FIXTURES = Path(__file__).resolve().parents[3] / "services/fixtures/sites"
PHISH = (FIXTURES / "phish/login.html").read_text()
OFFICIAL = (FIXTURES / "official/login.html").read_text()
HANG = "<script>for(;;){}</script>"  # a page that never lets the renderer reach DOMContentLoaded
PHISH_HANG = PHISH.replace("<head>", "<head>" + HANG, 1)
SLOW_SCRIPT_PAGE = OFFICIAL.replace("<head>", '<head><script src="/hang.js"></script>', 1)


class _H(http.server.BaseHTTPRequestHandler):
    hits: dict[str, int] = {}
    posts = 0

    def log_message(self, *_: object) -> None: ...

    def _html(self, body: str, status: int = 200) -> None:
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        type(self).posts += 1
        self._html("posted", 200)

    def do_GET(self) -> None:  # noqa: N802
        p = self.path
        _H.hits[p] = _H.hits.get(p, 0) + 1
        if p == "/phish-hang":
            self._html(PHISH_HANG)
        elif p == "/official-hang":
            self._html(OFFICIAL.replace("<head>", "<head>" + HANG, 1))
        elif p == "/slow-script":
            self._html(SLOW_SCRIPT_PAGE)
        elif p == "/hang.js":
            time.sleep(9)
        elif p == "/flaky":  # first request: the connection is reset; the retry gets the page
            if _H.hits[p] == 1:
                self.connection.close()
                return
            self._html(OFFICIAL)
        elif p == "/reset":
            self.connection.close()
        elif p == "/to-private":
            self.send_response(302)
            self.send_header("Location", "http://10.255.255.1/internal")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif p == "/hang-nothing":
            time.sleep(9)
        elif p == "/image":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(b"abc")
        else:
            self._html(OFFICIAL)


class _Loopback(Settings):
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
    _H.hits, _H.posts = {}, 0
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def settings(tmp_path: Path, base: str) -> _Loopback:
    s = _Loopback(snapshot_dir=tmp_path, allow_hosts=frozenset({"127.0.0.1"}))
    s.port = int(base.rsplit(":", 1)[1])
    return s


@pytest.fixture
async def sandbox(settings: _Loopback) -> AsyncIterator[SandboxBrowser]:
    sb = SandboxBrowser(settings)
    try:
        await sb.start()
        await sb._get_browser()
        sb._active -= 1
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"chromium unavailable: {exc}")
    yield sb
    await sb.stop()


# --- pure ---------------------------------------------------------------------------------------------------------


def test_error_classes_policy_blocks_and_nxdomain_are_final() -> None:
    for e in ("timeout", "connect_failed", "navigation_failed:net::ERR_X", "fetch_failed", "browser_error:crash"):
        assert is_transient(e) and fallback_allowed(e), e
    for e in (
        "dns_failure",
        "blocked_by_policy:ssrf_private_ip",
        "blocked_by_policy",
        "egress_blocked",
        "tls_error",
        "size_cap",
        "too_many_redirects",
        "http_403_empty",
        None,
    ):
        assert not is_transient(e) and not fallback_allowed(e), e


def test_static_extraction_finds_credential_form_brand_and_relay_without_running_anything() -> None:
    raw = extract_static(PHISH, "http://falcon-demo-bank-secure.test/login")
    assert "Falcon Demo Bank" in raw["title"] and "Falcon Demo Bank" in raw["text"]
    kinds = {f["type"] for fm in raw["forms"] for f in fm["fields"]}
    assert "password" in kinds
    assert raw["forms"][0]["action"].startswith("http://falcon-bot-relay.test/bot")
    assert any("falcon-bot-relay.test" in t["url"] for t in raw["typed"])
    assert raw["js"]["eval_calls"] >= 1 and raw["js"]["atob_calls"] >= 1
    assert "exfil(" not in raw["text"]  # script text never leaks into the visible text
    assert raw["favicon"].endswith("/assets/favicon.png")


async def test_fetch_is_get_only_revalidates_every_hop_and_never_posts(base: str, settings: _Loopback) -> None:
    pol = RequestPolicy(settings.guard)
    doc = await fetch_main_document(settings, pol, f"{base}/x", "desktop_en", 2.0)
    assert doc.status == 200 and b"Falcon Demo Bank" in doc.body and _H.posts == 0
    with pytest.raises(StaticFetchError) as ei:
        await fetch_main_document(settings, pol, f"{base}/to-private", "desktop_en", 2.0)
    assert ei.value.code.startswith("blocked_by_policy:ssrf_")
    with pytest.raises(StaticFetchError) as ei2:
        await fetch_main_document(settings, pol, "http://169.254.169.254/latest/", "desktop_en", 2.0)
    assert ei2.value.code.startswith("blocked_by_policy:ssrf_")


# --- real browser -------------------------------------------------------------------------------------------------


async def test_page_that_hangs_the_renderer_is_caught_via_static_fallback(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/phish-hang", "desktop_en")
    f = out.features
    assert f.error is None, f.error
    n = f.network
    assert n.static_fallback and n.partial and n.static_source == "captured" and n.fallback_reason
    assert f.final_url and f.final_url.endswith("/phish-hang") and f.status == 200
    assert any(fm.cred_form for fm in f.forms)  # the credential form is still seen
    assert any(t.exfil for t in f.script_post_targets) or any(fm.action_exfil for fm in f.forms)
    assert "Falcon Demo Bank" in f.title
    assert out.screenshot is None and f.screenshot_phash is None and f.favicon.sha256 is None
    assert n.non_get_sent == 0 and _H.posts == 0


async def test_static_fallback_is_never_cloaking_evidence(base: str, sandbox: SandboxBrowser) -> None:
    from falcon_core.signals.page.cloaking import compare_profiles

    a = await sandbox.visit(f"{base}/phish-hang", "mobile_ar")
    b = await sandbox.visit(f"{base}/phish-hang", "desktop_en")
    c = compare_profiles(a.features, b.features)
    assert c.inconclusive and not c.diff


async def test_slow_subresource_page_is_not_a_failure(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/slow-script", "desktop_en")
    f = out.features
    assert f.error is None, f.error
    assert f.final_url is not None and "Falcon Demo Bank" in f.title


async def test_transient_connection_reset_gets_one_retry(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/flaky", "desktop_en")
    f = out.features
    assert f.error is None, f.error
    assert f.network.attempts == 2 and not f.network.static_fallback
    assert "Falcon Demo Bank" in f.title


async def test_unanswering_target_stays_a_failure_with_a_bounded_retry(base: str, sandbox: SandboxBrowser) -> None:
    t0 = time.monotonic()
    out = await sandbox.visit(f"{base}/reset", "desktop_en")
    f = out.features
    assert f.error is not None and f.final_url is None and not f.network.static_fallback
    assert f.network.attempts <= 2
    assert time.monotonic() - t0 < 7.0  # the worker's wait


async def test_target_that_never_answers_times_out_inside_the_overall_budget(
    base: str, sandbox: SandboxBrowser
) -> None:
    t0 = time.monotonic()
    out = await sandbox.visit(f"{base}/hang-nothing", "desktop_en")
    assert out.features.error == "timeout" and out.features.final_url is None
    assert time.monotonic() - t0 < 7.0
    assert out.features.network.static_fallback is False


async def test_policy_blocked_target_stays_blocked_no_retry_no_fallback(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/to-private", "desktop_en")
    f = out.features
    assert f.error is not None and f.error.startswith("blocked_by_policy:ssrf_"), f.error
    assert f.final_url is None and f.title == "" and f.forms == []
    assert f.network.attempts == 1 and not f.network.static_fallback
    assert _H.hits.get("/to-private") == 1  # not fetched a second time


async def test_non_html_answer_is_not_read_statically(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/image", "desktop_en")
    assert not out.features.network.static_fallback
