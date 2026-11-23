"""Cascade tier exits (SCORING §1.6) and end-to-end verdicts with stubbed sandbox and feeds."""

from __future__ import annotations

from typing import Any

from cascade_helpers import assert_valid, make_cascade, metric, rules, run

from falcon_core.cascade import StubSandboxClient
from falcon_core.cascade.engine import url_sha256
from falcon_core.cascade.testing import (
    DEMO_BENIGN_URL,
    DEMO_LOOKALIKE_URL,
    DEMO_OFFICIAL_URL,
    DEMO_ZERO_DAY_URL,
    SlowSandbox,
    benign_features,
    loaded_mirror,
    official_features,
    phish_features,
    slow_signal,
)
from falcon_core.signals.base import Evidence as SignalEvidence
from falcon_core.signals.base import SignalContext, SignalSpec
from falcon_core.signals.url.canonical import canonicalize


def _all_valid(docs: list[dict[str, Any]]) -> None:
    assert docs, "nothing emitted"
    for d in docs:
        assert_valid(d)
    assert [d["final"] for d in docs].count(True) == 1
    assert docs[-1]["final"] is True
    assert len({d["verdict_id"] for d in docs}) == 1


# --- end-to-end scenarios ----------------------------------------------------------------------


async def test_lookalike_is_dangerous_via_h1_at_t2() -> None:
    sandbox = StubSandboxClient(default=phish_features())
    cascade, m = make_cascade(sandbox)
    sink = await run(cascade, DEMO_LOOKALIKE_URL)
    _all_valid(sink.docs)
    final = sink.docs[-1]
    assert final["verdict"] == "dangerous"
    assert final["tier_reached"] == "T2"
    assert final["model_route"] == "none"
    assert final["risk_score"] >= 95
    assert "H1" in rules(final)
    h1_ids = {e["id"] for e in final["evidence"] if e.get("hard_rule") == "H1"}
    assert any(set(r["evidence_ids"]) & h1_ids for r in final["reasons"])
    assert final["impersonated_brand"]["brand_id"] == "falcon_demo_bank"
    assert final["canonical_url"].startswith("hxxps://")
    assert "." not in final["canonical_url"].replace("[.]", "")
    assert final["actions"]["report"]["en"]
    assert [d["tier_reached"] for d in sink.docs] == ["T0", "T1", "T2"]
    assert sandbox.calls == [canonicalize(DEMO_LOOKALIKE_URL).url]
    labels = {"input_type": "url", "verdict": "dangerous", "tier": "T2", "route": "none"}
    assert metric(m, "fl_checks_total", {**labels, "source": "live"}) == 1


async def test_zero_day_without_url_cues_still_h1() -> None:
    cascade, _ = make_cascade(StubSandboxClient(default=phish_features(DEMO_ZERO_DAY_URL)))
    sink = await run(cascade, DEMO_ZERO_DAY_URL)
    _all_valid(sink.docs)
    t1 = next(d for d in sink.docs if d["tier_reached"] == "T1")
    assert t1["final"] is False
    final = sink.docs[-1]
    assert final["verdict"] == "dangerous" and "H1" in rules(final)


async def test_official_is_no_warning_signs_with_caution_h3() -> None:
    sandbox = StubSandboxClient(default=official_features())
    cascade, _ = make_cascade(sandbox)
    sink = await run(cascade, DEMO_OFFICIAL_URL)
    _all_valid(sink.docs)
    final = sink.docs[-1]
    assert final["verdict"] == "no_warning_signs"
    assert final["actions"]["caution"]["ar"] and final["actions"]["caution"]["en"]
    assert "H3" in rules(final)
    assert final["degraded"] is False
    assert final["tier_reached"] == "T1"  # H3 decides; rendering cannot change a capped verdict
    assert sandbox.calls == []
    assert final["impersonated_brand"] is None


async def test_degraded_signal_timeout_never_no_warning_signs() -> None:
    cascade, m = make_cascade(
        StubSandboxClient(default=benign_features()),
        extra_signals={"url.slow_probe": slow_signal()},
    )
    sink = await run(cascade, DEMO_BENIGN_URL)
    _all_valid(sink.docs)
    final = sink.docs[-1]
    assert final["degraded"] is True
    assert final["verdict"] != "no_warning_signs"
    assert "signal_error:url.slow_probe" in final["degraded_reasons"]
    assert metric(m, "fl_tool_errors_total", {"tool": "url.slow_probe", "reason": "timeout"}) == 1
    assert metric(m, "fl_degraded_total") == 1
    for d in sink.docs:  # partials too
        assert not (d["degraded"] and d["verdict"] == "no_warning_signs")


