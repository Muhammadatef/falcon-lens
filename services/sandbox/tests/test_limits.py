"""Caps, timeouts, error classification, production fail-closed and token handling."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from falcon_sandbox import browser as browser_mod
from falcon_sandbox.main import build_app
from falcon_sandbox.policy import (
    MAIN_DOC_HARD_BYTES,
    MAX_TOTAL_BYTES,
    ByteBudget,
    classify_fetch_error,
    declared_length,
    proxy_refusal,
)
from falcon_sandbox.settings import Settings

HOSTS = "falcon-demo-bank.test,fixtures"


# ---- 5 MB cap: decided from Content-Length BEFORE the body is read ------------------------------


def test_declared_length_over_cap_is_refused_before_reading() -> None:
    budget = ByteBudget(MAX_TOTAL_BYTES)
    assert declared_length({"Content-Length": str(MAX_TOTAL_BYTES + 1)}) == MAX_TOTAL_BYTES + 1
    assert budget.would_exceed(MAX_TOTAL_BYTES + 1)
    assert not budget.would_exceed(MAX_TOTAL_BYTES)
    budget.add(MAX_TOTAL_BYTES - 10)  # cumulative: earlier responses count too
    assert budget.would_exceed(11) and not budget.would_exceed(10)


def test_declared_length_missing_or_garbage() -> None:
    assert declared_length({}) is None
    assert declared_length({"content-length": "abc"}) is None


class _FakeResp:
    status = 200

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.body_read = False

    async def body(self) -> bytes:
        self.body_read = True
        return b"x"


async def test_handler_never_reads_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive the real route handler with a fake route: the body must stay unread and the
    request aborted when the main document's Content-Length is over the hard ceiling."""
    resp = _FakeResp({"content-length": str(MAIN_DOC_HARD_BYTES + 1), "content-type": "text/html"})
    aborted: list[str] = []

    class Req:
        url = "http://falcon-demo-bank.test/big"
        method = "GET"
        resource_type = "document"

        def is_navigation_request(self) -> bool:
            return True

        class frame:  # noqa: N801
            parent_frame = None

    class Route:
        request = Req()

        async def fetch(self, **_: Any) -> _FakeResp:
            return resp

        async def abort(self, reason: str) -> None:
            aborted.append(reason)

        async def fulfill(self, **_: Any) -> None:
            raise AssertionError("must not fulfil an oversized response")

    handlers: list[Any] = []

    class Ctx:
        async def route(self, _pattern: str, handler: Any) -> None:
            handlers.append(handler)

        async def route_web_socket(self, *_: Any) -> None: ...

        async def new_page(self) -> Any:
            raise RuntimeError("stop after the handler is registered")

        def on(self, *_: Any) -> None: ...

    sb = browser_mod.SandboxBrowser(Settings(allow_hosts=frozenset({"falcon-demo-bank.test"})))
    with pytest.raises(RuntimeError, match="stop after"):
        await sb._visit(Ctx(), "http://falcon-demo-bank.test/big", "desktop_en", False, False)  # type: ignore[arg-type]
    await handlers[0](Route())
    assert aborted == ["blockedbyclient"] and not resp.body_read


# ---- egress failures become `error`, never an empty page ----------------------------------------


@pytest.mark.parametrize(
    ("msg", "code"),
    [
        ("getaddrinfo ENOTFOUND nope.example", "dns_failure"),
        ("net::ERR_NAME_NOT_RESOLVED", "dns_failure"),
        ("tunneling socket could not be established, statusCode=403", "egress_blocked"),
        ("Proxy responded 407", "egress_blocked"),
        ("connect ECONNREFUSED 10.1.2.3:443", "connect_failed"),
        ("Timeout 6000ms exceeded", "timeout"),
        ("self signed certificate", "tls_error"),
        ("something else entirely", "fetch_failed"),
    ],
)
def test_classify_fetch_error(msg: str, code: str) -> None:
    assert classify_fetch_error(msg) == code


def test_proxy_refusal_is_an_error_not_a_blank_page() -> None:
    assert proxy_refusal(405, {}, 0, via_proxy=True) == "egress_blocked"
    assert proxy_refusal(502, {}, 0, via_proxy=True) == "egress_error"
    # a real page that happens to be 403 has a body / content type; fixtures bypass the proxy
    assert proxy_refusal(403, {"content-type": "text/html"}, 0, via_proxy=True) is None
    assert proxy_refusal(403, {}, 120, via_proxy=True) is None
    assert proxy_refusal(405, {}, 0, via_proxy=False) is None


def test_proxy_denial_is_blocked_by_policy_with_reason() -> None:
    h = {"X-Falcon-Block-Reason": "private_ip", "Connection": "close"}
    assert proxy_refusal(403, h, 0, via_proxy=True) == "blocked_by_policy:private_ip"
    assert proxy_refusal(403, {"x-falcon-block-reason": "metadata"}, 0, via_proxy=True) == "blocked_by_policy:metadata"


