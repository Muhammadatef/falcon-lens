from __future__ import annotations

import pytest
from starlette.requests import Request

from falcon_api.app import client_ip


def _req(peer: str | None, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


def test_gateway_peer_with_header_uses_header() -> None:
    assert client_ip(_req("172.20.0.5", {"X-Falcon-Client-IP": "203.0.113.9"})) == "203.0.113.9"


def test_two_visitors_get_two_ips() -> None:
    a = client_ip(_req("172.20.0.5", {"X-Falcon-Client-IP": "203.0.113.9"}))
    b = client_ip(_req("172.20.0.5", {"X-Falcon-Client-IP": "198.51.100.7"}))
    assert a != b


def test_gateway_peer_ignores_xff_and_cf_headers() -> None:
    h = {"X-Forwarded-For": "1.2.3.4", "Cf-Connecting-Ip": "5.6.7.8"}
    assert client_ip(_req("172.20.0.5", h)) == "172.20.0.5"


@pytest.mark.parametrize("peer", ["8.8.8.8", "2001:4860:4860::8888"])
def test_non_gateway_peer_with_spoofed_headers_uses_peer(peer: str) -> None:
    h = {"X-Falcon-Client-IP": "9.9.9.9", "X-Forwarded-For": "9.9.9.9", "Cf-Connecting-Ip": "9.9.9.9"}
    assert client_ip(_req(peer, h)) == peer


@pytest.mark.parametrize("bad", ["", "not-an-ip", "1.2.3.4, 5.6.7.8", "999.1.1.1", "1.2.3.4:80"])
def test_malformed_header_uses_peer(bad: str) -> None:
    assert client_ip(_req("172.20.0.5", {"X-Falcon-Client-IP": bad})) == "172.20.0.5"


def test_ipv6_header_and_peer() -> None:
    assert client_ip(_req("fd00::2", {"X-Falcon-Client-IP": "2001:db8::1"})) == "2001:db8::1"
    assert client_ip(_req("fd00::2", {})) == "fd00::2"


def test_no_client() -> None:
    assert client_ip(_req(None, {"X-Falcon-Client-IP": "1.2.3.4"})) == "unknown"