async def test_degraded_on_official_domain_is_suspicious() -> None:
    cascade, _ = make_cascade(extra_signals={"url.slow_probe": slow_signal()})
    sink = await run(cascade, DEMO_OFFICIAL_URL)
    final = sink.docs[-1]
    assert_valid(final)
    assert final["degraded"] is True and final["verdict"] == "suspicious"


async def test_benign_page_is_no_warning_signs() -> None:
    cascade, _ = make_cascade(StubSandboxClient(default=benign_features()))
    sink = await run(cascade, DEMO_BENIGN_URL)
    _all_valid(sink.docs)
    final = sink.docs[-1]
    assert final["verdict"] == "no_warning_signs" and final["actions"]["caution"]
    assert final["tier_reached"] == "T2"


# --- T0 ----------------------------------------------------------------------------------------


async def test_t0_fresh_feed_hit_exits_dangerous_h2() -> None:
    url = "https://synthetic-feed-entry.test/a"
    sandbox = StubSandboxClient(error="must_not_render")
    cascade, _ = make_cascade(sandbox, mirror=loaded_mirror([url], age_s=600))
    sink = await run(cascade, url)
    _all_valid(sink.docs)
    assert len(sink.docs) == 1
    final = sink.docs[0]
    assert final["verdict"] == "dangerous" and final["tier_reached"] == "T0"
    assert "H2" in rules(final)
    ev = next(e for e in final["evidence"] if e["signal"] == "rep.openphish")
    assert ev["tier"] == "T0" and ev["observed"]["fresh"] is True and ev["observed"]["match"] == "url"
    assert "synthetic-feed-entry" not in str(ev["observed"])  # hash-only mirror, no URL echoed
    assert sandbox.calls == []


async def test_t0_host_listing_hits_whole_host() -> None:
    cascade, _ = make_cascade(mirror=loaded_mirror(["https://synthetic-feed-entry.test/"]))
    final = (await run(cascade, "https://synthetic-feed-entry.test/other/page")).docs[-1]
    assert final["verdict"] == "dangerous" and "H2" in rules(final)


async def test_t0_stale_feed_hit_is_not_h2() -> None:
    url = "https://synthetic-feed-entry.test/b"
    cascade, _ = make_cascade(
        StubSandboxClient(default=benign_features(url)), mirror=loaded_mirror([url], 7 * 3600), t1_model=None
    )  # draft p_clf: T1 evidence adds to it
    sink = await run(cascade, url)
    final = sink.docs[-1]
    assert "H2" not in rules(final)
    assert final["verdict"] != "no_warning_signs"  # +6.0 still applies


async def test_t0_mirror_never_loaded_does_not_degrade() -> None:
    from falcon_core.signals.cache import MemoryCache
    from falcon_core.signals.reputation.mirror import FeedMirror

    cascade, _ = make_cascade(StubSandboxClient(default=benign_features()), mirror=FeedMirror(MemoryCache()))
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert not final["degraded"]
    assert any(e["signal"] == "rep.openphish" and e.get("error") == "feed_disabled" for e in final["evidence"])


async def test_t0_stale_feed_hit_does_not_degrade() -> None:
    url = "https://synthetic-feed-entry.test/c"
    cascade, _ = make_cascade(StubSandboxClient(default=benign_features(url)), mirror=loaded_mirror([url], 7 * 3600))
    final = (await run(cascade, url)).docs[-1]
    assert "H2" not in rules(final) and not final["degraded"]


async def test_t0_redis_exception_degrades() -> None:
    class Boom:
        async def get(self, *_a: object, **_k: object) -> None:
            raise ConnectionError("redis down")

        async def sismember(self, *_a: object, **_k: object) -> None:
            raise ConnectionError("redis down")

    from falcon_core.signals.reputation.mirror import FeedMirror

    cascade, _ = make_cascade(StubSandboxClient(default=benign_features()), mirror=FeedMirror(Boom()))  # type: ignore[arg-type]
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] and "signal_error:rep.openphish" in final["degraded_reasons"]


