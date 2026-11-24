from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from falcon_core.security import GuardPolicy
from falcon_core.signals.page.features import ProfileFeatures
from falcon_sandbox.main import build_app
from falcon_sandbox.policy import ByteBudget, RequestPolicy, check_target
from falcon_sandbox.settings import Settings
from falcon_sandbox.storage import SnapshotStore

FIXTURE_HOSTS = frozenset({"falcon-demo-bank.test", "falcon-bot-relay.test", "fixtures"})
POLICY = RequestPolicy(GuardPolicy(allow_hosts=FIXTURE_HOSTS))


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://redis:6379/",
        "http://10.0.0.1/a.png",
        "http://127.0.0.1/",
        "http://localhost/",
        "http://[::1]/",
        "http://2130706433/",
        "http://evil@10.0.0.1/",
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://example.com:22/",
        "http://falcon-demo-bank.test:6379/",
        "http://some-internal-host.test/",
    ],
)
def test_refused_targets(url: str) -> None:
    assert check_target(url, POLICY.guard) is not None
    assert not POLICY.decide(url, "GET", "document").allow


def test_public_and_fixture_hosts_allowed() -> None:
    assert POLICY.decide("https://example.com/", "GET", "document").allow
    assert POLICY.decide("http://falcon-demo-bank.test/assets/logo.png", "GET", "image").allow
    assert POLICY.decide("data:image/png;base64,AAAA", "GET", "image").allow


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
def test_never_sends_non_get(method: str) -> None:
    d = POLICY.decide("http://falcon-bot-relay.test/bot1:x/sendMessage", method, "fetch")
    assert not d.allow and d.reason == "method_not_get"


def test_fonts_media_blocked_unless_visual() -> None:
    assert not POLICY.decide("https://example.com/f.woff2", "GET", "font").allow
    assert not POLICY.decide("https://example.com/v.mp4", "GET", "media").allow
    visual = RequestPolicy(POLICY.guard, visual=True)
    assert visual.decide("https://example.com/f.woff2", "GET", "font").allow
    assert not visual.decide("wss://example.com/s", "GET", "websocket").allow


def test_redirect_cap() -> None:
    assert POLICY.decide("https://example.com/", "GET", "document", redirect_depth=10).allow
    d = POLICY.decide("https://example.com/", "GET", "document", redirect_depth=11)
    assert not d.allow and d.reason == "too_many_redirects"


def test_byte_budget() -> None:
    b = ByteBudget(5 * 1024 * 1024)
    assert not b.add(5 * 1024 * 1024)
    assert b.add(1)


def test_snapshot_store_private_files(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    sid, dom_sha, shot_sha = store.save_snapshot(
        dom="<html></html>",
        screenshot=b"\x89PNG",
        redirects=[{"url": "http://x", "status": 200}],
        network={"requests": 1},
        features={"a": 1},
    )
    d = tmp_path / sid
    assert sid == dom_sha and shot_sha
    assert {p.name for p in d.iterdir()} == {
        "dom.html",
        "screenshot.png",
        "redirects.json",
        "network.json",
        "features.json",
    }
    assert (d / "dom.html").stat().st_mode & 0o077 == 0
    assert store.save_screenshot(b"abc") == store.save_screenshot(b"abc")


class _FakeBrowser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def ready(self) -> bool:
        return True

    async def visit(self, url: str, profile: str, **_: Any) -> Any:
        from falcon_sandbox.browser import VisitResult

        self.calls.append((url, profile))
        return VisitResult(
            ProfileFeatures(profile=profile, requested_url=url, final_url=url, status=200)  # type: ignore[arg-type]
        )


def _client(tmp_path: Path) -> tuple[TestClient, _FakeBrowser]:
    fake = _FakeBrowser()
    settings = Settings(allow_hosts=FIXTURE_HOSTS, snapshot_dir=tmp_path, api_key="k")
    return TestClient(build_app(settings, fake)), fake  # type: ignore[arg-type]


def test_render_requires_key(tmp_path: Path) -> None:
    c, fake = _client(tmp_path)
    with c:
        assert c.post("/render", json={"url": "https://example.com/"}).status_code == 401
        assert (
            c.post("/render", json={"url": "https://example.com/"}, headers={"x-sandbox-key": "no"}).status_code == 401
        )
        assert fake.calls == []


@pytest.mark.parametrize("url", ["http://169.254.169.254/", "http://redis:6379/", "http://10.0.0.1/"])
def test_render_refuses_internal_targets(tmp_path: Path, url: str) -> None:
    c, fake = _client(tmp_path)
    with c:
        for path in ("/render", "/capture"):
            r = c.post(path, json={"url": url}, headers={"x-sandbox-key": "k"})
            assert r.status_code == 400 and r.json()["detail"]["error"] == "blocked"
    assert fake.calls == []  # the browser is never even asked


def test_render_returns_features_only(tmp_path: Path) -> None:
    c, fake = _client(tmp_path)
    with c:
        r = c.post(
            "/render",
            json={"url": "https://example.com/", "verdict_id": "vd_1"},
            headers={"x-sandbox-key": "k"},
        )
    assert r.status_code == 200
    body = r.json()
    # per-profile detail validates against the strict model (extra="forbid": no raw HTML keys)
    profiles = {k: ProfileFeatures.model_validate(v) for k, v in body["profiles"].items()}
    assert set(profiles) == {"mobile_ar", "desktop_en"}
    # flat keys the cascade's SandboxFeatures reads
    flat = {"redirect_chain", "final_url", "title", "forms", "post_targets", "hotlinked_origins"}
    flat |= {"visible_text", "favicon_sha256", "dom_simhash", "cloaking"}
    assert flat <= set(body)
    assert body["verdict_id"] == "vd_1" and "detected" in body["cloaking"]
    forbidden = {"html", "dom", "screenshot", "content", "body"}
    assert not forbidden & set(_all_keys(body))
    assert len(fake.calls) == 2


def _all_keys(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return [*obj, *(k for v in obj.values() for k in _all_keys(v))]
    if isinstance(obj, list):
        return [k for v in obj for k in _all_keys(v)]
    return []


def test_request_rejects_unknown_fields(tmp_path: Path) -> None:
    c, _ = _client(tmp_path)
    with c:
        r = c.post(
            "/render",
            json={"url": "https://example.com/", "submit": True},
            headers={"x-sandbox-key": "k"},
        )
    assert r.status_code == 422


def test_render_screenshot_readable_by_read_only_api_mount(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    sha = store.save_screenshot(b"\x89PNG-shot")
    f = tmp_path / "screens" / f"{sha}.png"
    assert f.read_bytes() == b"\x89PNG-shot"
    assert f.stat().st_mode & 0o777 == 0o644 and (tmp_path / "screens").stat().st_mode & 0o777 == 0o755
