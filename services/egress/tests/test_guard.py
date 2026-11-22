import asyncio
from collections.abc import Sequence

import pytest

from falcon_egress import guard

PUBLIC = "93.184.215.14"


async def resolver(host: str) -> Sequence[str]:
    return {"public.example.com": [PUBLIC], "inside.example.com": ["10.0.0.5"]}.get(host, [])


def test_blocks_disallowed_port_and_private_ip() -> None:
    assert asyncio.run(guard.check("example.com", 22)).reason == "port"
    assert asyncio.run(guard.check("127.0.0.1", 443)).reason == "loopback"
    assert asyncio.run(guard.check("169.254.169.254", 80)).reason == "metadata"
    assert asyncio.run(guard.check("10.0.0.5", 443)).reason == "private"
    assert asyncio.run(guard.check("[::1]", 443)).reason == "loopback"
    assert asyncio.run(guard.check("2130706433", 80)).reason == "obfuscated_ip"
    assert asyncio.run(guard.check("redis", 443)).reason == "internal_name"


def test_connect_check_resolves_with_guard() -> None:
    ok = asyncio.run(guard.check("public.example.com", 443, resolver=resolver))
    assert ok.allowed
    assert ok.addresses == [PUBLIC]
    bad = asyncio.run(guard.check("inside.example.com", 443, resolver=resolver))
    assert not bad.allowed
    assert bad.reason == "private"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://169.254.169.254/latest/meta-data/", "metadata"),
        ("http://evil@public.example.com/", "userinfo"),
        ("http://redis:6379/", "port"),
        ("http://inside.example.com/", "private"),
        ("https://public.example.com/", "scheme"),
    ],
)
def test_check_url_denies(url: str, reason: str) -> None:
    d = asyncio.run(guard.check_url(url, resolver=resolver))
    assert not d.allowed
    assert d.reason == reason


def test_check_url_allows_and_canonicalises() -> None:
    d = asyncio.run(guard.check_url("http://Public.Example.com/a?b=1#f", resolver=resolver))
    assert d.allowed
    assert d.addresses == [PUBLIC]
    assert d.host_header == "public.example.com"
    assert d.request_target == "/a?b=1"
    assert d.port == 80


def test_policy_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_EGRESS_ALLOW_HOSTS", " falcon-demo-bank.test , ")
    pol = guard.policy_from_env()
    assert pol.allow_hosts == frozenset({"falcon-demo-bank.test"})
    monkeypatch.delenv("FL_EGRESS_ALLOW_HOSTS")
    assert guard.policy_from_env().allow_hosts == frozenset()
