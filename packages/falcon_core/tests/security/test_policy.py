"""PR-4 review fixes and POST allow-list: allow_hosts at the socket layer, malformed
Location headers, IPv4-compatible IPv6, timeout clamp, and GuardedHTTPClient.post."""

from __future__ import annotations

import json
from collections.abc import Sequence

import httpcore
import httpx
import pytest

from falcon_core.security import (
    BlockReason,
    FetchFailed,
    GuardedHTTPClient,
    GuardPolicy,
    SSRFBlocked,
    ip_block_reason,
    ip_reason_for_host,
    safe_fetch,
)
from falcon_core.security.http import (
    _DIAL_HOST,
    PinnedNetworkBackend,
    _build_transport,
    _clamp_timeout,
)

PUBLIC_V4 = "93.184.215.14"
FIXTURE = "falcon-demo-bank.test"
FIXTURE_POLICY = GuardPolicy(allow_hosts=frozenset({FIXTURE}))
OK_WIRE = [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nok"]


def table(t: dict[str, Sequence[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str) -> Sequence[str]:
        if host not in t:
            raise OSError("NXDOMAIN")
        return t[host]

    return resolve


class RecordingBackend(httpcore.AsyncMockBackend):
    """Mock socket backend that records every dialled (host, port)."""

    def __init__(self, buffer: list[bytes]) -> None:
        super().__init__(buffer)
        self.dialled: list[tuple[str, int]] = []

    async def connect_tcp(self, host: str, port: int, *args: object, **kwargs: object) -> httpcore.AsyncNetworkStream:
        self.dialled.append((host, port))
        return await super().connect_tcp(host, port)


# ------------------------------------------- 1. allow_hosts at the socket layer


@pytest.mark.asyncio
async def test_allow_listed_fixture_reaches_private_ip_through_real_transport() -> None:
    inner = RecordingBackend(OK_WIRE)
    transport = _build_transport(FIXTURE_POLICY, None, inner=inner)
    r = await safe_fetch(
        f"http://{FIXTURE}/",
        resolver=table({FIXTURE: ["172.18.0.5"]}),
        policy=FIXTURE_POLICY,
        transport=transport,
    )
    assert r.status == 200
    assert r.body == b"ok"
    assert inner.dialled == [("172.18.0.5", 80)]  # the pinned IP, never the name


@pytest.mark.asyncio
async def test_non_listed_host_on_same_private_ip_refused() -> None:
    inner = RecordingBackend(OK_WIRE)
    transport = _build_transport(FIXTURE_POLICY, None, inner=inner)
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://other.example.com/",
            resolver=table({"other.example.com": ["172.18.0.5"]}),
            policy=FIXTURE_POLICY,
            transport=transport,
        )
    assert ei.value.reason is BlockReason.PRIVATE
    assert inner.dialled == []


@pytest.mark.asyncio
async def test_socket_layer_uses_logical_host_only() -> None:
    backend = PinnedNetworkBackend(FIXTURE_POLICY, inner=RecordingBackend(OK_WIRE))
    # No logical host (a bypass of the URL layer): strict.
    with pytest.raises(SSRFBlocked) as ei:
        await backend.connect_tcp("172.18.0.5", 80)
    assert ei.value.reason is BlockReason.PRIVATE
    token = _DIAL_HOST.set("other.example.com")
    try:
        with pytest.raises(SSRFBlocked):
            await backend.connect_tcp("172.18.0.5", 80)
    finally:
        _DIAL_HOST.reset(token)
    token = _DIAL_HOST.set(FIXTURE)
    try:
        assert await backend.connect_tcp("172.18.0.5", 80) is not None
        # Listing a host never opens metadata or loopback on its own.
        for ip, reason in [
            ("169.254.169.254", BlockReason.METADATA),
            ("127.0.0.1", BlockReason.LOOPBACK),
            ("169.254.1.1", BlockReason.LINK_LOCAL),
        ]:
            with pytest.raises(SSRFBlocked) as ei:
                await backend.connect_tcp(ip, 80)
            assert ei.value.reason is reason
    finally:
        _DIAL_HOST.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ip", "reason"),
    [("169.254.169.254", BlockReason.METADATA), ("127.0.0.1", BlockReason.LOOPBACK)],
)
async def test_listed_host_resolving_to_metadata_or_loopback_blocked(ip: str, reason: BlockReason) -> None:
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            f"http://{FIXTURE}/",
            resolver=table({FIXTURE: [ip]}),
            policy=FIXTURE_POLICY,
            transport=_build_transport(FIXTURE_POLICY, None, inner=RecordingBackend(OK_WIRE)),
        )
    assert ei.value.reason is reason


