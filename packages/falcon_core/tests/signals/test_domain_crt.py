import asyncio
import json
import os
from typing import Any

import pytest
from netfakes import Ctx, FakeHTTP, fixture, result, validate

from falcon_core.security.http import FetchFailed, FetchFailReason
from falcon_core.signals import REGISTRY
from falcon_core.signals.base import Evidence
from falcon_core.signals.domain import crt

CRT = "https://crt.sh/?q=falcon-demo-shop.com&output=json"


@pytest.fixture(autouse=True)
def _reset() -> None:
    crt.reset_backoff()


async def run(ctx: Any) -> list[Evidence]:
    _spec, fn = REGISTRY["domain.cert_age_days"]
    return await fn(ctx)


def by_name(evs: list[Evidence]) -> dict[str, Evidence]:
    return {e.signal: e for e in evs}


async def test_three_evidence_items() -> None:
    http = FakeHTTP({"https://crt.sh/": result(fixture("crtsh.json"))})
    evs = await run(Ctx(url="https://falcon-demo-shop.com/pay", http=http))
    validate(evs)
    got = by_name(evs)
    assert set(got) == {"domain.cert_age_days", "domain.cert_issuer", "domain.ct_siblings"}
    age = got["domain.cert_age_days"]
    assert age.observed["cert_age_days"] == 4  # first cert 2026-11-18 -> 2026-11-22
    assert age.observed["certs_seen"] == 3 and age.polarity == "risk" and age.source == "crt"
    assert got["domain.cert_issuer"].observed["issuer"] == "Synthetic CA"  # latest cert's issuer
    sib = got["domain.ct_siblings"].observed
    assert sib["domains"] == ["falcon-demo-pay.net", "sibling-one.com"] and sib["count"] == 2
    assert http.calls == [CRT]


async def test_fresh_cert_is_risk() -> None:
    rows = json.loads(fixture("crtsh.json"))
    for r in rows:
        r["not_before"] = "2026-11-21T00:00:00"
    http = FakeHTTP({"https://crt.sh/": result(rows)})
    got = by_name(await run(Ctx(url="https://falcon-demo-shop.com/", http=http)))
    assert got["domain.cert_age_days"].polarity == "risk"


async def test_cache_hit_avoids_second_call() -> None:
    http = FakeHTTP({"https://crt.sh/": result(fixture("crtsh.json"))})
    ctx = Ctx(url="https://falcon-demo-shop.com/", http=http)
    a = await run(ctx)
    b = await run(ctx)
    assert len(http.calls) == 1
    assert [e.observed for e in a] == [e.observed for e in b]


async def test_single_flight() -> None:
    http = FakeHTTP({"https://crt.sh/": result(fixture("crtsh.json"))})
    cache = Ctx().cache
    await asyncio.gather(*[run(Ctx(url="https://falcon-demo-shop.com/", http=http, cache=cache)) for _ in range(5)])
    assert len(http.calls) == 1


async def test_no_certs_is_neutral_not_error() -> None:
    http = FakeHTTP({"https://crt.sh/": result("[]")})
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=http))
    validate([ev])
    assert ev.error is None and ev.observed == {"cert_age_days": None, "certs_seen": 0}


async def test_rate_limit_triggers_backoff_without_hammering() -> None:
    http = FakeHTTP({"https://crt.sh/": result("slow down", 429)})
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=http))
    assert ev.error == "crt_rate_limited"
    (ev2,) = await run(Ctx(url="https://example.org/", http=http))  # different domain, breaker open
    assert ev2.error == "crt_backoff" and len(http.calls) == 1


async def test_timeout_and_bad_json_are_errors() -> None:
    http = FakeHTTP({"https://crt.sh/": FetchFailed(FetchFailReason.TIMEOUT)})
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=http))
    assert ev.error == "crt_timeout"
    crt.reset_backoff()
    http = FakeHTTP({"https://crt.sh/": result("<html>")})
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=http))
    assert ev.error == "crt_bad_json"
    crt.reset_backoff()
    http = FakeHTTP({"https://crt.sh/": result('{"not": "a list"}')})
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=http))
    assert ev.error == "crt_bad_json"


async def test_signal_budget_timeout() -> None:
    http = FakeHTTP({"https://crt.sh/": ("sleep", 5.0)})
    (ev,) = await run(Ctx(url="https://falcon-demo-shop.com/", http=http))
    assert ev.error == "timeout" and ev.signal == "domain.cert_age_days"


async def test_arabic_domain_uses_punycode_query() -> None:
    http = FakeHTTP({"https://crt.sh/": result("[]")})
    await run(Ctx(url="https://متجر-الصقر.com/", http=http))
    assert "q=xn--" in http.calls[0]


def test_issuer_org_parsing() -> None:
    assert crt.issuer_org("C=US, O=Let's Encrypt, CN=R11") == "Let's Encrypt"
    assert crt.issuer_org("CN=Only CN") == "Only CN"
    assert crt.issuer_org("garbage") == "garbage"


def test_siblings_capped_and_exclude_self() -> None:
    rows = [
        {
            "name_value": "\n".join(f"a.sib{i}.com" for i in range(60)) + "\nfalcon-demo-shop.com",
            "not_before": "2026-11-20T00:00:00",
            "issuer_name": "O=X",
        }
    ]
    s = crt.summarize(rows, "falcon-demo-shop.com")
    assert s["siblings_total"] == 60 and len(s["siblings"]) == crt.MAX_SIBLINGS


@pytest.mark.skipif(os.environ.get("FL_NETWORK_TESTS") != "1", reason="live network test (FL_NETWORK_TESTS=1)")
async def test_live_crt_example_com() -> None:
    import time

    from falcon_core.security.http import GuardedHTTPClient

    async with GuardedHTTPClient() as http:
        evs = await run(Ctx(url="https://example.com/", http=http, clock=time.time))
    assert evs and (evs[0].error is None or evs[0].error.startswith("crt_"))
