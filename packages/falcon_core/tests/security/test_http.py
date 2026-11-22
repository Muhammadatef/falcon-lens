"""Guarded client internals: socket-level pinning, decoding caps, hooks."""

from __future__ import annotations

import asyncio
import gzip
import os
import zlib
from collections.abc import Sequence

import httpcore
import httpx
import pytest

from falcon_core.security import (
    BlockReason,
    FetchFailed,
    FetchFailReason,
    GuardedHTTPClient,
    SSRFBlocked,
    safe_fetch,
    set_default_on_block,
)
from falcon_core.security.http import (
    PinnedNetworkBackend,
    ProxyOnlyNetworkBackend,
    _build_transport,
)
from falcon_core.security.ssrf import DEFAULT_POLICY

PUBLIC_V4 = "93.184.215.14"


async def resolver(host: str) -> Sequence[str]:
    return [PUBLIC_V4]


# --------------------------------------------------------- socket layer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("host", "port", "reason"),
    [
        (
            "public.example.com",
            443,
            BlockReason.NOT_PINNED,
        ),  # a name means something skipped the guard
        ("10.0.0.1", 80, BlockReason.PRIVATE),
        ("127.0.0.1", 443, BlockReason.LOOPBACK),
        ("::1", 443, BlockReason.LOOPBACK),
        ("169.254.169.254", 80, BlockReason.METADATA),
        (PUBLIC_V4, 22, BlockReason.PORT),
    ],
)
async def test_pinned_backend_refuses(
    host: str, port: int, reason: BlockReason
) -> None:
    backend = PinnedNetworkBackend()
    with pytest.raises(SSRFBlocked) as ei:
        await backend.connect_tcp(host, port)
    assert ei.value.reason is reason


@pytest.mark.asyncio
async def test_pinned_backend_refuses_unix_socket() -> None:
    with pytest.raises(SSRFBlocked):
        await PinnedNetworkBackend().connect_unix_socket("/var/run/docker.sock")


@pytest.mark.asyncio
async def test_pinned_backend_delegates_allowed_ip() -> None:
    inner = httpcore.AsyncMockBackend([b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"])
    stream = await PinnedNetworkBackend(inner=inner).connect_tcp(PUBLIC_V4, 443)
    assert stream is not None


@pytest.mark.asyncio
async def test_proxy_only_backend() -> None:
    inner = httpcore.AsyncMockBackend([])
    b = ProxyOnlyNetworkBackend("egress", 3128, inner=inner)
    assert await b.connect_tcp("egress", 3128) is not None
    with pytest.raises(SSRFBlocked) as ei:
        await b.connect_tcp(PUBLIC_V4, 443)
    assert ei.value.reason is BlockReason.NOT_PINNED


def test_transport_pool_uses_guarded_backend() -> None:
    """Pins the httpx 0.28.x private ``_pool`` swap; fails loudly on upgrade."""
    t = _build_transport(DEFAULT_POLICY, None)
    pool = t._pool
    assert isinstance(pool, httpcore.AsyncConnectionPool)
    assert isinstance(pool._network_backend, PinnedNetworkBackend)
    tp = _build_transport(DEFAULT_POLICY, "http://egress:3128")
    assert isinstance(tp._pool, httpcore.AsyncHTTPProxy)
    assert isinstance(tp._pool._network_backend, ProxyOnlyNetworkBackend)


@pytest.mark.asyncio
async def test_real_transport_blocks_at_socket_even_if_url_layer_bypassed() -> None:
    """Send straight through the production transport with a private IP: the
    socket layer refuses, and the error surfaces as SSRFBlocked (not wrapped)."""
    t = _build_transport(DEFAULT_POLICY, None)
    async with httpx.AsyncClient(transport=t, trust_env=False) as c:
        with pytest.raises(SSRFBlocked) as ei:
            await c.get("http://10.0.0.1/")
        assert ei.value.reason is BlockReason.PRIVATE
        with pytest.raises(SSRFBlocked) as ei:
            await c.get("http://public.example.com/")
        assert ei.value.reason is BlockReason.NOT_PINNED


# ------------------------------------------------------------- bodies


@pytest.mark.asyncio
async def test_gzip_body_decoded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=httpx.ByteStream(gzip.compress(b"hello")),
        )

    r = await safe_fetch(
        "http://g.example.com/",
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    assert r.body == b"hello"


@pytest.mark.asyncio
async def test_deflate_body_decoded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "deflate"},
            stream=httpx.ByteStream(zlib.compress(b"hi")),
        )

    r = await safe_fetch(
        "http://d.example.com/",
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    assert r.body == b"hi"


@pytest.mark.asyncio
async def test_gzip_bomb_blocked() -> None:
    bomb = gzip.compress(
        b"\0" * (50 * 1024 * 1024)
    )  # ~50 KB on the wire, 50 MB decoded
    assert len(bomb) < 1024 * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(bomb)
        )

    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://bomb.example.com/",
            resolver=resolver,
            transport=httpx.MockTransport(handler),
        )
    assert ei.value.reason is BlockReason.RESPONSE_TOO_LARGE


