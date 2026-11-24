"""Hunt runtime (T-034): kill switch, pause, fixture cycle, DNS, CT, keyed sources, HTTP-client rule, linking.

No network: every outbound call goes to httpx.MockTransport; time is a FakeClock.
"""

from __future__ import annotations

import ast
import json
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import pytest
from sentinel_core.hunt.candidates import Candidate
from sentinel_core.hunt.config import default_config

from falcon_core.signals.brands.registry import default_registry
from falcon_sentinel.hunt import runtime
from falcon_sentinel.hunt.clock import FakeClock
from falcon_sentinel.hunt.http import HostNotAllowed, HuntHTTP, api_client
from falcon_sentinel.hunt.link import HuntLinker
from falcon_sentinel.hunt.scheduler import PAUSE_KEY, HuntScheduler, make_guard
from falcon_sentinel.hunt.settings import HuntSettings
from falcon_sentinel.hunt.sources.base import SourceDisabled
from falcon_sentinel.hunt.sources.ct import Backoff, CrtSh, CtSearchSource, RateWait
from falcon_sentinel.hunt.sources.dns import DohResolver, TokenBucket
from falcon_sentinel.hunt.sources.keyed import KEYED
from falcon_sentinel.hunt.store import MemoryHuntStore
from falcon_sentinel.hunt.submit import Submitter

HUNT_SRC = Path(__file__).resolve().parents[1] / "src" / "falcon_sentinel" / "hunt"
ALLOW = ("crt.sh", "dns.google")
DOH = HuntSettings().doh_url  # the DoH endpoint from settings (not a fixture URL)


class Recorder:
    """MockTransport handler that records every request."""

    def __init__(self, fn: Any) -> None:
        self.fn, self.requests = fn, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        return self.fn(req)


def _api(state: str = "queued") -> Recorder:
    n = {"i": 0}

    def fn(req: httpx.Request) -> httpx.Response:
        n["i"] += 1
        vid = f"vd_{n['i']:026d}"
        headers = {"X-Verdict-State": state}
        return httpx.Response(202, json={"verdict_id": vid, "events_url": "", "status_url": ""}, headers=headers)

    return Recorder(fn)


def _dns_answer(status: int, types: list[int] = ()) -> dict[str, Any]:  # type: ignore[assignment]
    return {"Status": status, "Answer": [{"name": "x.", "type": t, "TTL": 300, "data": "x"} for t in types]}


def _sched(
    settings: HuntSettings,
    store: MemoryHuntStore,
    redis: Any,
    clock: FakeClock,
    egress: Recorder | None = None,
    api: Recorder | None = None,
    brands: list[str] | None = None,
) -> HuntScheduler:
    http = None
    if egress is not None:
        http = HuntHTTP(proxy=None, allow_hosts=ALLOW, guard=make_guard(redis), transport=httpx.MockTransport(egress))
    sub = Submitter(api_client("http://api.test", "k", httpx.MockTransport(api))) if api is not None else None
    return HuntScheduler(
        settings=settings,
        config=default_config(),
        registry=default_registry(),
        store=store,
        redis=redis,
        clock=clock,
        http=http,
        submitter=sub,
        brands=brands,
    )


@pytest.fixture
def redis() -> Any:
    return fakeredis.FakeAsyncRedis(decode_responses=True)


# ---------------------------------------------------------------- kill switch


def test_enabled_defaults_false_even_with_sources_on_in_yaml() -> None:
    s = HuntSettings.from_env({})
    assert s.enabled is False  # master switch wins over hunt.yaml default_enabled
    assert s.sources == ("permutation",)
    assert "ct_lookup" not in s.sources and "ct_search" not in s.sources
    assert HuntSettings.from_env({"FL_HUNT_ENABLED": "true"}).enabled is True
    assert HuntSettings.from_env({"FL_HUNT_CT_MIN_INTERVAL_S": "5"}).ct_min_interval_s == 120  # floor
    offline = HuntSettings.from_env(
        {"FL_SOVEREIGN_MODE": "1", "FL_OFFLINE_LOOKUPS": "true", "FL_HUNT_SOURCES": "permutation,fixture"}
    )
    assert offline.active_sources() == ("fixture",)


async def test_disabled_never_starts_and_makes_no_request(redis: Any) -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=_dns_answer(0, [2])))
    async with AsyncExitStack() as stack:
        task = await runtime.maybe_start(
            stack, HuntSettings.from_env({}), MemoryHuntStore(), redis, egress_transport=httpx.MockTransport(rec)
        )
    assert task is None
    assert rec.requests == []


def test_http_refuses_without_proxy() -> None:
    with pytest.raises(ValueError, match="FL_HUNT_PROXY"):
        HuntHTTP(proxy=None, allow_hosts=ALLOW)


