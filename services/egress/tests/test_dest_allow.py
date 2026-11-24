"""FL_EGRESS_DEST_ALLOW: the voice proxy instance may reach only the model hosts."""

import asyncio
from collections.abc import Sequence

import pytest

from falcon_egress import guard

PUBLIC = "93.184.215.14"


async def resolver(host: str) -> Sequence[str]:
    return [PUBLIC]


@pytest.fixture(autouse=True)
def _allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_EGRESS_DEST_ALLOW", "huggingface.co, hf.co")


@pytest.mark.parametrize("host", ["huggingface.co", "cdn-lfs.huggingface.co", "cas-bridge.xethub.hf.co", "HF.CO."])
def test_model_hosts_pass(host: str) -> None:
    assert asyncio.run(guard.check(host, 443, resolver=resolver)).allowed


@pytest.mark.parametrize("host", ["example.com", "evilhuggingface.co", "huggingface.co.evil.example", "hf.co.example"])
def test_everything_else_is_refused(host: str) -> None:
    d = asyncio.run(guard.check(host, 443, resolver=resolver))
    assert not d.allowed
    assert d.reason == "destination_not_allowed"


def test_plain_http_is_filtered_too() -> None:
    d = asyncio.run(guard.check_url("http://example.com/x", resolver=resolver))
    assert d.reason == "destination_not_allowed"


def test_private_addresses_still_blocked_for_allowed_hosts() -> None:
    async def inside(host: str) -> Sequence[str]:
        return ["10.0.0.5"]

    assert asyncio.run(guard.check("huggingface.co", 443, resolver=inside)).reason == "private"


def test_unset_means_no_extra_restriction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FL_EGRESS_DEST_ALLOW")
    assert asyncio.run(guard.check("example.com", 443, resolver=resolver)).allowed
