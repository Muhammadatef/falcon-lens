"""Egress proxy behaviour (T-003 part 2, PR-4 review item 6). Local sockets only.

The proxy runs with an injected resolver and an injected ``open_connection``.
That function records the (host, port) the proxy asked to dial, then connects to
a local fake upstream instead, so there is no real network and the pinning is
observable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import pytest

from falcon_core.security import BlockReason, GuardedHTTPClient, GuardPolicy, SSRFBlocked
from falcon_egress import main

PUBLIC = "93.184.215.14"
UPSTREAM_REPLY = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello"


class SeqResolver:
    def __init__(self, answers: dict[str, list[list[str]]]) -> None:
        self.answers = answers
        self.calls: dict[str, int] = {}

    async def __call__(self, host: str) -> Sequence[str]:
        seq = self.answers.get(host)
        if not seq:
            raise OSError("NXDOMAIN")
        n = self.calls.get(host, 0)
        self.calls[host] = n + 1
        return seq[min(n, len(seq) - 1)]


@dataclass
class Rig:
    port: int
    dialled: list[tuple[str, int]] = field(default_factory=list)
    received: list[bytes] = field(default_factory=list)


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    received: list[bytes] = []

    async def upstream(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        data = await r.read(65536)
        received.append(data)
        w.write(UPSTREAM_REPLY if not data.startswith(b"PING") else b"PONG")
        await w.drain()
        w.close()

    up = await asyncio.start_server(upstream, "127.0.0.1", 0)
    up_port = up.sockets[0].getsockname()[1]
    dialled: list[tuple[str, int]] = []

    async def fake_open(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        dialled.append((host, port))
        return await asyncio.open_connection("127.0.0.1", up_port)

    resolver = SeqResolver(
        {
            "public.example.com": [[PUBLIC]],
            "inside.example.com": [["10.0.0.5"]],
            "rebind.example.com": [[PUBLIC], ["127.0.0.1"]],
            "fixture.test": [["172.18.0.9"]],
        }
    )
    main.BLOCKED.clear()
    handler = main.make_proxy_handler(
        resolver=resolver,
        policy=GuardPolicy(allow_hosts=frozenset({"fixture.test"})),
        open_connection=fake_open,
    )
    proxy = await asyncio.start_server(handler, "127.0.0.1", 0)
    rig = Rig(port=proxy.sockets[0].getsockname()[1], dialled=dialled, received=received)
    async with up, proxy:
        yield rig


async def send(rig: Rig, raw: bytes, after_200: bytes | None = None) -> bytes:
    r, w = await asyncio.open_connection("127.0.0.1", rig.port)
    w.write(raw)
    await w.drain()
    if after_200 is not None:
        line = await r.readuntil(b"\r\n\r\n")
        assert line.startswith(b"HTTP/1.1 200")
        w.write(after_200)
        await w.drain()
    data = await asyncio.wait_for(r.read(), 5)
    w.close()
    return data


def status(resp: bytes) -> int:
    return int(resp.split(b" ", 2)[1])


# ------------------------------------------------------------------ CONNECT


async def test_connect_dials_checked_ip_not_name(rig: Rig) -> None:
    resp = await send(rig, b"CONNECT public.example.com:443 HTTP/1.1\r\n\r\n", after_200=b"PING")
    assert resp == b"PONG"
    assert rig.dialled == [(PUBLIC, 443)]


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        (b"169.254.169.254:80", b"metadata"),
        (b"10.0.0.1:443", b"private"),
        (b"[::1]:443", b"loopback"),
        (b"[::ffff:10.0.0.1]:443", b"private"),
        (b"2130706433:80", b"obfuscated_ip"),
        (b"redis:6379", b"port"),
        (b"redis:443", b"internal_name"),
        (b"public.example.com:22", b"port"),
        (b"inside.example.com:443", b"private"),
        (b"nx.example.com:443", b"dns_failure"),
    ],
)
async def test_connect_denied(rig: Rig, target: bytes, reason: bytes) -> None:
    resp = await send(rig, b"CONNECT " + target + b" HTTP/1.1\r\n\r\n")
    assert status(resp) == 403
    assert b"X-Falcon-Block-Reason: " + reason in resp
    assert rig.dialled == []


async def test_connect_rebinding_at_proxy_denied(rig: Rig) -> None:
    """The client pre-check saw a public IP. The proxy resolves again, gets loopback,
    and refuses. The first CONNECT was pinned to the public IP."""
    first = await send(rig, b"CONNECT rebind.example.com:443 HTTP/1.1\r\n\r\n", after_200=b"PING")
    assert first == b"PONG"
    second = await send(rig, b"CONNECT rebind.example.com:443 HTTP/1.1\r\n\r\n")
    assert status(second) == 403
    assert b"loopback" in second
    assert rig.dialled == [(PUBLIC, 443)]


async def test_fixture_host_only_via_explicit_allow_list(rig: Rig) -> None:
    resp = await send(rig, b"CONNECT fixture.test:443 HTTP/1.1\r\n\r\n", after_200=b"PING")
    assert resp == b"PONG"
    assert rig.dialled == [("172.18.0.9", 443)]


# -------------------------------------------------- absolute-form plain HTTP


async def test_absolute_form_get_forwarded_pinned_and_rewritten(rig: Rig) -> None:
    raw = (
        b"GET http://Public.Example.com/a/b?c=1 HTTP/1.1\r\n"
        b"Host: attacker-chosen.example.net\r\n"
        b"User-Agent: test\r\n"
        b"Proxy-Connection: keep-alive\r\n"
        b"Proxy-Authorization: Basic eDp5\r\n"
        b"Connection: keep-alive\r\n\r\n"
    )
    resp = await send(rig, raw)
    assert resp == UPSTREAM_REPLY
    assert rig.dialled == [(PUBLIC, 80)]
    (sent,) = rig.received
    head = sent.split(b"\r\n")
    assert head[0] == b"GET /a/b?c=1 HTTP/1.1"
    assert b"Host: public.example.com" in head  # rebuilt from the checked URL
    assert b"User-Agent: test" in head
    assert not any(h.lower().startswith(b"proxy-") for h in head)
    assert b"Connection: close" in head
    assert b"attacker-chosen" not in sent


@pytest.mark.parametrize(
    ("raw", "code", "reason"),
    [
        (b"GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\n\r\n", 403, b"metadata"),
        (b"GET http://10.0.0.1/ HTTP/1.1\r\n\r\n", 403, b"private"),
        (b"GET http://[::1]/ HTTP/1.1\r\n\r\n", 403, b"loopback"),
        (b"GET http://0x7f.1/ HTTP/1.1\r\n\r\n", 403, b"obfuscated_ip"),
        (b"GET http://evil@10.0.0.1/ HTTP/1.1\r\n\r\n", 403, b"userinfo"),
        (b"GET http://redis:6379/ HTTP/1.1\r\n\r\n", 403, b"port"),
        (b"GET http://localhost/ HTTP/1.1\r\n\r\n", 403, b"internal_name"),
        (b"GET http://inside.example.com/ HTTP/1.1\r\n\r\n", 403, b"private"),
        (b"GET https://public.example.com/ HTTP/1.1\r\n\r\n", 403, b"scheme"),
        (b"POST http://public.example.com/ HTTP/1.1\r\nContent-Length: 1\r\n\r\nx", 405, b""),
        (b"GET http://public.example.com/ HTTP/1.1\r\nContent-Length: 4\r\n\r\nbody", 400, b""),
        (
            b"GET http://public.example.com/ HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
            400,
            b"",
        ),
        (b"GET http://public.example.com/ HTTP/1.1\r\nX-A: 1\r\n folded\r\n\r\n", 400, b""),
        (b"GET http://public.example.com/ HTTP/1.1\r\nX-A : 1\r\n\r\n", 400, b""),
        (b"GET /origin-form HTTP/1.1\r\nHost: public.example.com\r\n\r\n", 400, b""),
        (b"GET http://public.example.com/ HTTP/2\r\n\r\n", 400, b""),
        (b"garbage\r\n\r\n", 400, b""),
    ],
)
async def test_plain_http_refused(rig: Rig, raw: bytes, code: int, reason: bytes) -> None:
    resp = await send(rig, raw)
    assert status(resp) == code
    if reason:
        assert b"X-Falcon-Block-Reason: " + reason in resp
    assert rig.dialled == []


async def test_metrics_count_reasons(rig: Rig) -> None:
    await send(rig, b"CONNECT 169.254.169.254:80 HTTP/1.1\r\n\r\n")
    await send(rig, b"GET http://169.254.169.254/ HTTP/1.1\r\n\r\n")
    assert main.BLOCKED["metadata"] == 2
    assert b'fl_ssrf_blocked_total{reason="metadata"} 2' in main._metrics()


async def test_oversized_head_refused(rig: Rig) -> None:
    raw = b"GET http://public.example.com/ HTTP/1.1\r\nX-Big: " + b"a" * 9000 + b"\r\n\r\n"
    resp = await send(rig, raw)
    assert status(resp) == 431


# -------------------------------- end to end: guarded client in proxy mode


async def test_guarded_client_through_proxy(rig: Rig) -> None:
    async def client_resolver(host: str) -> Sequence[str]:
        return [PUBLIC]

    async with GuardedHTTPClient(
        resolver=client_resolver, proxy=f"http://127.0.0.1:{rig.port}"
    ) as c:
        r = await c.fetch("http://public.example.com/x")
        assert r.status == 200
        assert r.body == b"hello"
        assert rig.dialled == [(PUBLIC, 80)]
        # The client pre-check sees public, the proxy sees private: the proxy refuses,
        # and the client surfaces the proxy's typed reason.
        with pytest.raises(SSRFBlocked) as ei:
            await c.fetch("http://inside.example.com/")
        assert ei.value.reason is BlockReason.PRIVATE
        with pytest.raises(SSRFBlocked) as ei:
            await c.fetch("https://inside.example.com/")
        assert ei.value.reason is BlockReason.EGRESS_DENIED
    assert rig.dialled == [(PUBLIC, 80)]