async def test_http_allow_list_in_process() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json={}))
    h = HuntHTTP(proxy=None, allow_hosts=ALLOW, transport=httpx.MockTransport(rec))
    for url in ("https://falcon-demo-bank-secure.test/", "http://crt.sh/", "https://crt.sh.example/"):
        with pytest.raises(HostNotAllowed):
            await h.get_json(url)
    await h.get_json("https://crt.sh/", params={"q": "x"})
    assert len(rec.requests) == 1


# ---------------------------------------------------------------- pause


async def test_pause_mid_cycle_stops_requests(redis: Any) -> None:
    clock = FakeClock()

    def fn(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_dns_answer(3))

    rec = Recorder(fn)
    settings = replace(HuntSettings(), sources=("permutation",), dns_max_per_cycle=50)
    sched = _sched(settings, MemoryHuntStore(), redis, clock, egress=rec, api=_api())
    orig = rec.fn

    def pausing(req: httpx.Request) -> httpx.Response:
        if len(rec.requests) == 3:
            redis_sync_flag["set"] = True
        return orig(req)

    redis_sync_flag: dict[str, bool] = {}
    rec.fn = pausing

    async def guard() -> None:
        if redis_sync_flag.get("set"):
            await redis.set(PAUSE_KEY, "1")
        if await redis.get(PAUSE_KEY):
            from falcon_sentinel.hunt.sources.base import Paused

            raise Paused("x")

    assert sched.http is not None
    sched.http.guard = guard
    res = await sched.run_cycle()
    assert res["outcome"] == "paused"
    assert len(rec.requests) == 3  # nothing left after the pause was set
    again = await sched.run_cycle()
    assert again["outcome"] == "paused" and len(rec.requests) == 3


# ---------------------------------------------------------------- fixture cycle


async def test_fixture_cycle_dedupes_thresholds_and_quota(redis: Any) -> None:
    clock = FakeClock()
    store = MemoryHuntStore()
    api = _api()
    settings = replace(HuntSettings(), sources=("fixture",), submit_max_per_hour=2, prescore_min=60)
    res = await _sched(settings, store, redis, clock, api=api).run_cycle()
    assert res["outcome"] == "ok"
    rows = await store.list()
    names = sorted(c.domain for c in rows)
    # www.<name> deduped onto the registrable name; the official demo domain is never a candidate
    assert names == ["falcon-demo-bank-cloak.test", "falcon-demo-bank-login.test", "falcon-demo-bank-secure.test"]
    assert all(c.provenance["source"] == "fixture" for c in rows)
    assert all(c.prescore >= 60 for c in rows)
    assert len(api.requests) == 2  # FL_HUNT_SUBMIT_MAX_PER_HOUR
    statuses = sorted(c.status for c in rows)
    assert statuses == ["skipped_quota", "submitted", "submitted"]
    body = json.loads(api.requests[0].content)
    assert body["channel"] == "hunt" and body["url"].startswith("http://falcon-demo-bank-")
    assert api.requests[0].headers["x-falcon-source"] == "fixture"
    assert api.requests[0].headers["idempotency-key"].startswith("hc_")
    # second run and a restart (new scheduler, same store) submit nothing twice
    await _sched(settings, store, redis, clock, api=api).run_cycle()
    assert len(api.requests) == 2
    clock.advance(3600)  # next hour: only the skipped one goes
    await _sched(settings, store, redis, clock, api=api).run_cycle()
    assert len(api.requests) == 3
    assert len({json.loads(r.content)["url"] for r in api.requests}) == 3
    assert not await redis.exists("fl:events")  # hunt never publishes domain.observed (or anything)


async def test_below_threshold_recorded_never_visited(redis: Any) -> None:
    store, api = MemoryHuntStore(), _api()
    settings = replace(HuntSettings(), sources=("fixture",), prescore_min=101)
    await _sched(settings, store, redis, FakeClock(), api=api).run_cycle()
    assert api.requests == [] and {c.status for c in await store.list()} == {"new"}


async def test_already_known_when_api_answers_cached(redis: Any) -> None:
    store, api = MemoryHuntStore(), _api(state="cached")
    await _sched(replace(HuntSettings(), sources=("fixture",)), store, redis, FakeClock(), api=api).run_cycle()
    rows = await store.list()
    assert {c.status for c in rows} == {"already_known"}
    assert all(c.verdict_id is None for c in rows)  # a person's verdict is never taken as a hunt verdict


async def test_jobs_lag_holds_submission(redis: Any) -> None:
    store, api = MemoryHuntStore(), _api()
    sched = _sched(replace(HuntSettings(), sources=("fixture",)), store, redis, FakeClock(), api=api)

    async def lag() -> int:
        return 21

    sched.jobs_lag = lag
    res = await sched.run_cycle()
    assert res["stats"].get("held_for_lag") and api.requests == []