@pytest.mark.asyncio
async def test_loopback_only_with_exact_allow_host_ips() -> None:
    policy = GuardPolicy(allow_hosts=frozenset({FIXTURE}), allow_host_ips=frozenset({"127.0.0.1"}))
    inner = RecordingBackend(OK_WIRE)
    r = await safe_fetch(
        f"http://{FIXTURE}/",
        resolver=table({FIXTURE: ["127.0.0.1"]}),
        policy=policy,
        transport=_build_transport(policy, None, inner=inner),
    )
    assert r.status == 200
    assert inner.dialled == [("127.0.0.1", 80)]
    assert ip_reason_for_host(FIXTURE, "127.0.0.2", policy) is BlockReason.LOOPBACK
    assert ip_reason_for_host("x.example.com", "127.0.0.1", policy) is BlockReason.LOOPBACK


def test_default_policy_lists_nothing() -> None:
    assert ip_reason_for_host(FIXTURE, "10.0.0.1") is BlockReason.PRIVATE


# ------------------------------------------------- 2. malformed Location


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["http:127.0.0.1/", "http:evil.org", "https:foo", "http://[::1", "http://a b/"])
async def test_malformed_location_is_typed_error(location: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    res = table({"public.example.com": [PUBLIC_V4]})
    with pytest.raises((SSRFBlocked, FetchFailed)):
        await safe_fetch("http://public.example.com/", resolver=res, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize("location", [b"http:127.0.0.1/", b"http:evil.org", b"https:foo"])
async def test_malformed_location_through_real_transport(location: bytes) -> None:
    wire = [b"HTTP/1.1 302 Found\r\nLocation: " + location + b"\r\nContent-Length: 0\r\n\r\n"]
    inner = RecordingBackend(wire)
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://public.example.com/",
            resolver=table({"public.example.com": [PUBLIC_V4]}),
            transport=_build_transport(GuardPolicy(), None, inner=inner),
        )
    # httpx (like WHATWG) resolves same-scheme "http:foo" as a relative path, so
    # these loop on the same public host; anything else is invalid_url. Either
    # way the error is typed and only the checked public IP is ever dialled.
    assert ei.value.reason in (BlockReason.INVALID_URL, BlockReason.TOO_MANY_REDIRECTS)
    assert set(inner.dialled) == {(PUBLIC_V4, 80)}


# ---------------------------------------- 3. IPv4-compatible IPv6, timeout


@pytest.mark.parametrize("ip", ["::8.8.8.8", "::93.184.215.14", "[::1.1.1.1]"])
def test_ipv4_compatible_public_inner_blocked(ip: str) -> None:
    assert ip_block_reason(ip) is BlockReason.RESERVED


def test_ipv4_compatible_private_inner_keeps_inner_reason() -> None:
    assert ip_block_reason("::10.0.0.1") is BlockReason.PRIVATE
    assert ip_block_reason("::ffff:" + PUBLIC_V4) is None  # mapped public stays allowed


def test_timeout_clamped() -> None:
    assert _clamp_timeout(600) == 6.0
    assert _clamp_timeout(0) == 6.0
    assert _clamp_timeout(-1) == 6.0
    assert _clamp_timeout(float("nan")) == 6.0
    assert _clamp_timeout(1.5) == 1.5


# --------------------------------------------------------------- 4. POST

API = "api.reputation.example.com"
POST_POLICY = GuardPolicy(post_allow_hosts=frozenset({API}))


@pytest.mark.asyncio
async def test_post_to_allow_listed_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b'{"matches":[]}'))

    async with GuardedHTTPClient(
        resolver=table({API: [PUBLIC_V4]}),
        policy=POST_POLICY,
        transport=httpx.MockTransport(handler),
    ) as c:
        r = await c.post(f"https://{API}/v4/threatMatches:find", json={"q": ["a"]})
        f = await c.post(f"https://{API}/v1/host/", data={"host": "x.example.com"})
    assert r.status == 200
    assert r.body == b'{"matches":[]}'
    assert seen[0].method == "POST"
    assert seen[0].url.host == PUBLIC_V4  # pinned
    assert seen[0].headers["host"] == API
    assert seen[0].headers["content-type"] == "application/json"
    assert json.loads(seen[0].content) == {"q": ["a"]}
    assert f.status == 200
    assert seen[1].headers["content-type"] == "application/x-www-form-urlencoded"
    assert seen[1].content == b"host=x.example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://other.example.com/",
        "https://sub.api.reputation.example.com/",  # exact match only
        "https://10.0.0.1/",
    ],
)
async def test_post_to_other_host_blocked(url: str) -> None:
    blocks: list[BlockReason] = []
    called: list[httpx.Request] = []
    async with GuardedHTTPClient(
        resolver=table({"other.example.com": [PUBLIC_V4], "sub." + API: [PUBLIC_V4]}),
        policy=POST_POLICY,
        transport=httpx.MockTransport(lambda r: called.append(r) or httpx.Response(200)),  # type: ignore[func-returns-value]
        on_block=blocks.append,
    ) as c:
        with pytest.raises(SSRFBlocked) as ei:
            await c.post(url, json={})
    assert ei.value.reason in (BlockReason.METHOD_NOT_ALLOWED, BlockReason.PRIVATE)
    if "10.0.0.1" not in url:
        assert ei.value.reason is BlockReason.METHOD_NOT_ALLOWED
        assert ei.value.reason.value == "method_not_allowed"
    assert blocks == [ei.value.reason]
    assert called == []