@pytest.mark.parametrize("value", ["", "  ", "Bad Reason!", "a" * 80, "x\u00e9", "a;b"])
def test_unparseable_block_reason_fails_closed(value: str) -> None:
    assert proxy_refusal(403, {"X-Falcon-Block-Reason": value}, 0, via_proxy=True) == "blocked_by_policy"


def test_target_empty_403_is_http_403_empty() -> None:
    assert proxy_refusal(403, {"Connection": "close"}, 0, via_proxy=True) == "http_403_empty"
    assert proxy_refusal(403, {"Server": "AkamaiGHost"}, 0, via_proxy=True) == "http_403_empty"


def test_other_target_errors_keep_their_codes() -> None:
    assert proxy_refusal(404, {}, 0, via_proxy=True) is None
    assert proxy_refusal(500, {}, 0, via_proxy=True) is None
    assert proxy_refusal(429, {}, 0, via_proxy=True) is None


# ---- total timeout ------------------------------------------------------------------------------


async def test_visit_enforces_total_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class Ctx:
        closed = False

        async def close(self) -> None:
            Ctx.closed = True

    class Browser:
        async def new_context(self, **_: Any) -> Ctx:
            return Ctx()

    sb = browser_mod.SandboxBrowser(Settings())

    async def get_browser() -> Any:
        sb._active += 1
        return Browser()

    async def slow_visit(*_: Any, **__: Any) -> Any:
        await asyncio.sleep(30)

    monkeypatch.setattr(sb, "_get_browser", get_browser)
    monkeypatch.setattr(sb, "_visit", slow_visit)
    monkeypatch.setattr(browser_mod, "TOTAL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(browser_mod, "HARD_TIMEOUT_GRACE_S", 0.1)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    out = await sb.visit("http://falcon-demo-bank.test/", "desktop_en")
    assert loop.time() - t0 < 2
    assert out.features.error == "timeout" and out.features.timed_out
    assert out.features.final_url is None
    assert Ctx.closed  # the context is always torn down


# ---- allow-list only in local/demo/ci; token handling ------------------------------------------


def _env(monkeypatch: pytest.MonkeyPatch, **kw: str | None) -> Settings:
    for k in ("FL_ENV", "FL_SSRF_ALLOW_HOSTS", "FL_SANDBOX_TOKEN", "FL_SANDBOX_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in kw.items():
        if v is not None:
            monkeypatch.setenv(k, v)
    return Settings.from_env()


@pytest.mark.parametrize("env", ["local", "demo", "ci"])
def test_allowlist_honoured_in_dev_envs(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    s = _env(monkeypatch, FL_ENV=env, FL_SSRF_ALLOW_HOSTS=HOSTS)
    assert s.allow_hosts == {"falcon-demo-bank.test", "fixtures"}


@pytest.mark.parametrize("env", ["production", "prod", "staging", "", "Production", None])
def test_allowlist_ignored_everywhere_else(monkeypatch: pytest.MonkeyPatch, env: str | None) -> None:
    s = _env(monkeypatch, FL_ENV=env, FL_SSRF_ALLOW_HOSTS=HOSTS)
    assert s.allow_hosts == frozenset()
    assert s.guard.allow_hosts == frozenset()


def test_token_has_no_api_key_fallback_and_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _env(monkeypatch, FL_SANDBOX_API_KEY="public-judge-key").api_key == ""
    assert _env(monkeypatch, FL_SANDBOX_TOKEN="  secret \n").api_key == "secret"
    assert _env(monkeypatch, FL_SANDBOX_TOKEN="   ").api_key == ""


class _Fake:
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def ready(self) -> bool:
        return True

    async def visit(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("must not be called without a valid token")


@pytest.mark.parametrize("token", ["", "   ", "\t\n"])
def test_empty_or_whitespace_token_fails_closed_with_503(tmp_path: Path, token: str) -> None:
    app = build_app(Settings(snapshot_dir=tmp_path, api_key=token), _Fake())  # type: ignore[arg-type]
    with TestClient(app) as c:
        for headers in ({}, {"x-sandbox-key": token}, {"authorization": f"Bearer {token}"}):
            r = c.post("/render", json={"url": "https://example.com/"}, headers=headers)
            assert r.status_code == 503
        assert c.get("/healthz").status_code == 200  # probes stay open


def test_wrong_token_is_401_and_bearer_works(tmp_path: Path) -> None:
    app = build_app(Settings(snapshot_dir=tmp_path, api_key="s3cret"), _Fake())  # type: ignore[arg-type]
    with TestClient(app) as c:
        body = {"url": "http://10.0.0.1/"}
        assert c.post("/render", json=body, headers={"x-sandbox-key": "nope"}).status_code == 401
        assert c.post("/render", json=body).status_code == 401
        assert c.post("/render", json=body, headers={"authorization": "Bearer s3cret"}).status_code == 400
        assert c.get("/metrics").status_code == 401
