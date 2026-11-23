"""Server-side (3xx) redirects of the main document: every hop is re-validated, a legitimate chain
renders, a hop to a private host stays blocked and the error always carries the reason.

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

from falcon_core.security.ssrf import GuardPolicy
from falcon_sandbox.browser import SandboxBrowser
from falcon_sandbox.settings import Settings

SITE = Path(__file__).resolve().parents[3] / "services/fixtures/sites/official"

# path -> (status, Location). Same-site hops, a path hop, a relative Location and a "cross-site" hop
# (localhost vs 127.0.0.1) are legitimate; /to-private and /to-metadata must stay blocked.
REDIRECTS = {
    "/apex": (301, "/www"),
    "/www": (302, "/login"),
    "/relative": (307, "login"),
    "/chain1": (301, "/chain2"),
    "/chain2": (302, "/chain3"),
    "/chain3": (301, "/chain4"),
    "/chain4": (302, "/login"),
    "/to-private": (302, "http://10.255.255.1/internal"),
    "/to-metadata": (301, "http://169.254.169.254/latest/meta-data/"),
    "/to-scheme": (302, "file:///etc/passwd"),
    "/to-port": (302, "http://127.0.0.1:22/"),
    "/loop": (302, "/loop"),
}


class _Handler(http.server.SimpleHTTPRequestHandler):
    cross: str = ""

    def log_message(self, *_: object) -> None: ...

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/cross":
            self.send_response(302)
            self.send_header("Location", f"{self.cross}/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path in REDIRECTS:
            status, loc = REDIRECTS[self.path]
            self.send_response(status)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/login":
            self.path = "/login.html"
        super().do_GET()


class _LoopbackSettings(Settings):
    port: int = 0

    @property
    def guard(self) -> GuardPolicy:
        return GuardPolicy(
            allowed_ports=frozenset({80, 443, self.port}),
            allow_hosts=frozenset({"127.0.0.1", "localhost"}),
            allow_host_ips=frozenset({"127.0.0.1"}),
        )


@pytest.fixture
def base() -> Iterator[str]:
    handler = functools.partial(_Handler, directory=str(SITE))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    _Handler.cross = f"http://localhost:{port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


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


@pytest.mark.parametrize("path", ["/apex", "/relative", "/chain1", "/cross"])
async def test_legitimate_redirect_chain_renders(base: str, sandbox: SandboxBrowser, path: str) -> None:
    for _ in range(3):  # the old failure was a race: repeat to make a regression visible
        out = await sandbox.visit(f"{base}{path}", "desktop_en")
        f = out.features
        assert f.error is None, f.error
        assert f.final_url is not None and f.final_url.endswith("/login")
        assert "Sign in" in f.title
        assert len(f.redirect_chain) >= 2
        assert f.client_navigations == []  # the inert hop stubs never leak as client navigations
        assert f.redirect_chain[0].status in (301, 302, 307)


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/to-private", "ssrf_"),
        ("/to-metadata", "ssrf_"),
        ("/to-scheme", "ssrf_"),
        ("/to-port", "ssrf_"),
    ],
)
async def test_redirect_to_forbidden_target_is_blocked_with_reason(
    base: str, sandbox: SandboxBrowser, path: str, reason: str
) -> None:
    out = await sandbox.visit(f"{base}{path}", "desktop_en")
    f = out.features
    assert f.final_url is None
    assert f.error is not None and f.error.startswith(f"blocked_by_policy:{reason}"), f.error
    assert f.title == "" and f.forms == []


async def test_redirect_loop_is_capped(base: str, sandbox: SandboxBrowser) -> None:
    out = await sandbox.visit(f"{base}/loop", "desktop_en")
    assert out.features.error == "too_many_redirects"
    assert out.features.final_url is None
