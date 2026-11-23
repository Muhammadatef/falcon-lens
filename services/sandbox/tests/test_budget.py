"""Size and time budgets: a big or slow real-world page is still evidence, never a bare failure.

Real Chromium against a loopback server that serves generated pages in the style of the invented brand
"Falcon Demo Bank" (each carries the visible TEST FIXTURE label; the form posts nowhere). Limits are
patched down so the tests stay fast; the production values are pinned separately in
``test_production_limits``. Skipped when no Chromium is installed.
"""

from __future__ import annotations

import contextlib
import http.server
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from falcon_core.security.ssrf import GuardPolicy
from falcon_sandbox import browser as browser_mod
from falcon_sandbox import policy
from falcon_sandbox.browser import SandboxBrowser
from falcon_sandbox.settings import Settings

LABEL = '<div class="fl-banner">TEST FIXTURE, not a real site / صفحة اختبار، ليست موقعاً حقيقياً</div>'
FORM = (
    '<form action="/nowhere" method="post"><label>Username <input type="text" name="username"></label>'
    '<label>Password <input type="password" name="password"></label><button type="submit">Sign in</button></form>'
)


def page(title: str, body: str, tail: str = "") -> bytes:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title} - Falcon Demo Bank</title></head>'
        f"<body>{LABEL}<h1>Falcon Demo Bank</h1>{body}{tail}</body></html>"
    ).encode()


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *_: object) -> None: ...

    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8", declared: int | None = None) -> None:
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body) if declared is None else declared))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/big":  # login form first, then a long comment: the main document is over the cap
            self._send(page("Big", FORM, "<!--" + "x" * 400_000 + "-->"))
        elif path == "/huge-declared":  # declares (and sends) more than the hard ceiling
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.send_header("content-length", str(policy.MAIN_DOC_HARD_BYTES + 1))
            self.end_headers()
            left = policy.MAIN_DOC_HARD_BYTES + 1
            with contextlib.suppress(OSError):
                while left > 0:
                    n = min(left, 1_000_000)
                    self.wfile.write(b" " * n)
                    left -= n
        elif path == "/many-images":  # sub-resources add up past the (patched) budget
            imgs = "".join(f'<img src="/img/{i}.png" width="10" height="10">' for i in range(6))
            self._send(page("Images", FORM, imgs))
        elif path.startswith("/img/"):
            self._send(b"\x89PNG" + b"0" * 150_000, "image/png")
        elif path == "/hang-after-form":  # the form is parsed, then a script that never answers
            self._send(page("Slow script", FORM, '<script src="/hang.js"></script>'))
        elif path in ("/hang.js", "/slow-doc"):  # /slow-doc: the main document is slower than the whole budget
            time.sleep(30)
        elif path == "/favicon.ico":
            self.send_response(404)
            self.end_headers()
        else:
            self._send(page("Home", FORM))


class _Settings(Settings):
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
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
async def sandbox(tmp_path: Path, base: str) -> AsyncIterator[SandboxBrowser]:
    settings = _Settings(snapshot_dir=tmp_path)
    settings.port = int(base.rsplit(":", 1)[1])
    sb = SandboxBrowser(settings)
    try:
        await sb.start()
        await sb._get_browser()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"chromium unavailable: {exc}")
    sb._active -= 1
    yield sb
    await sb.stop()


def test_production_limits() -> None:
    """The documented values (docs/ARCHITECTURE.md#sandbox). Changing one is a design decision."""
    assert policy.TOTAL_TIMEOUT_S == 6.0
    assert policy.NAV_BUDGET_S < policy.TOTAL_TIMEOUT_S
    assert policy.TOTAL_TIMEOUT_S + browser_mod.HARD_TIMEOUT_GRACE_S < 7.0  # the worker waits 7 s
    assert policy.MAX_TOTAL_BYTES == 5 * 1024 * 1024  # sub-resource cap is unchanged
    assert policy.MAIN_DOC_MAX_BYTES == 8 * 1024 * 1024
    assert policy.MAIN_DOC_HARD_BYTES == 32 * 1024 * 1024
    assert Settings().max_concurrent >= 6  # one check = two profiles; three checks must not queue


