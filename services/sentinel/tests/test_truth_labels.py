"""Provenance label (fixture hosts are never "live") and shared-platform suffixes are never indicators."""

from __future__ import annotations

import pytest
from sentinel_core.correlate import registrable_domain

from falcon_core.provenance import effective_source, fixture_hosts, is_fixture_domain, is_shared_platform

HOSTS = frozenset({"falcon-demo-bank-secure.test", "fixtures"})
PLATFORMS = [
    "pages.dev",
    "github.io",
    "vercel.app",
    "netlify.app",
    "workers.dev",
    "web.app",
    "firebaseapp.com",
    "blogspot.com",
]


@pytest.mark.parametrize("host", PLATFORMS)
def test_shared_platform_suffix_is_not_an_indicator(host: str) -> None:
    assert is_shared_platform(host) and is_shared_platform(host.replace(".", "[.]"))
    assert registrable_domain(host) == ""
    assert registrable_domain(f"https://{host}/x") == ""


@pytest.mark.parametrize("host", PLATFORMS)
def test_the_registrable_name_under_a_platform_is_the_indicator(host: str) -> None:
    assert registrable_domain(f"evil-login.{host}") == f"evil-login.{host}"
    assert registrable_domain(f"a.b.evil-login.{host}") == f"evil-login.{host}"
    assert not is_shared_platform(f"evil-login.{host}")


def test_ordinary_domains_unchanged() -> None:
    assert registrable_domain("a.b.example.com") == "example.com"
    assert not is_shared_platform("example.com") and not is_shared_platform("localhost")


def test_fixture_label_comes_from_config_and_fails_closed() -> None:
    env = {"FL_ENV": "demo", "FL_SSRF_ALLOW_HOSTS": "fixtures, Falcon-Demo-Bank-Secure.test"}
    assert fixture_hosts(env) == frozenset({"fixtures", "falcon-demo-bank-secure.test"})
    assert fixture_hosts({**env, "FL_ENV": "production"}) == frozenset()
    assert fixture_hosts({"FL_SSRF_ALLOW_HOSTS": "fixtures"}) == frozenset()
    assert is_fixture_domain("falcon-demo-bank-secure[.]test", HOSTS)
    assert is_fixture_domain("http://x.falcon-demo-bank-secure.test/login", HOSTS)
    assert not is_fixture_domain("evil-falcon-demo-bank-secure.test", HOSTS)


def test_effective_source() -> None:
    assert effective_source("live", ["falcon-demo-bank-secure.test"], HOSTS) == "fixture"
    assert effective_source("live", ["falcon-demo-bank-secure.test", "real.example.com"], HOSTS) == "live"
    assert effective_source("live", [], HOSTS) == "live"
    assert effective_source("live", ["falcon-demo-bank-secure.test"], frozenset()) == "live"
    assert effective_source("replay", ["falcon-demo-bank-secure.test"], HOSTS) == "replay"


def test_real_public_domain_in_the_allow_list_stays_live() -> None:
    hosts = frozenset({"real-bank.com", "fixtures", "demo.test"})
    assert effective_source("live", ["real-bank.com"], hosts) == "live"
    assert effective_source("live", ["a.real-bank.com"], hosts) == "live"
    assert effective_source("live", ["fixtures", "demo.test"], hosts) == "fixture"
    assert not is_fixture_domain("real-bank.com", hosts)