# ---------------------------------------------------------------- DNS


async def test_nxdomain_on_ns_gives_unregistered_and_no_a_mx(redis: Any) -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=_dns_answer(3)))
    h = HuntHTTP(proxy=None, allow_hosts=ALLOW, transport=httpx.MockTransport(rec))
    dns = DohResolver(h, DOH, 5, FakeClock())
    res = await dns.check("falcon-demo-bank-pay.test")
    assert res.registered is False
    assert [r.url.params["type"] for r in rec.requests] == ["2"]
    assert all(r.url.params["edns_client_subnet"] == "0.0.0.0/0" for r in rec.requests)
    again = await dns.check("falcon-demo-bank-pay.test")  # negative cache
    assert again.registered is False and len(rec.requests) == 1


async def test_registered_gets_a_and_mx() -> None:
    def fn(req: httpx.Request) -> httpx.Response:
        t = int(req.url.params["type"])
        return httpx.Response(200, json=_dns_answer(0, [t]))

    rec = Recorder(fn)
    h = HuntHTTP(proxy=None, allow_hosts=ALLOW, transport=httpx.MockTransport(rec))
    res = await DohResolver(h, DOH, 5, FakeClock()).check("falcon-demo-bank-pay.test")
    assert res.registered and res.has_a and res.has_mx
    assert [r.url.params["type"] for r in rec.requests] == ["2", "1", "15"]


async def test_servfail_is_unknown_not_unregistered() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=_dns_answer(2)))
    h = HuntHTTP(proxy=None, allow_hosts=ALLOW, transport=httpx.MockTransport(rec))
    assert (await DohResolver(h, DOH, 5, FakeClock()).check("a-b.test")).registered is None


async def test_token_bucket_holds_qps() -> None:
    clock = FakeClock()
    bucket = TokenBucket(5.0, clock)
    times = []
    for _ in range(26):
        await bucket.acquire()
        times.append(clock.monotonic())
    for i in range(len(times)):
        window = [t for t in times if times[i] <= t < times[i] + 1.0]
        assert len(window) <= 5  # FL_HUNT_DNS_QPS, no burst
    assert times[-1] - times[0] >= 25 / 5 - 1e-6


# ---------------------------------------------------------------- CT


def _ct(handler: Any, clock: FakeClock) -> tuple[CrtSh, Recorder]:
    rec = Recorder(handler)
    h = HuntHTTP(proxy=None, allow_hosts=ALLOW, transport=httpx.MockTransport(rec))
    return CrtSh(h, clock, 120), rec


async def test_ct_breaker_backoff_grows() -> None:
    clock = FakeClock()
    seq = iter([httpx.Response(429), "timeout", httpx.Response(200, json=[])])

    def fn(req: httpx.Request) -> httpx.Response:
        nxt = next(seq)
        if nxt == "timeout":
            raise httpx.ReadTimeout("t", request=req)
        assert isinstance(nxt, httpx.Response)
        return nxt

    crt, rec = _ct(fn, clock)
    with pytest.raises(Backoff):
        await crt.lookup("falcon-demo-bank-pay.test")
    first_wait = crt.breaker.open_until - clock.monotonic()
    with pytest.raises(Backoff):
        await crt.lookup("falcon-demo-bank-pay.test")  # breaker open: no call made
    assert len(rec.requests) == 1
    clock.advance(first_wait + 1)
    with pytest.raises(Backoff):
        await crt.lookup("falcon-demo-bank-pay.test")  # timeout
    second_wait = crt.breaker.open_until - clock.monotonic()
    assert second_wait > first_wait
    clock.advance(second_wait + 1)
    s = await crt.lookup("falcon-demo-bank-pay.test")
    assert s.certs_seen == 0 and crt.breaker.failures == 0


async def test_ct_min_interval_between_calls() -> None:
    clock = FakeClock()
    crt, rec = _ct(lambda r: httpx.Response(200, json=[]), clock)
    await crt.lookup("a-falcon.test")
    with pytest.raises(RateWait):
        await crt.lookup("b-falcon.test")
    clock.advance(119)
    with pytest.raises(RateWait):
        await crt.lookup("b-falcon.test")
    clock.advance(1)
    await crt.lookup("b-falcon.test")
    gaps = [b - a for a, b in zip(crt.call_times, crt.call_times[1:], strict=False)]
    assert gaps and min(gaps) >= 120
    assert len(rec.requests) == 2


