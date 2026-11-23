"""Client-side (JS) redirects must not become navigation_failed.

Real Chromium against a loopback server that serves the Falcon Demo Bank fixture pages
(services/fixtures/sites/official, invented brand, labelled TEST FIXTURE). Skipped when no
Chromium is installed.
"""

from __future__ import annotations

import functools
import http.server
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from falcon_core.security.ssrf import GuardPolicy
from falcon_sandbox.browser import SandboxBrowser
from falcon_sandbox.settings import Settings

SITE = Path(__file__).resolve().parents[3] / "services/fixtures/sites/official"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_: object) -> None: ...

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/login":
            self.path = "/login.html"
        super().do_GET()


class _LoopbackSettings(Settings):
    """Test-only: the production guard plus ONE extra port and loopback for the fixture server."""

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
    handler = functools.partial(_Quiet, directory=str(SITE))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def interrupted_goto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chromium's race (a script redirect lands before goto resolves) is timing dependent, so
    reproduce its exact outcome: the real navigation (and the page's own redirect) happen, then
    goto reports the interruption the way Playwright does."""
    real_goto = Page.goto

    async def goto(self: Page, url: str, **kw: object) -> None:
        await real_goto(self, url, **kw)  # type: ignore[arg-type]
        await self.wait_for_load_state("domcontentloaded")
        raise PlaywrightError(f'Page.goto: Navigation to "{url}" is interrupted by another navigation to "{self.url}"')

    monkeypatch.setattr(Page, "goto", goto)


@pytest.fixture
async def sandbox(tmp_path: Path, base: str) -> AsyncIterator[SandboxBrowser]:
    settings = _LoopbackSettings(snapshot_dir=tmp_path)
    settings.port = int(base.rsplit(":", 1)[1])
    sb = SandboxBrowser(settings)
    try:
        await sb.start()
        await sb._get_browser()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"chromium unavailable: {exc}")
    yield sb
    await sb.stop()


async def test_client_redirect_renders_final_page(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/client-redirect.html", "desktop_en")
    f = out.features
    assert f.error is None
    assert f.final_url == f"{base}/login"
    assert "Sign in" in f.title


async def test_client_redirect_to_private_host_is_blocked(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/client-redirect-private.html", "desktop_en")
    assert out.features.error == "blocked_by_policy"


async def test_interrupted_navigation_is_not_a_failure(
    base: str, sandbox: SandboxBrowser, interrupted_goto: None
) -> None:
    out = await sandbox.visit(f"{base}/client-redirect.html", "desktop_en")
    f = out.features
    assert f.error is None
    assert f.final_url == f"{base}/login"


async def test_interrupted_navigation_to_blocked_host_fails_closed(
    base: str, sandbox: SandboxBrowser, interrupted_goto: None
) -> None:
    out = await sandbox.visit(f"{base}/client-redirect-private.html", "desktop_en")
    assert out.features.error == "blocked_by_policy"
