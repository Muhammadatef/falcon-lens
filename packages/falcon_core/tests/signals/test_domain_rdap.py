import asyncio
import json
import os
from typing import Any

import pytest
from netfakes import NOW, Ctx, FakeHTTP, fixture, result, validate

from falcon_core.security.http import FetchFailed, FetchFailReason
from falcon_core.security.ssrf import BlockReason, SSRFBlocked
from falcon_core.signals import REGISTRY
from falcon_core.signals.base import Evidence
from falcon_core.signals.domain import rdap

BOOT = "https://data.iana.org/rdap/dns.json"
RDAP = "https://rdap.registry.test/com/v1/domain/"


def routes() -> dict[str, object]:
    return {BOOT: result(fixture("iana_dns.json")), RDAP: result(fixture("rdap_domain.json"))}


async def run(ctx: Any) -> list[Evidence]:
    _spec, fn = REGISTRY["domain.age_days"]
    return await fn(ctx)


def test_registered_with_spec() -> None:
    spec, _ = REGISTRY["domain.age_days"]
    assert spec.family == "domain" and spec.network == "egress_proxy" and spec.timeout_ms <= 2500


async def test_age_and_registrar() -> None:
    http = FakeHTTP(routes())
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/login", http=http))
    validate([ev])
    assert ev.error is None and ev.source == "rdap"
    assert ev.observed["age_days"] == 7  # 2026-11-15 -> 2026-11-22
    assert ev.observed["registrar"] == "Synthetic Registrar LLC"
    assert ev.polarity == "risk"  # < 30 days
    assert http.calls[-1] == RDAP + "falcon-demo-shop.com"


async def test_subdomain_queries_registrable_domain() -> None:
    http = FakeHTTP(routes())
    await run(Ctx(url="https://secure.login.falcon-demo-shop.com/", http=http))
    assert http.calls[-1] == RDAP + "falcon-demo-shop.com"


async def test_old_domain_is_trust() -> None:
    doc = json.loads(fixture("rdap_domain.json"))
    doc["events"][0]["eventDate"] = "2005-01-01T00:00:00Z"
    http = FakeHTTP({BOOT: result(fixture("iana_dns.json")), RDAP: result(doc)})
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=http))
    assert ev.polarity == "trust" and ev.observed["age_days"] > 3650


async def test_cache_hit_avoids_second_call() -> None:
    http = FakeHTTP(routes())
    ctx = Ctx(url="https://falcon-demo-shop.com/", http=http)
    first = await run(ctx)
    n = len(http.calls)
    second = await run(ctx)
    assert len(http.calls) == n == 2  # bootstrap + domain, once
    assert second[0].observed == first[0].observed


async def test_bootstrap_cached_across_domains() -> None:
    http = FakeHTTP(routes())
    cache = Ctx().cache
    await run(Ctx(url="https://falcon-demo-shop.com/", http=http, cache=cache))
    await run(Ctx(url="https://another-demo-site.net/", http=http, cache=cache))
    assert sum(1 for c in http.calls if c == BOOT) == 1


async def test_single_flight_collapses_concurrent_lookups() -> None:
    http = FakeHTTP(routes())
    cache = Ctx().cache
    outs = await asyncio.gather(
        *[run(Ctx(url="https://falcon-demo-shop.com/", http=http, cache=cache)) for _ in range(6)]
    )
    assert all(o[0].error is None for o in outs)
    assert sum(1 for c in http.calls if c.startswith(RDAP)) == 1


async def test_unsupported_tld_is_error_evidence_and_negative_cached() -> None:
    http = FakeHTTP(routes())
    ctx = Ctx(url="https://falcon-demo-shop.ae/", http=http)
    (ev,) = await run(ctx)
    validate([ev])
    assert ev.error == "rdap_unsupported_tld" and ev.observed is None and ev.confidence == 0.0
    n = len(http.calls)
    (ev2,) = await run(ctx)
    assert ev2.error == "rdap_unsupported_tld" and len(http.calls) == n


async def test_not_found() -> None:
    r = routes()
    r[RDAP] = result("{}", 404)
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(r)))
    assert ev.error == "rdap_not_found"


async def test_arabic_idn_host_queries_punycode() -> None:
    http = FakeHTTP(routes())
    await run(Ctx(url="https://متجر-الصقر.com/", http=http))
    assert "xn--" in http.calls[-1] and http.calls[-1].startswith(RDAP)


async def test_cyrillic_confusable_host_is_looked_up_as_its_own_domain() -> None:
    http = FakeHTTP(routes())
    await run(Ctx(url="https://fаlcon-demo-shop.com/", http=http))  # Cyrillic a
    assert http.calls[-1].startswith(RDAP + "xn--")


async def test_raw_ip_and_empty() -> None:
    assert await run(Ctx(url="http://203.0.113.9/x", http=FakeHTTP({}))) == []
    assert await run(Ctx(url=None, http=FakeHTTP({}))) == []


async def test_no_http_client_is_error() -> None:
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=None))
    assert ev.error == "rdap_no_http_client"


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (FetchFailed(FetchFailReason.TIMEOUT), "rdap_timeout"),
        (FetchFailed(FetchFailReason.CONNECT_ERROR, "ConnectError"), "rdap_connect_error"),
        (SSRFBlocked(BlockReason.PRIVATE), "rdap_ssrf_blocked:private"),
    ],
)
async def test_transport_errors_become_evidence(exc: Exception, code: str) -> None:
    r = routes()
    r[RDAP] = exc
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(r)))
    validate([ev])
    assert ev.error == code


async def test_http_500_is_error_not_cached() -> None:
    r = routes()
    r[RDAP] = result("oops", 503)
    ctx = Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(r))
    (ev,) = await run(ctx)
    assert ev.error == "rdap_http_503"
    assert await ctx.cache.get("rdap:falcon-demo-shop.com") is None


async def test_signal_timeout_budget_becomes_error() -> None:
    r = routes()
    r[RDAP] = ("sleep", 5.0)
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(r)))
    assert ev.error == "timeout" and ev.signal == "domain.age_days"
    assert ev.latency_ms is not None and ev.latency_ms < 3500


async def test_missing_registration_event() -> None:
    doc = json.loads(fixture("rdap_domain.json"))
    doc["events"] = []
    r = routes()
    r[RDAP] = result(doc)
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(r)))
    assert ev.error == "rdap_no_registration_date"


def test_parse_bootstrap_prefers_https_and_skips_empty() -> None:
    m = rdap.parse_bootstrap(json.loads(fixture("iana_dns.json")))
    assert m["com"] == "https://rdap.registry.test/com/v1/"
    assert m["xn--mgbaam7a8h"] == "https://rdap.imaginary-ae.test/"
    assert "org" not in m


def test_clock_is_injected() -> None:
    assert NOW > 0


@pytest.mark.skipif(os.environ.get("FL_NETWORK_TESTS") != "1", reason="live network test (FL_NETWORK_TESTS=1)")
async def test_live_rdap_example_com() -> None:
    from falcon_core.security.http import GuardedHTTPClient

    async with GuardedHTTPClient() as http:
        (ev,) = await run(Ctx(url="https://example.com/", http=http, clock=__import__("time").time))
    assert ev.error is None, ev.error
    assert ev.observed["age_days"] > 3650 and ev.polarity == "trust"
