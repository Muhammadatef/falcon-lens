"""Helpers for the domain/infrastructure signals: registrable domain, guarded JSON fetch, error mapping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import tldextract

from falcon_core.security.http import FetchFailed
from falcon_core.security.ssrf import SSRFBlocked
from falcon_core.signals.base import Evidence, SignalSpec
from falcon_core.signals.url.canonical import canonicalize

# ICANN section only: RDAP/CT answer for the registry-level domain, not for a tenant of a private suffix.
_ICANN = tldextract.TLDExtract(
    suffix_list_urls=(), include_psl_private_domains=False, cache_dir=None
)

MAX_JSON_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Target:
    domain: str  # ICANN registrable domain, ASCII (punycode) form
    tld: str  # last label, ASCII


def target_domain(url: str | None) -> Target | None:
    """Registrable domain to look up, or None (raw IP host, no public suffix, not http(s))."""
    c = canonicalize(url or "")
    if not c.ok or c.is_ip or c.is_data_uri or not c.host_ascii:
        return None
    ext = _ICANN(c.host_ascii)
    dom = ext.top_domain_under_public_suffix
    if not dom:
        return None
    dom = dom.lower()
    return Target(domain=dom, tld=dom.rsplit(".", 1)[-1])


def error_evidence(spec: SignalSpec, msg: str, source: str) -> Evidence:
    return Evidence(
        signal=spec.name,
        family=spec.family,
        observed=None,
        polarity="neutral",
        source=source,
        tier=spec.tier,
        confidence=0.0,
        error=msg,
    )


class FetchError(Exception):
    """Mapped transport failure; ``code`` is stable and goes into Evidence.error."""

    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


async def fetch_json(
    http: Any, url: str, *, timeout_s: float, max_bytes: int = MAX_JSON_BYTES
) -> Any:
    """GET ``url`` through the guarded client and parse JSON. Raises FetchError with a stable code."""
    if http is None:
        raise FetchError("no_http_client")
    try:
        res = await http.fetch(url, timeout=timeout_s, max_bytes=max_bytes)
    except SSRFBlocked as exc:
        raise FetchError(f"ssrf_blocked:{exc.reason.value}") from exc
    except FetchFailed as exc:
        raise FetchError(exc.reason.value) from exc
    if res.status == 404:
        raise FetchError("not_found", 404)
    if res.status == 429:
        raise FetchError("rate_limited", 429)
    if res.status >= 400:
        raise FetchError(f"http_{res.status}", res.status)
    try:
        return json.loads(res.body)
    except ValueError as exc:
        raise FetchError("bad_json") from exc