async def test_big_main_document_is_cut_not_failed(
    base: str, sandbox: SandboxBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_mod, "MAIN_DOC_MAX_BYTES", 100_000)
    f = (await sandbox.visit(f"{base}/big", "desktop_en")).features
    assert f.error is None and f.status == 200
    assert f.network.truncated and f.network.doc_bytes == 100_000
    assert "Big" in f.title
    assert any(x.cred_form for x in f.forms)  # the part we kept still carries the evidence


async def test_main_document_under_cap_is_not_flagged(base: str, sandbox: SandboxBrowser) -> None:
    f = (await sandbox.visit(f"{base}/big", "desktop_en")).features
    assert f.error is None and not f.network.truncated and not f.network.size_cap_hit


async def test_declared_size_over_hard_ceiling_is_refused(base: str, sandbox: SandboxBrowser) -> None:
    f = (await sandbox.visit(f"{base}/huge-declared", "desktop_en")).features
    assert f.error == "size_cap" and f.final_url is None


async def test_subresource_budget_does_not_fail_the_page(
    base: str, sandbox: SandboxBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_mod, "MAX_TOTAL_BYTES", 300_000)
    f = (await sandbox.visit(f"{base}/many-images", "desktop_en")).features
    assert f.error is None and f.status == 200 and f.title
    assert f.network.size_cap_hit and not f.network.truncated
    assert any(b.reason == "size_cap" for b in f.network.blocked)


async def test_hung_subresource_times_out_alone(
    base: str, sandbox: SandboxBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_mod, "SUBRESOURCE_TIMEOUT_S", 0.6)
    t0 = time.monotonic()
    f = (await sandbox.visit(f"{base}/hang-after-form", "desktop_en")).features
    assert f.error is None and not f.network.partial and f.network.dcl_ms is not None
    assert any(x.cred_form for x in f.forms)
    assert time.monotonic() - t0 < policy.TOTAL_TIMEOUT_S


async def test_slow_script_gives_partial_features_within_budget(
    base: str, sandbox: SandboxBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DOMContentLoaded never arrives inside the navigation budget: extract what loaded, mark it partial."""
    monkeypatch.setattr(browser_mod, "SUBRESOURCE_TIMEOUT_S", 30.0)
    monkeypatch.setattr(browser_mod, "NAV_BUDGET_S", 1.5)
    monkeypatch.setattr(browser_mod, "TOTAL_TIMEOUT_S", 3.0)
    t0 = time.monotonic()
    out = await sandbox.visit(f"{base}/hang-after-form", "desktop_en")
    f = out.features
    assert time.monotonic() - t0 < 3.0 + browser_mod.HARD_TIMEOUT_GRACE_S
    assert f.error is None and not f.timed_out
    assert f.network.partial and f.network.dcl_ms is None
    assert f.final_url == f"{base}/hang-after-form" and "Slow script" in f.title
    assert any(x.cred_form for x in f.forms)
    assert f.network.pending_hosts == ["127.0.0.1"]


async def test_slow_main_document_is_still_a_timeout(
    base: str, sandbox: SandboxBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_mod, "NAV_BUDGET_S", 1.0)
    monkeypatch.setattr(browser_mod, "TOTAL_TIMEOUT_S", 2.0)
    t0 = time.monotonic()
    f = (await sandbox.visit(f"{base}/slow-doc", "desktop_en")).features
    assert f.error == "timeout" and f.timed_out and f.final_url is None
    assert time.monotonic() - t0 < 2.0 + browser_mod.HARD_TIMEOUT_GRACE_S


async def test_visit_never_posts(base: str, sandbox: SandboxBrowser) -> None:
    f = (await sandbox.visit(f"{base}/big", "desktop_en")).features
    assert f.network.non_get_sent == 0
