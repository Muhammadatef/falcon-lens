"""FL_EGRESS_DEST_ALLOW for hunt-egress: only crt.sh and the DoH resolver (docs/design/HUNTER.md section 9)."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from falcon_egress import guard

PUBLIC = "93.184.215.14"
COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


async def resolver(host: str) -> Sequence[str]:
    return [PUBLIC]


def _hunt_allow() -> str:
    svc = yaml.safe_load(COMPOSE.read_text())["services"]["hunt-egress"]
    return str(svc["environment"]["FL_EGRESS_DEST_ALLOW"])


@pytest.fixture(autouse=True)
def _allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_EGRESS_DEST_ALLOW", _hunt_allow())


def test_compose_lists_exactly_two_hosts() -> None:
    assert sorted(h.strip() for h in _hunt_allow().split(",")) == ["crt.sh", "dns.google"]


@pytest.mark.parametrize("host", ["crt.sh", "dns.google", "CRT.SH."])
def test_hunt_hosts_pass(host: str) -> None:
    assert asyncio.run(guard.check(host, 443, resolver=resolver)).allowed


@pytest.mark.parametrize(
    "host",
    [
        "falcon-demo-bank-secure.test",
        "example.com",
        "evilcrt.sh",
        "crt.sh.example",
        "dns.google.example",
        "huggingface.co",
    ],
)
def test_everything_else_is_refused(host: str) -> None:
    d = asyncio.run(guard.check(host, 443, resolver=resolver))
    assert not d.allowed
    assert d.reason == "destination_not_allowed"
