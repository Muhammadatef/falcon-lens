"""FL_SSRF_ALLOW_HOSTS defaults: only invented Falcon Demo Bank .test fixtures, honoured only in local/demo/ci."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from falcon_egress.guard import policy_from_env as egress_policy
from falcon_sandbox.settings import Settings as SandboxSettings
from falcon_worker.main import guard_policy

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RE = re.compile(r"\$\{FL_SSRF_ALLOW_HOSTS:-([^}]*)\}")


def _compose_defaults() -> set[str]:
    text = (ROOT / "docker-compose.yml").read_text()
    found = {m.group(1) for m in DEFAULT_RE.finditer(text)}
    assert found, "no FL_SSRF_ALLOW_HOSTS default in docker-compose.yml"
    return found


def _env_example() -> str:
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.startswith("FL_SSRF_ALLOW_HOSTS="):
            return line.split("=", 1)[1]
    raise AssertionError("FL_SSRF_ALLOW_HOSTS missing from .env.example")


def test_compose_default_is_one_list_everywhere() -> None:
    assert len(_compose_defaults()) == 1, "worker, sandbox and egress must share one default list"


def test_defaults_are_only_fixture_test_hosts() -> None:
    lists = {*_compose_defaults(), _env_example()}
    assert len(lists) == 1, "docker-compose.yml default and .env.example must agree"
    hosts = next(iter(lists)).split(",")
    for h in hosts:
        # `fixtures` is the nginx service alias on the internal sandbox network; the rest are invented .test hosts.
        assert h == "fixtures" or (h.endswith(".test") and h.startswith(("falcon-demo-bank", "falcon-bot-relay"))), h
    assert {"falcon-demo-bank-injection.test", "falcon-demo-bank-cloak.test", "falcon-bot-relay.test"} <= set(hosts)


def test_compose_fixture_aliases_cover_the_allow_list() -> None:
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    aliases = set(doc["services"]["fixtures"]["networks"]["sandbox"]["aliases"])
    assert set(_env_example().split(",")) <= aliases


@pytest.mark.parametrize("env", ["local", "demo", "ci"])
def test_hosts_honoured_in_non_production_envs(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("FL_ENV", env)
    monkeypatch.setenv("FL_SSRF_ALLOW_HOSTS", _env_example())
    assert "falcon-demo-bank-injection.test" in guard_policy().allow_hosts
    assert "falcon-demo-bank-injection.test" in SandboxSettings.from_env().allow_hosts
    monkeypatch.setenv("FL_EGRESS_ALLOW_HOSTS", _env_example())
    assert "falcon-demo-bank-injection.test" in egress_policy().allow_hosts


@pytest.mark.parametrize("env", ["production", "prod", "staging", "", "Local"])
def test_hosts_ignored_outside_local_demo_ci(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("FL_ENV", env)
    monkeypatch.setenv("FL_SSRF_ALLOW_HOSTS", _env_example())
    assert not guard_policy().allow_hosts
    assert not SandboxSettings.from_env().allow_hosts
    monkeypatch.setenv("FL_EGRESS_ALLOW_HOSTS", _env_example())
    assert not egress_policy().allow_hosts


def test_hosts_ignored_when_fl_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FL_ENV", raising=False)
    monkeypatch.setenv("FL_SSRF_ALLOW_HOSTS", _env_example())
    assert not guard_policy().allow_hosts
    assert not SandboxSettings.from_env().allow_hosts
    monkeypatch.setenv("FL_EGRESS_ALLOW_HOSTS", _env_example())
    assert not egress_policy().allow_hosts
