"""Sentinel dashboard metrics: node durations, LLM ask outcomes, template-vs-LLM share, approval turnaround."""

from __future__ import annotations

from graph_helpers import make_env

from falcon_core.telemetry.metrics import REGISTRY as FL_REGISTRY
from falcon_sentinel.llm import StubLLM
from falcon_sentinel.metrics import SentinelMetrics


def val(name: str, **labels: str) -> float:
    return FL_REGISTRY.get_sample_value(name, labels) or 0.0


async def test_triage_run_records_nodes_llm_asks_text_source_and_turnaround() -> None:
    nodes = {n: val("fl_sentinel_node_seconds_count", node=n) for n in ("enrich", "assess", "summarise", "propose")}
    asks = val("fl_sentinel_llm_calls_total", task="summarise", outcome="ok")
    llm_text = val("fl_sentinel_text_total", task="summarise", generated_by="llm")
    env = await make_env()
    iid = env.campaign_id()
    runner = env.runner(StubLLM())
    await runner.run(iid)
    for n, before in nodes.items():
        assert val("fl_sentinel_node_seconds_count", node=n) == before + 1, n
    assert val("fl_sentinel_llm_calls_total", task="summarise", outcome="ok") == asks + 1
    assert val("fl_sentinel_text_total", task="summarise", generated_by="llm") == llm_text + 1
    (td,) = [a for a in (env.cache.get(iid) or {})["actions"] if a["tool"] == "draft_takedown"]
    before = val("fl_approval_turnaround_seconds_count", decision="reject")
    act_before = val("fl_sentinel_node_seconds_count", node="act")  # act pauses for approval: timed when it finishes
    await runner.reject(iid, td["action_id"], "op_bob")
    assert val("fl_approval_turnaround_seconds_count", decision="reject") == before + 1
    assert val("fl_sentinel_node_seconds_count", node="act") == act_before + 1


async def test_template_fallback_is_counted_when_the_verifier_rejects() -> None:
    before = val("fl_sentinel_text_total", task="summarise", generated_by="template")
    env = await make_env()
    iid = env.campaign_id()
    bad = StubLLM(
        overrides={"summarise": lambda u: {"en": "x", "ar": "y", "claims": [{"text_en": "u", "evidence_ids": []}]}}
    )
    await env.runner(bad).run(iid)
    assert val("fl_sentinel_text_total", task="summarise", generated_by="template") == before + 1


async def test_incident_status_gauge_follows_the_cache() -> None:
    env = await make_env()
    SentinelMetrics().refresh_gauges(env.cache.all())
    total = sum(
        val("fl_incident_status", status=s) for s in ("open", "triaging", "awaiting_approval", "mitigated", "closed")
    )
    assert total == len(env.cache.all())


def test_sentinel_series_are_on_the_registry_that_metrics_serves() -> None:
    """falcon_core.service renders the shared registry only; Sentinel metrics on another registry never reached Prometheus."""
    from prometheus_client import generate_latest

    from falcon_core.telemetry import metrics as tm
    from falcon_sentinel import metrics as sm

    assert sm.INCIDENTS_TOTAL is tm.INCIDENTS and sm.EVENT_LAG is tm.EVENT_LAG
    sm.INCIDENTS_TOTAL.labels("campaign", "high", "replay").inc()
    sm.NODE_SECONDS.labels("enrich").observe(0.1)
    text = generate_latest(tm.REGISTRY).decode()
    assert "fl_incidents_total{" in text and "fl_sentinel_node_seconds_bucket" in text
