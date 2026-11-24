"""Provenance helpers shared by the worker, Sentinel and API.

Two jobs:
- `effective_source`: a check or incident whose domains are all internal fixture hosts (the allow-list
  in ``FL_SSRF_ALLOW_HOSTS``, honoured only in local, demo and ci) is a test fixture, never "live".
  The label comes from configuration, not from guessing at brand names.
- `is_shared_platform`: a shared hosting or platform suffix (pages.dev, github.io, vercel.app ...) from the
  Public Suffix List (private section included) is never an indicator by itself; only the name under it is.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping

from falcon_core.signals.url.canonical import psl_split

ALLOWLIST_ENVS = frozenset({"local", "demo", "ci"})
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")


def _host(value: str) -> str:
    v = value.strip().lower().replace("[.]", ".").replace("(.)", ".")
    v = _SCHEME.sub("", v)
    return re.split(r"[/?#]", v, maxsplit=1)[0].rsplit("@", 1)[-1].split(":", 1)[0].strip(".")


def fixture_hosts(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """Internal fixture hosts. Fail closed: empty unless FL_ENV is local, demo or ci."""
    e = os.environ if env is None else env
    if e.get("FL_ENV") not in ALLOWLIST_ENVS:
        return frozenset()
    return frozenset(h.strip().lower() for h in e.get("FL_SSRF_ALLOW_HOSTS", "").split(",") if h.strip())


def is_fixture_domain(value: str, hosts: frozenset[str] | None = None) -> bool:
    hs = fixture_hosts() if hosts is None else hosts
    h = _host(value)
    return bool(h) and any(h == f or h.endswith("." + f) for f in hs)


def effective_source(source: str, domains: Iterable[str], hosts: frozenset[str] | None = None) -> str:
    """ "live" becomes "fixture" when there is at least one domain and every domain is a fixture host."""
    if source != "live":
        return source
    hs = fixture_hosts() if hosts is None else hosts
    ds = [d for d in domains if d]
    if hs and ds and all(is_fixture_domain(d, hs) for d in ds):
        return "fixture"
    return source


def is_shared_platform(value: str) -> bool:
    """True when the host is itself a public or private-section suffix (pages.dev, github.io, co.uk ...)."""
    h = _host(value)
    if "." not in h:
        return False
    _sub, dom, suffix, _private = psl_split(h)
    return not dom and bool(suffix)
