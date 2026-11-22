"""T-003 acceptance: SSRF guard. No real network: DNS and HTTP are mocked.

Host names here are invented (``*.example.com`` is IANA-reserved for docs) and
the public addresses are only ever handed to a mock transport.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

from falcon_core.security import (
    BlockReason,
    GuardPolicy,
    Resolver,
    SSRFBlocked,
    check_host_port,
    ip_block_reason,
    is_ip_allowed,
    resolve_and_check,
    safe_fetch,
    validate_url,
)

PUBLIC_V4 = "93.184.215.14"
PUBLIC_V4_B = "93.184.215.15"
PUBLIC_V6 = "2606:2800:21f:cb07:6820:80da:af6b:8b2c"


def static_resolver(table: dict[str, Sequence[str]]) -> Resolver:
    async def resolve(host: str) -> Sequence[str]:
        if host not in table:
            raise OSError("NXDOMAIN")
        return table[host]

    return resolve


class SequenceResolver:
    """Returns successive answers for the same name (DNS rebinding)."""

    def __init__(self, answers: list[list[str]]) -> None:
        self.answers = answers
        self.calls = 0

    async def __call__(self, host: str) -> Sequence[str]:
        ans = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return ans


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/html"},
        stream=httpx.ByteStream(b"<html>ok</html>"),
    )


# ------------------------------------------------------------ validate_url


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://127.0.0.1/", BlockReason.LOOPBACK),
        ("http://2130706433/", BlockReason.OBFUSCATED_IP),
        ("http://0177.0.0.1/", BlockReason.OBFUSCATED_IP),
        ("http://0x7f.1/", BlockReason.OBFUSCATED_IP),
        ("http://0x7f000001/", BlockReason.OBFUSCATED_IP),
        ("http://127.1/", BlockReason.OBFUSCATED_IP),
        ("http://017700000001/", BlockReason.OBFUSCATED_IP),
        ("http://[::1]/", BlockReason.LOOPBACK),
        ("http://[::ffff:10.0.0.1]/", BlockReason.PRIVATE),
        ("http://[::ffff:127.0.0.1]/", BlockReason.LOOPBACK),
        ("http://[::ffff:a00:1]/", BlockReason.PRIVATE),
        ("http://[::ffff:169.254.169.254]/", BlockReason.METADATA),
        ("http://[64:ff9b::a00:1]/", BlockReason.PRIVATE),
        ("http://[2002:7f00:1::]/", BlockReason.LOOPBACK),
        ("http://[::127.0.0.1]/", BlockReason.LOOPBACK),
        ("http://[2001::1]/", BlockReason.RESERVED),
        ("http://169.254.169.254/latest/meta-data/", BlockReason.METADATA),
        ("http://[fd00:ec2::254]/", BlockReason.METADATA),
        ("http://100.100.100.200/", BlockReason.METADATA),
        ("http://169.254.1.1/", BlockReason.LINK_LOCAL),
        ("http://[fe80::1]/", BlockReason.LINK_LOCAL),
        ("http://100.64.0.1/", BlockReason.CGNAT),
        ("http://[fd00::1]/", BlockReason.IPV6_ULA),
        ("http://10.0.0.1/", BlockReason.PRIVATE),
        ("http://172.16.5.4/", BlockReason.PRIVATE),
        ("http://192.168.1.1/", BlockReason.PRIVATE),
        ("http://0.0.0.0/", BlockReason.RESERVED),
        ("http://[::]/", BlockReason.RESERVED),
        ("http://224.0.0.1/", BlockReason.RESERVED),
        ("http://255.255.255.255/", BlockReason.RESERVED),
        ("http://198.18.0.1/", BlockReason.RESERVED),
        ("http://evil@10.0.0.1/", BlockReason.USERINFO),
        ("http://evil@public.example.com/", BlockReason.USERINFO),
        ("http://user:pass@public.example.com/", BlockReason.USERINFO),
        ("http://public.example.com%40127.0.0.1/", BlockReason.USERINFO),
        ("http://redis:6379/", BlockReason.PORT),
        ("http://redis/", BlockReason.INTERNAL_NAME),
        ("http://postgres/", BlockReason.INTERNAL_NAME),
        ("http://egress/", BlockReason.INTERNAL_NAME),
        ("http://localhost/", BlockReason.INTERNAL_NAME),
        ("http://localhost./", BlockReason.INTERNAL_NAME),
        ("http://LOCALHOST/", BlockReason.INTERNAL_NAME),
        ("http://foo.localhost/", BlockReason.INTERNAL_NAME),
        ("http://host.docker.internal/", BlockReason.INTERNAL_NAME),
        ("http://metadata.google.internal/", BlockReason.INTERNAL_NAME),
        ("http://printer.local/", BlockReason.INTERNAL_NAME),
        ("http://router.home.arpa/", BlockReason.INTERNAL_NAME),
        ("http://redis.default.svc.cluster.local/", BlockReason.INTERNAL_NAME),
        ("http://falcon-demo-bank.test/", BlockReason.INTERNAL_NAME),
        ("http://public.example.com:22/", BlockReason.PORT),
        ("http://public.example.com:8080/", BlockReason.PORT),
        ("https://public.example.com:0/", BlockReason.PORT),
        ("file:///etc/passwd", BlockReason.SCHEME),
        ("gopher://public.example.com:70/_INFO", BlockReason.SCHEME),
        ("data:text/html,<b>x</b>", BlockReason.SCHEME),
        ("javascript:alert(1)", BlockReason.SCHEME),
        ("ftp://public.example.com/", BlockReason.SCHEME),
        ("dict://127.0.0.1:6379/info", BlockReason.SCHEME),
        ("http:/public.example.com/", BlockReason.INVALID_URL),
        ("http://public.example.com\\@10.0.0.1/", BlockReason.INVALID_URL),
        ("http://pub lic.example.com/", BlockReason.INVALID_URL),
        ("http://public.example.com\r\nX: y/", BlockReason.INVALID_URL),
        ("http:///path", BlockReason.INVALID_URL),
        ("//public.example.com/", BlockReason.INVALID_URL),
        ("http://" + "a" * 5000 + ".example.com/", BlockReason.URL_TOO_LONG),
    ],
)
def test_validate_url_blocks(url: str, reason: BlockReason) -> None:
    with pytest.raises(SSRFBlocked) as ei:
        validate_url(url)
    assert ei.value.reason is reason, (url, ei.value)


@pytest.mark.parametrize(
    ("url", "canonical", "port"),
    [
        (
            "https://Public.Example.COM/a?b=1#frag",
            "https://public.example.com/a?b=1",
            443,
        ),
        ("http://public.example.com:80/", "http://public.example.com/", 80),
        ("http://public.example.com:443/", "http://public.example.com:443/", 443),
        ("https://public.example.com.", "https://public.example.com/", 443),
        ("  https://public.example.com/x  ", "https://public.example.com/x", 443),
        (f"http://{PUBLIC_V4}/", f"http://{PUBLIC_V4}/", 80),
        (f"https://[{PUBLIC_V6}]/", f"https://[{PUBLIC_V6}]/", 443),
        (
            "https://xn--mnchen-3ya.example.com/",
            "https://xn--mnchen-3ya.example.com/",
            443,
        ),
        ("https://münchen.example.com/", "https://xn--mnchen-3ya.example.com/", 443),
        ("https://user.github.io/page", "https://user.github.io/page", 443),
        ("https://a_b.example.com/", "https://a_b.example.com/", 443),
    ],
)
def test_validate_url_allows_public(url: str, canonical: str, port: int) -> None:
    t = validate_url(url)
    assert t.url == canonical
    assert t.port == port


def test_allow_hosts_is_explicit_opt_in() -> None:
    policy = GuardPolicy(allow_hosts=frozenset({"falcon-demo-bank.test"}))
    assert (
        validate_url("http://falcon-demo-bank.test/", policy).host
        == "falcon-demo-bank.test"
    )
    with pytest.raises(SSRFBlocked):
        validate_url("http://falcon-demo-bank.test:8080/", policy)  # ports stay strict
    with pytest.raises(SSRFBlocked):
        validate_url("http://other.test/", policy)


# -------------------------------------------------------------- IP policy


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "::1",
        "::ffff:10.0.0.1",
        "[::1]",
        "fd00::1",
        "fe80::1%en0",
        "not-an-ip",
    ],
)
def test_is_ip_allowed_false(ip: str) -> None:
    assert not is_ip_allowed(ip)
    assert ip_block_reason(ip) is not None


@pytest.mark.parametrize("ip", [PUBLIC_V4, PUBLIC_V6, "::ffff:" + PUBLIC_V4, "1.1.1.1"])
def test_is_ip_allowed_true(ip: str) -> None:
    assert is_ip_allowed(ip)


def test_check_host_port_for_proxy() -> None:
    assert check_host_port("public.example.com", 443) is None
    assert str(check_host_port(PUBLIC_V4, 80)) == PUBLIC_V4
    for host, port, reason in [
        ("169.254.169.254", 80, BlockReason.METADATA),
        ("[::1]", 443, BlockReason.LOOPBACK),
        ("redis", 443, BlockReason.INTERNAL_NAME),
        ("public.example.com", 22, BlockReason.PORT),
        ("2130706433", 80, BlockReason.OBFUSCATED_IP),
    ]:
        with pytest.raises(SSRFBlocked) as ei:
            check_host_port(host, port)
        assert ei.value.reason is reason


# ------------------------------------------------------------- resolution


@pytest.mark.asyncio
async def test_resolver_private_answer_blocked() -> None:
    t = validate_url("http://internal-looking.example.com/")
    with pytest.raises(SSRFBlocked) as ei:
        await resolve_and_check(
            t, static_resolver({"internal-looking.example.com": ["10.1.2.3"]})
        )
    assert ei.value.reason is BlockReason.PRIVATE


@pytest.mark.asyncio
async def test_resolver_mixed_answer_blocked() -> None:
    t = validate_url("http://mixed.example.com/")
    res = static_resolver({"mixed.example.com": [PUBLIC_V4, "127.0.0.1"]})
    with pytest.raises(SSRFBlocked) as ei:
        await resolve_and_check(t, res)
    assert ei.value.reason is BlockReason.LOOPBACK


@pytest.mark.asyncio
async def test_resolver_nxdomain_and_empty() -> None:
    t = validate_url("http://nx.example.com/")
    for res in (static_resolver({}), static_resolver({"nx.example.com": []})):
        with pytest.raises(SSRFBlocked) as ei:
            await resolve_and_check(t, res)
        assert ei.value.reason is BlockReason.DNS_FAILURE


# ----------------------------------------------------- end-to-end fetches


@pytest.mark.asyncio
async def test_public_host_allowed_and_pinned() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok_handler(request)

    r = await safe_fetch(
        "https://public.example.com/page?q=1",
        resolver=static_resolver({"public.example.com": [PUBLIC_V4]}),
        transport=httpx.MockTransport(handler),
    )
    assert r.status == 200
    assert r.body == b"<html>ok</html>"
    assert r.final_url == "https://public.example.com/page?q=1"
    assert r.resolved_ip == PUBLIC_V4
    assert [h.url for h in r.redirect_chain] == ["https://public.example.com/page?q=1"]
    # Pinned: the wire request goes to the checked IP, hostname only in Host + SNI.
    (req,) = seen
    assert req.url.host == PUBLIC_V4
    assert req.headers["host"] == "public.example.com"
    assert req.extensions["sni_hostname"] == "public.example.com"


@pytest.mark.asyncio
async def test_public_ipv6_host_allowed() -> None:
    r = await safe_fetch(
        "http://v6.example.com/",
        resolver=static_resolver({"v6.example.com": [PUBLIC_V6]}),
        transport=httpx.MockTransport(ok_handler),
    )
    assert r.resolved_ip == PUBLIC_V6


@pytest.mark.asyncio
async def test_dns_rebinding_second_resolve_private_blocked() -> None:
    """First resolve public, then the attacker flips the record to a private IP
    and redirects back to the same name. The re-check on the next hop catches
    it, and the first hop was pinned to the public IP (never re-resolved)."""
    resolver = SequenceResolver([[PUBLIC_V4], ["10.0.0.1"]])
    wire_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wire_hosts.append(request.url.host)
        return httpx.Response(
            302, headers={"location": "http://rebind.example.com/admin"}
        )

    blocks: list[BlockReason] = []
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://rebind.example.com/",
            resolver=resolver,
            transport=httpx.MockTransport(handler),
            on_block=blocks.append,
        )
    assert ei.value.reason is BlockReason.PRIVATE
    assert resolver.calls == 2
    assert wire_hosts == [PUBLIC_V4]  # nothing ever went to 10.0.0.1
    assert blocks == [BlockReason.PRIVATE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("http://10.0.0.1/", BlockReason.PRIVATE),
        ("http://169.254.169.254/latest/meta-data/", BlockReason.METADATA),
        ("http://[::1]/", BlockReason.LOOPBACK),
        ("http://2130706433/", BlockReason.OBFUSCATED_IP),
        ("http://redis:6379/", BlockReason.PORT),
        ("http://localhost/", BlockReason.INTERNAL_NAME),
        ("http://evil@public.example.com/", BlockReason.USERINFO),
        ("file:///etc/passwd", BlockReason.SCHEME),
        ("gopher://public.example.com/", BlockReason.SCHEME),
        ("//127.0.0.1/", BlockReason.LOOPBACK),  # scheme-relative
        (
            "http://private-name.example.com/",
            BlockReason.PRIVATE,
        ),  # name resolving private
    ],
)
async def test_redirect_to_private_blocked(location: str, reason: BlockReason) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    res = static_resolver(
        {
            "public.example.com": [PUBLIC_V4],
            "private-name.example.com": ["192.168.0.10"],
        }
    )
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://public.example.com/",
            resolver=res,
            transport=httpx.MockTransport(handler),
        )
    assert ei.value.reason is reason


@pytest.mark.asyncio
async def test_redirect_chain_followed_and_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if host == "a.example.com":
            return httpx.Response(301, headers={"location": "https://b.example.com/x"})
        if host == "b.example.com" and request.url.path == "/x":
            return httpx.Response(302, headers={"location": "/final"})
        return ok_handler(request)

    res = static_resolver(
        {"a.example.com": [PUBLIC_V4], "b.example.com": [PUBLIC_V4_B]}
    )
    r = await safe_fetch(
        "http://a.example.com/", resolver=res, transport=httpx.MockTransport(handler)
    )
    assert r.final_url == "https://b.example.com/final"
    assert [(h.url, h.status, h.ip) for h in r.redirect_chain] == [
        ("http://a.example.com/", 301, PUBLIC_V4),
        ("https://b.example.com/x", 302, PUBLIC_V4_B),
        ("https://b.example.com/final", 200, PUBLIC_V4_B),
    ]


def _loop_handler(request: httpx.Request) -> httpx.Response:
    n = int(request.url.path.strip("/") or 0)
    if n >= 11:
        return ok_handler(request)
    return httpx.Response(302, headers={"location": f"/{n + 1}"})


@pytest.mark.asyncio
async def test_more_than_ten_redirects_blocked() -> None:
    res = static_resolver({"loop.example.com": [PUBLIC_V4]})
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://loop.example.com/0",
            resolver=res,
            transport=httpx.MockTransport(_loop_handler),
        )
    assert ei.value.reason is BlockReason.TOO_MANY_REDIRECTS


@pytest.mark.asyncio
async def test_exactly_ten_redirects_allowed() -> None:
    res = static_resolver({"loop.example.com": [PUBLIC_V4]})
    r = await safe_fetch(
        "http://loop.example.com/1",
        resolver=res,
        transport=httpx.MockTransport(_loop_handler),
    )
    assert r.status == 200
    assert len(r.redirect_chain) == 11  # 10 redirects + final


@pytest.mark.asyncio
async def test_max_redirects_cannot_exceed_hard_cap() -> None:
    res = static_resolver({"loop.example.com": [PUBLIC_V4]})
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            "http://loop.example.com/0",
            resolver=res,
            transport=httpx.MockTransport(_loop_handler),
            max_redirects=50,
        )
    assert ei.value.reason is BlockReason.TOO_MANY_REDIRECTS


@pytest.mark.asyncio
async def test_oversize_response_blocked() -> None:
    big = b"x" * (5 * 1024 * 1024 + 1)

    def declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big)

    async def stream_body() -> AsyncIterator[bytes]:
        for _ in range(6):
            yield b"y" * (1024 * 1024)

    def undeclared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=stream_body())

    res = static_resolver({"big.example.com": [PUBLIC_V4]})
    for handler in (declared, undeclared):
        with pytest.raises(SSRFBlocked) as ei:
            await safe_fetch(
                "http://big.example.com/",
                resolver=res,
                transport=httpx.MockTransport(handler),
            )
        assert ei.value.reason is BlockReason.RESPONSE_TOO_LARGE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://127.0.0.1/", BlockReason.LOOPBACK),
        ("http://2130706433/", BlockReason.OBFUSCATED_IP),
        ("http://0177.0.0.1/", BlockReason.OBFUSCATED_IP),
        ("http://0x7f.1/", BlockReason.OBFUSCATED_IP),
        ("http://[::1]/", BlockReason.LOOPBACK),
        ("http://[::ffff:10.0.0.1]/", BlockReason.PRIVATE),
        ("http://169.254.169.254/", BlockReason.METADATA),
        ("http://100.64.0.1/", BlockReason.CGNAT),
        ("http://[fd00::1]/", BlockReason.IPV6_ULA),
        ("http://evil@10.0.0.1/", BlockReason.USERINFO),
        ("http://redis:6379/", BlockReason.PORT),
        ("http://public.example.com:22/", BlockReason.PORT),
        ("file:///etc/passwd", BlockReason.SCHEME),
    ],
)
async def test_safe_fetch_blocks_and_reports(url: str, reason: BlockReason) -> None:
    called: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return ok_handler(request)

    blocks: list[BlockReason] = []
    with pytest.raises(SSRFBlocked) as ei:
        await safe_fetch(
            url,
            resolver=static_resolver({"public.example.com": [PUBLIC_V4]}),
            transport=httpx.MockTransport(handler),
            on_block=blocks.append,
        )
    assert ei.value.reason is reason
    assert blocks == [reason]
    assert called == []  # blocked before any byte left