@pytest.mark.asyncio
async def test_post_default_policy_allows_nothing() -> None:
    async with GuardedHTTPClient(resolver=table({API: [PUBLIC_V4]})) as c:
        with pytest.raises(SSRFBlocked) as ei:
            await c.post(f"https://{API}/", json={})
    assert ei.value.reason is BlockReason.METHOD_NOT_ALLOWED


@pytest.mark.asyncio
async def test_post_rules() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://elsewhere.example.com/"},
            stream=httpx.ByteStream(b""),
        )

    async with GuardedHTTPClient(
        resolver=table({API: [PUBLIC_V4]}),
        policy=POST_POLICY,
        transport=httpx.MockTransport(handler),
    ) as c:
        with pytest.raises(SSRFBlocked) as ei:
            await c.post(f"http://{API}/", json={})
        assert ei.value.reason is BlockReason.SCHEME
        with pytest.raises(SSRFBlocked) as ei:
            await c.post(f"https://{API}/", json={"x": "a" * (64 * 1024)})
        assert ei.value.reason is BlockReason.REQUEST_TOO_LARGE
        r = await c.post(f"https://{API}/", json={"x": 1})  # 3xx returned, not followed
        assert r.status == 302
        assert len(calls) == 1
        with pytest.raises(ValueError):
            await c.post(f"https://{API}/", json={}, data={"a": "b"})
        with pytest.raises(SSRFBlocked) as ei:  # fetch() never POSTs
            await c.fetch(f"https://{API}/", method="POST")
        assert ei.value.reason is BlockReason.METHOD_NOT_ALLOWED


@pytest.mark.asyncio
async def test_post_allow_listed_host_resolving_private_blocked() -> None:
    async with GuardedHTTPClient(
        resolver=table({API: ["10.0.0.7"]}),
        policy=POST_POLICY,
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    ) as c:
        with pytest.raises(SSRFBlocked) as ei:
            await c.post(f"https://{API}/", json={})
    assert ei.value.reason is BlockReason.PRIVATE