async def test_ct_fresh_and_empty_list_never_changes_status(redis: Any) -> None:
    clock = FakeClock()
    nb = (clock.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")

    def fn(req: httpx.Request) -> httpx.Response:
        if req.url.host == "crt.sh":
            q = req.url.params["q"]
            rows = (
                [{"name_value": q, "not_before": nb, "issuer_name": "C=ZZ, O=Test CA"}] if q.startswith("fresh") else []
            )
            return httpx.Response(200, json=rows)
        t = int(req.url.params["type"])
        return httpx.Response(200, json=_dns_answer(0, [t]))

    rec = Recorder(fn)
    store = MemoryHuntStore()
    settings = replace(HuntSettings(), sources=("permutation", "ct_lookup"), dns_max_per_cycle=2, prescore_min=101)
    sched = _sched(settings, store, redis, clock, egress=rec, api=_api())
    assert sched.crt is not None
    s = await sched.crt.lookup("fresh-falcon.test")
    assert s.fresh and s.first_not_before is not None
    clock.advance(121)
    before = Candidate(
        domain="empty-falcon.test",
        brand_id="x",
        discovery="permutation",
        permutation_kind="typo",
        first_seen=clock.now(),
        provenance={"source": "live"},
        reasons=("resolves_a",),
    )
    out = await sched._ct([before], {"ct": 0})
    assert out[0].status == before.status and out[0].reasons == before.reasons and out[0].upstream_seen is None


async def test_ct_search_off_by_default() -> None:
    assert "ct_search" not in HuntSettings.from_env({}).active_sources()
    assert default_config().sources["ct_search"].default_enabled is False
    crt, _rec = _ct(lambda r: httpx.Response(200, json=[]), FakeClock())
    src = CtSearchSource(crt, default_registry(), enabled=False)
    assert src.status() == "disabled"
    with pytest.raises(SourceDisabled):
        await src.poll(None, None)


# ---------------------------------------------------------------- keyed + client rule


async def test_keyed_sources_need_key() -> None:
    for cls in KEYED:
        src = cls()
        assert src.status() == "ready_needs_key" and src.requires_key
        with pytest.raises(SourceDisabled):
            await src.poll(None, None)
    tree = ast.parse((HUNT_SRC / "sources" / "keyed.py").read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {m for m in imported if m.split(".")[0] in ("httpx", "requests", "urllib", "socket", "aiohttp")}


def test_only_http_module_builds_clients() -> None:
    bad = []
    for path in HUNT_SRC.rglob("*.py"):
        if path.name == "http.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name in (
                    "AsyncClient",
                    "Client",
                    "AsyncHTTPTransport",
                    "HTTPTransport",
                    "GuardedHTTPClient",
                    "urlopen",
                ):
                    bad.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module in ("requests", "aiohttp", "urllib.request"):
                bad.append(f"{path.name}:{node.lineno}")
    assert bad == []


# ---------------------------------------------------------------- consumer linking


def _verdict_event(vid: str, verdict: str, domain: str, **payload: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_id": "evt_01JC8Z9Q3M5N7P2R4T6V8W0XY" + vid[-1],
        "type": "verdict.created",
        "occurred_at": "2026-11-24T20:05:00Z",
        "source": "fixture",
        "verdict_id": vid,
        "payload": {"verdict": verdict, "registrable_domain": domain.replace(".", "[.]"), **payload},
    }


async def test_linker_trusts_table_not_label(redis: Any) -> None:
    clock = FakeClock()
    store = MemoryHuntStore()
    await _sched(replace(HuntSettings(), sources=("fixture",)), store, redis, clock, api=_api()).run_cycle()
    sub = [c for c in await store.list() if c.status == "submitted"][0]
    link = HuntLinker(store)
    ev = _verdict_event(str(sub.verdict_id), "dangerous", sub.domain, origin="user", hunt_lookalike=False)
    await link.annotate(ev)
    assert ev["payload"]["origin"] == "hunt" and ev["payload"]["hunt_lookalike"] is True
    got = await store.get_by_domain(sub.domain)
    assert got is not None and got.status == "confirmed" and got.verdict == "dangerous"
    assert got.time_to_detection_s is not None and got.time_to_detection_basis == "cert_not_before"
    spoof = _verdict_event("vd_" + "9" * 26, "dangerous", "falcon-demo-bank-x.test", channel="hunt", origin="hunt")
    await link.annotate(spoof)
    assert spoof["payload"]["origin"] == "user" and "hunt_lookalike" not in spoof["payload"]
    # a later person check of the same domain records the lead once
    user = _verdict_event("vd_" + "8" * 26, "dangerous", sub.domain)
    user["occurred_at"] = "2026-11-24T21:00:00Z"
    await link.annotate(user)
    after = await store.get_by_domain(sub.domain)
    assert after is not None and after.first_user_seen is not None