@pytest.mark.asyncio
async def test_custom_smaller_cap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"x" * 2000))

    with pytest.raises(SSRFBlocked):
        await safe_fetch(
            "http://s.example.com/",
            resolver=resolver,
            transport=httpx.MockTransport(handler),
            max_bytes=1000,
        )


@pytest.mark.asyncio
async def test_unsupported_encoding_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "br"}, stream=httpx.ByteStream(b"???")
        )

    with pytest.raises(FetchFailed) as ei:
        await safe_fetch(
            "http://br.example.com/",
            resolver=resolver,
            transport=httpx.MockTransport(handler),
        )
    assert ei.value.reason is FetchFailReason.UNSUPPORTED_ENCODING


@pytest.mark.asyncio
async def test_header_subset_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html",
                "set-cookie": "sid=1",
                "x-secret": "1",
            },
            stream=httpx.ByteStream(b"ok"),
        )

    r = await safe_fetch(
        "http://h.example.com/",
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    assert dict(r.headers) == {"content-type": "text/html"}


# ------------------------------------------------------- method / timeout


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "CONNECT"])
async def test_non_get_methods_blocked(method: str) -> None:
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://m.example.com/",
            method=method,
            resolver=resolver,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
    assert ei.value.reason is BlockReason.METHOD


@pytest.mark.asyncio
async def test_head_has_empty_body() -> None:
    r = await safe_fetch(
        "http://m.example.com/",
        method="HEAD",
        resolver=resolver,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, stream=httpx.ByteStream(b"zzz"))
        ),
    )
    assert r.body == b""


@pytest.mark.asyncio
async def test_total_timeout_covers_dns() -> None:
    async def slow(host: str) -> Sequence[str]:
        await asyncio.sleep(5)
        return [PUBLIC_V4]

    with pytest.raises(FetchFailed) as ei:
        await safe_fetch(
            "http://slow.example.com/",
            resolver=slow,
            timeout=0.05,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
    assert ei.value.reason is FetchFailReason.TIMEOUT


@pytest.mark.asyncio
async def test_connect_error_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(FetchFailed) as ei:
        await safe_fetch(
            "http://c.example.com/",
            resolver=resolver,
            transport=httpx.MockTransport(handler),
        )
    assert ei.value.reason is FetchFailReason.CONNECT_ERROR


# ---------------------------------------------------------------- hooks


@pytest.mark.asyncio
async def test_default_hook_and_broken_hook() -> None:
    seen: list[BlockReason] = []
    set_default_on_block(seen.append)
    try:
        with pytest.raises(SSRFBlocked):
            await safe_fetch("http://127.0.0.1/")
        assert seen == [BlockReason.LOOPBACK]
    finally:
        set_default_on_block(None)

    def broken(reason: BlockReason) -> None:
        raise RuntimeError("metrics down")

    with pytest.raises(SSRFBlocked):  # still blocked; hook failure swallowed
        await safe_fetch("http://10.0.0.1/", on_block=broken)


@pytest.mark.asyncio
async def test_proxy_mode_keeps_hostname_and_prechecks() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"))

    async with GuardedHTTPClient(
        resolver=resolver,
        proxy="http://egress:3128",
        transport=httpx.MockTransport(handler),
    ) as c:
        r = await c.fetch("https://p.example.com/")
        assert r.status == 200
        assert seen[0].url.host == "p.example.com"
        with pytest.raises(SSRFBlocked):
            await c.fetch("http://169.254.169.254/")


# ------------------------------------------------- optional live check


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("FL_NETWORK_TESTS") != "1",
    reason="set FL_NETWORK_TESTS=1 for live network",
)
async def test_live_public_fetch() -> None:
    r = await safe_fetch("https://example.com/", timeout=10)
    assert r.status == 200
    assert r.resolved_ip
