"""The metric list in docs/OBSERVABILITY.md is the contract: parse it and compare."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from prometheus_client import generate_latest

from falcon_core.telemetry import metrics as m

DOC = Path(__file__).resolve().parents[4] / "docs" / "OBSERVABILITY.md"
_ITEM = re.compile(r"`([a-z_]+)(?:\{([^}]*)\})?`(?:\s*\(([^)]*)\))?")


def _doc_metrics() -> dict[str, tuple[str, ...]]:
    text = DOC.read_text(encoding="utf-8")
    block = text.split("**Metrics (the contract", 1)[1].split("Helpers live in", 1)[0]
    found: dict[str, tuple[str, ...]] = {}
    for line in block.splitlines():
        if not line.startswith("- "):
            continue
        for name, labels, _ in _ITEM.findall(line.split(":", 1)[1]):
            found[f"fl_{name}"] = tuple(x.strip() for x in labels.split(",") if x.strip())
    return found


def _registered() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for fam in m.REGISTRY.collect():
        name = fam.name + "_total" if fam.type == "counter" else fam.name
        labels: set[str] = set()
        for s in fam.samples:
            labels |= set(s.labels) - {"le"}
        out[name] = tuple(sorted(labels))
    return out


def test_doc_parses_all_sections() -> None:
    assert len(_doc_metrics()) == 62


def test_every_documented_metric_exists_exactly() -> None:
    documented = _doc_metrics()
    registered = {c.name for c in m.REGISTRY.collect()}
    for name in documented:
        base = name.removesuffix("_total")
        assert name.startswith("fl_")
        assert base in registered, f"{name} missing from registry"


def test_no_undocumented_metrics() -> None:
    documented = {n.removesuffix("_total") for n in _doc_metrics()}
    registered = {c.name for c in m.REGISTRY.collect()}
    assert registered == documented


def test_labels_match_doc() -> None:
    # Touch every labelled metric once so samples (and label names) exist.
    m.record_verdict(input_type="url", verdict="dangerous", tier="T0", route="none", source="replay")
    m.ESCALATIONS.labels("T0", "T1").inc()
    m.CACHE_HITS.labels("redis").inc()
    m.VOICE_CHECKS.labels("dangerous").inc()
    m.TOOL_ERRORS.labels("whois", "timeout").inc()
    m.FEED_AGE.labels("openphish").set(1)
    m.FEED_ENABLED.labels("openphish").set(1)
    m.record_llm(model="x", role="judge", input_tokens=1, fallback=True)
    m.SSRF_BLOCKED.labels("private_ip").inc()
    m.RATE_LIMITED.labels("ip").inc()
    m.CAMPAIGN_NEW_DOMAINS.labels("falcon_demo_bank", "replay").inc()
    m.BRAND_IMPERSONATION.labels("falcon_demo_bank").inc()
    m.USER_FEEDBACK.labels("false_positive").inc()
    m.record_campaign_board_view("list")
    m.EVAL_METRIC.labels("f1", "test", "cascade").set(0.5)
    m.record_incident(type="campaign", severity="high", source="replay")
    m.INCIDENT_OPEN.labels("high").set(1)
    m.RULE_FIRED.labels("R1").inc()
    m.SENTINEL_ACTIONS.labels("draft", "dry_run").inc()
    m.LLM_CALLS.labels("extractor", "local", "ok", "false").inc()
    m.LLM_CALL_SECONDS.labels("extractor", "local").observe(0.1)
    m.LLM_RESULTS.labels("extractor", "ok").inc()
    m.HARD_RULE_FIRED.labels("H1", "floor_dangerous").inc()
    m.EVIDENCE_SEEN.labels("url.entropy").inc()
    m.SANDBOX_RENDERS.labels("ok").inc()
    m.AGENT_TOOL_CALLS.labels("rdap_lookup", "ok").inc()
    m.DEGRADED_REASONS.labels("sandbox_unavailable:timeout").inc()
    m.QUEUE_DEPTH.labels("jobs", "lag").set(1)
    m.SENTINEL_NODE_SECONDS.labels("enrich").observe(0.1)
    m.SENTINEL_LLM_CALLS.labels("assess", "ok").inc()
    m.SENTINEL_LLM_SECONDS.labels("assess").observe(0.1)
    m.SENTINEL_TEXT.labels("assess", "llm").inc()
    m.APPROVAL_TURNAROUND.labels("approve").observe(60)
    m.INCIDENT_STATUS.labels("open").set(1)
    m.HUNT_CYCLES.labels("ok", "fixture").inc()
    m.HUNT_SOURCE_REQUESTS.labels("dns", "ok", "live").inc()
    m.HUNT_CANDIDATES.labels("ct", "fixture").inc()
    m.HUNT_SUBMITTED.labels("fixture").inc()
    m.HUNT_CONFIRMED.labels("dangerous", "fixture").inc()
    m.HUNT_ALREADY_KNOWN.labels("live").inc()
    m.HUNT_QUOTA_REMAINING.labels("hour", "live").set(1)
    m.HUNT_ENABLED.labels("live").set(0)
    m.HUNT_LAST_SUCCESS.labels("dns", "live").set(1)
    m.HUNT_TIME_TO_DETECTION.labels("cert_not_before", "fixture").observe(60)
    m.HUNT_LEAD.labels("live").observe(60)
    with m.timed_stage("t0"):
        pass
    registered = _registered()
    for name, labels in _doc_metrics().items():
        if labels:
            assert registered[name] == tuple(sorted(labels)), name


def test_stage_buckets_cover_10ms_to_20s() -> None:
    assert m.STAGE_LATENCY_BUCKETS[0] == 0.01
    assert m.STAGE_LATENCY_BUCKETS[-1] == 20.0
    assert 8.0 in m.STAGE_LATENCY_BUCKETS  # SLO boundary


def test_timed_stage_context_and_decorator() -> None:
    def count(stage: str) -> float:
        return m.REGISTRY.get_sample_value("fl_stage_latency_seconds_count", {"stage": stage}) or 0.0

    before = count("ut")
    with m.timed_stage("ut"):
        pass

    @m.timed_stage("ut")
    def f() -> int:
        return 1

    assert f() == 1
    with pytest.raises(RuntimeError), m.timed_stage("ut"):
        raise RuntimeError
    assert count("ut") == before + 3


async def test_timed_stage_async() -> None:
    @m.timed_stage("ut_async")
    async def f() -> int:
        return 2

    assert await f() == 2
    assert m.REGISTRY.get_sample_value("fl_stage_latency_seconds_count", {"stage": "ut_async"}) == 1.0


def test_record_verdict_source_and_validation() -> None:
    labels = {
        "input_type": "url", "verdict": "dangerous", "tier": "T1", "route": "none",
        "source": "live",
    }  # fmt: skip
    before = m.REGISTRY.get_sample_value("fl_checks_total", labels) or 0.0
    m.record_verdict(input_type="url", verdict="dangerous", tier="T1", route="none")
    assert m.REGISTRY.get_sample_value("fl_checks_total", labels) == before + 1
    with pytest.raises(ValueError):
        m.record_verdict(
            input_type="url",
            verdict="x",
            tier="T0",
            route="none",
            source="bogus",  # type: ignore[arg-type]
        )


def test_record_llm() -> None:
    m.record_llm(model="mm", role="ut_role", input_tokens=10, output_tokens=5, cost_usd=0.01,
                 fallback=True)  # fmt: skip
    g = m.REGISTRY.get_sample_value
    assert g("fl_llm_tokens_total", {"model": "mm", "role": "ut_role"}) == 15
    assert g("fl_llm_cost_usd_total", {"model": "mm"}) == pytest.approx(0.01)
    assert g("fl_llm_fallback_total", {"role": "ut_role"}) == 1


def test_metrics_endpoint_exposes_fl_registry() -> None:
    from fastapi.testclient import TestClient

    from falcon_core.service import create_app

    m.record_verdict(input_type="url", verdict="dangerous", tier="T0", route="none")
    body = TestClient(create_app("unit")).get("/metrics").text
    assert "fl_checks_total{" in body and 'source="live"' in body
    assert b"fl_checks_total" in generate_latest(m.REGISTRY)


@pytest.mark.parametrize(("tier", "route"), [("t0", "none"), ("T4", "none"), ("T0", "cascade")])
def test_record_verdict_rejects_non_contract_labels(tier: str, route: str) -> None:
    with pytest.raises(ValueError):
        m.record_verdict(input_type="url", verdict="dangerous", tier=tier, route=route)