class _MemCache:
    """Read-side cache stub; the test writes it like the worker sink would after publishing."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)


async def test_t0_cache_hit_reissues_under_new_id() -> None:
    cache = _MemCache()
    sandbox = StubSandboxClient(default=phish_features())
    cascade, m = make_cascade(sandbox, cache=cache)
    first = (await run(cascade, DEMO_LOOKALIKE_URL)).docs[-1]
    cache.data[url_sha256(canonicalize(DEMO_LOOKALIKE_URL))] = first
    second = await run(cascade, DEMO_LOOKALIKE_URL)
    assert len(second.docs) == 1
    doc = second.docs[0]
    assert_valid(doc)
    assert doc["verdict_id"] != first["verdict_id"]
    assert doc["verdict"] == first["verdict"] and doc["evidence"] == first["evidence"]
    assert second.meta[0]["reissued_from"] == first["verdict_id"]
    assert len(sandbox.calls) == 1
    assert metric(m, "fl_cache_hits_total", {"layer": "verdict"}) == 1


async def test_cached_degraded_verdict_is_ignored() -> None:
    cache = _MemCache()
    cascade, _ = make_cascade(
        StubSandboxClient(default=benign_features()), extra_signals={"url.slow_probe": slow_signal()}
    )
    degraded = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert degraded["degraded"] is True
    cache.data[url_sha256(canonicalize(DEMO_BENIGN_URL))] = degraded
    sandbox = StubSandboxClient(default=benign_features())
    cascade2, m = make_cascade(sandbox, cache=cache)
    final = (await run(cascade2, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] is False and len(sandbox.calls) == 1
    assert metric(m, "fl_cache_hits_total", {"layer": "verdict"}) == 0


class _FlakySink:
    """Fails the first final emit (Redis down), like a broken PUBLISH."""

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    async def emit(self, doc: dict[str, Any], meta: Any) -> None:
        if doc["final"]:
            raise ConnectionError("redis down")
        self.docs.append(doc)


async def test_sink_failure_on_final_propagates_and_is_not_rescored() -> None:
    import pytest

    from falcon_core.cascade import SinkError, new_verdict_id

    cascade, m = make_cascade(StubSandboxClient(default=phish_features()))
    sink = _FlakySink()
    with pytest.raises(SinkError):
        await cascade.run_url(new_verdict_id(), DEMO_LOOKALIKE_URL, sink)
    assert all(not d["final"] for d in sink.docs)  # no second, degraded final
    assert not any("internal_error" in str(d.get("degraded_reasons")) for d in sink.docs)
    labels = {"input_type": "url", "verdict": "dangerous", "tier": "T2", "route": "none", "source": "live"}
    assert metric(m, "fl_checks_total", labels) == 0  # not counted until published


async def test_cascade_bug_after_final_does_not_emit_second_final() -> None:
    from falcon_core.cascade import CallbackSink, new_verdict_id

    calls = {"n": 0}

    async def after(doc: dict[str, Any], meta: Any) -> None:
        if doc["final"]:
            calls["n"] += 1

    cascade, _ = make_cascade(StubSandboxClient(default=benign_features()))
    sink = CallbackSink(after)
    await cascade.run_url(new_verdict_id(), DEMO_BENIGN_URL, sink)
    assert calls["n"] == 1
    assert [d["final"] for d in sink.docs].count(True) == 1


async def test_t0_ssrf_blocked_metadata_ip_is_degraded_and_counted() -> None:
    sandbox = StubSandboxClient(error="must_not_render")
    cascade, m = make_cascade(sandbox)
    sink = await run(cascade, "http://169.254.169.254/latest/meta-data/")
    _all_valid(sink.docs)
    final = sink.docs[-1]
    assert final["verdict"] != "no_warning_signs"
    assert final["degraded"] or final["verdict"] == "dangerous"
    assert sandbox.calls == []
    total = sum(
        s.value
        for fam in m.registry.collect()
        if fam.name == "fl_ssrf_blocked"
        for s in fam.samples
        if s.name == "fl_ssrf_blocked_total"
    )
    assert total == 1


async def test_invalid_url_gives_degraded_final() -> None:
    cascade, _ = make_cascade()
    sink = await run(cascade, "javascript:alert(1)")
    _all_valid(sink.docs)
    assert sink.docs[-1]["degraded"] is True and sink.docs[-1]["tier_reached"] == "T0"


# --- T1 ----------------------------------------------------------------------------------------


def _const_signal(name: str, observed: dict[str, Any]) -> Any:
    spec = SignalSpec(name=name, family="url", tier="T1", input_types=("url",), timeout_ms=50,
                      network="none", emits=(name,))  # fmt: skip

    async def fn(ctx: SignalContext) -> list[SignalEvidence]:
        return [SignalEvidence(signal=name, family="url", observed=observed)]

    return spec, fn


async def test_t1_confident_high_exits_without_sandbox() -> None:
    sigs = {
        "url.userinfo_trick": _const_signal("url.userinfo_trick", {"present": True}),
        "url.bidi_or_zero_width": _const_signal("url.bidi_or_zero_width", {"present": True}),
        "url.raw_ip_host": _const_signal("url.raw_ip_host", {"present": True}),
    }
    sandbox = StubSandboxClient(error="must_not_render")
    cascade, _ = make_cascade(sandbox, signals=sigs, t1_model=None)  # draft p_clf: signal evidence drives p
    sink = await run(cascade, "https://plain-host.test/")
    _all_valid(sink.docs)
    final = sink.docs[-1]
    assert final["tier_reached"] == "T1" and final["verdict"] == "dangerous"
    assert sandbox.calls == []
    assert 1 <= len(final["reasons"]) <= 3


async def test_t1_uncertain_escalates_and_partial_is_not_final() -> None:
    sandbox = StubSandboxClient(default=benign_features())
    cascade, m = make_cascade(sandbox)
    sink = await run(cascade, DEMO_BENIGN_URL)
    assert [d["final"] for d in sink.docs] == [False, False, True]
    assert metric(m, "fl_escalations_total", {"from": "T1", "to": "T2"}) == 1


async def test_t1_signals_run_concurrently() -> None:
    # Deterministic: every signal waits on a barrier that opens only once all N have started.
    # If signals ran sequentially the first would never be released and would hit the bound.
    import asyncio

    n = 5
    started = 0
    all_started = asyncio.Event()

    def mk(i: int) -> Any:
        name = f"url.sleepy{i}"
        spec = SignalSpec(name=name, family="url", tier="T1", input_types=("url",),
                          timeout_ms=5000, network="none", emits=(name,))  # fmt: skip

        async def fn(ctx: SignalContext) -> list[SignalEvidence]:
            nonlocal started
            started += 1
            if started == n:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=2.0)
            return []

        return spec, fn

    cascade, _ = make_cascade(signals={f"url.sleepy{i}": mk(i) for i in range(n)})
    await run(cascade, "https://plain-host.test/")
    assert started == n and all_started.is_set()


async def test_crashing_signal_is_error_evidence_not_crash() -> None:
    spec = SignalSpec(name="url.crashy", family="url", tier="T1", input_types=("url",),
                      timeout_ms=50, network="none", emits=())  # fmt: skip

    async def boom(ctx: SignalContext) -> list[SignalEvidence]:
        raise RuntimeError("boom")

    cascade, _ = make_cascade(StubSandboxClient(default=benign_features()),
                              extra_signals={"url.crashy": (spec, boom)})  # fmt: skip
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert_valid(final)
    assert final["degraded"] and final["verdict"] != "no_warning_signs"


# --- T2 ----------------------------------------------------------------------------------------


async def test_t2_sandbox_failure_degrades() -> None:
    cascade, m = make_cascade(StubSandboxClient(error="timeout"))
    sink = await run(cascade, DEMO_LOOKALIKE_URL)
    _all_valid(sink.docs)
    final = sink.docs[-1]
    assert final["degraded"] is True and final["verdict"] != "no_warning_signs"
    assert any(r.startswith("sandbox_unavailable") for r in final["degraded_reasons"])
    assert metric(m, "fl_tool_errors_total", {"tool": "sandbox", "reason": "timeout"}) == 1


async def test_t2_sandbox_timeout_is_enforced() -> None:
    cascade, m = make_cascade(SlowSandbox(benign_features(), delay_s=1.0), sandbox_timeout_s=0.05)
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] and final["verdict"] == "suspicious"  # no page-independent trust evidence
    assert metric(m, "fl_sandbox_timeouts_total") == 1


async def test_t2_uncertain_band_records_t3_escalation() -> None:
    # Hotlinked brand assets (+2.0) on an unrelated page: p ~ 0.45, inside the T2 band.
    feats = benign_features()
    feats = feats.model_copy(update={"hotlinked_origins": ["https://falcon-demo-bank.test"]})
    cascade, m = make_cascade(StubSandboxClient(default=feats))
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert_valid(final)
    assert final["tier_reached"] == "T2" and final["model_route"] == "none"
    assert final["verdict"] == "suspicious"
    assert metric(m, "fl_escalations_total", {"from": "T2", "to": "T3"}) == 1
    assert "T3 escalation recorded" in final["trace"][-1]["summary"]


async def test_t2_exfil_to_bot_is_h4() -> None:
    from falcon_core.cascade import SandboxForm

    feats = benign_features().model_copy(
        update={"forms": [SandboxForm(fields=["password"], action_origin="api.telegram.org")]}
    )
    cascade, _ = make_cascade(StubSandboxClient(default=feats))
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["verdict"] == "dangerous" and "H4" in rules(final)


async def test_extractor_hook_is_called() -> None:
    from falcon_core.cascade.evidence import make_evidence

    class Ext:
        calls = 0

        async def extract(self, features: Any, verdict_id: str) -> list[Any]:
            Ext.calls += 1
            return [make_evidence("injection.instruction_like_text", "injection", {"present": True},
                                  tier="T2", source="llm:extractor")]  # fmt: skip

    cascade, _ = make_cascade(StubSandboxClient(default=benign_features()), extractor=Ext())
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert Ext.calls == 1
    assert any(e["signal"] == "injection.instruction_like_text" for e in final["evidence"])
