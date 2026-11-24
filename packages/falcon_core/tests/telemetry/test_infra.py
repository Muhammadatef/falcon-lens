"""Static checks on the committed infra: alert rules, runbook anchors, dashboards."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
RULES = sorted((ROOT / "infra" / "prometheus" / "rules").glob("*.yml"))
DASHBOARDS = sorted((ROOT / "infra" / "grafana" / "dashboards").glob("*.json"))
EXPECTED_UIDS = {
    "fl-command-overview",
    "fl-detection-quality",
    "fl-pipeline",
    "fl-ai-ops",
    "fl-security",
    "fl-sentinel",
    "fl-model-quality",
}


def _runbook_anchors() -> set[str]:
    """RUNBOOK headings such as `## a / b / c` define one anchor per alert id."""
    anchors: set[str] = set()
    for line in (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            anchors |= {part.strip() for part in line[3:].split("/")}
    return anchors


def _documented_metrics() -> set[str]:
    text = (ROOT / "docs" / "OBSERVABILITY.md").read_text(encoding="utf-8")
    block = text.split("**Metrics (the contract", 1)[1].split("Helpers live in", 1)[0]
    names = {f"fl_{n}" for n in re.findall(r"`([a-z_]+)(?:\{[^}]*\})?`", block)}
    # metrics served by other processes (API, egress proxy, evals-exporter) are documented right after the list
    outside = text.split("**Outside the contract list above**", 1)[1].split("**Dashboards**", 1)[0]
    return names | {
        f"fl_{n}"
        for n in re.findall(r"`([a-z_]+)(?:\{[^}]*\})?`", outside)
        if n.startswith(("api_", "egress_", "eval_", "voice_utterances", "voice_latency", "voice_errors"))
    }


def _alert_rules() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for path in RULES:
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
            rules += [r for r in group["rules"] if "alert" in r]
    return rules


def test_every_alert_has_runbook_anchor() -> None:
    anchors = _runbook_anchors()
    rules = _alert_rules()
    assert len(rules) >= 15
    for rule in rules:
        url = rule["annotations"]["runbook_url"]
        assert url.startswith("docs/RUNBOOK.md#"), rule["alert"]
        assert url.split("#", 1)[1] in anchors, f"{rule['alert']}: {url}"
        assert rule["labels"]["severity"] in {"warning", "critical"}


def test_alert_names_unique() -> None:
    names = [r["alert"] for r in _alert_rules()]
    assert len(names) == len(set(names))


def test_rules_only_use_documented_metrics() -> None:
    documented = _documented_metrics()
    suffixes = ("_bucket", "_count", "_sum")
    for path in RULES:
        for name in set(re.findall(r"\bfl_[a-z_0-9]+", path.read_text(encoding="utf-8"))):
            base = name
            for s in suffixes:
                base = base.removesuffix(s)
            if name.startswith("fl_http_requests") or name.startswith("fl_service"):
                continue  # platform metrics from falcon_core.service
            assert base in documented or name in documented, name


def test_seven_dashboards_provisioned_with_5s_refresh() -> None:
    boards = [json.loads(p.read_text(encoding="utf-8")) for p in DASHBOARDS]
    assert {b["uid"] for b in boards} == EXPECTED_UIDS
    for b in boards:
        assert b["refresh"] == "5s"
        assert b["panels"]
        ids = [p["id"] for p in b["panels"]]
        assert len(ids) == len(set(ids))


def test_dashboards_use_only_documented_metrics_and_flag_replay() -> None:
    documented = _documented_metrics()
    for path in DASHBOARDS:
        board = json.loads(path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8")
        for name in set(re.findall(r"\bfl_[a-z_0-9]+", text)):
            base = re.sub(r"_(bucket|count|sum)$", "", name)
            assert base in documented or name in documented or name == "fl_http_requests_total", f"{path.name}: {name}"
        # REPLAY banner on every board, driven by the source label.
        banner = board["panels"][0]
        assert 'source="replay"' in banner["targets"][0]["expr"], path.name
        assert "REPLAY" in json.dumps(banner["fieldConfig"]["defaults"]["mappings"])
        # Every source-labelled series panel splits by source and paints REPLAY.
        for p in board["panels"]:
            exprs = " ".join(t.get("expr", "") for t in p.get("targets", []))
            sourced = re.search(r"fl_(checks|incidents|campaign_new_domains)_total", exprs)
            if sourced and p["type"] == "timeseries":
                assert "source" in exprs and "REPLAY" in exprs, f"{path.name}: {p['title']}"
                assert "REPLAY" in json.dumps(p["fieldConfig"]["overrides"])


def test_service_down_alert_covers_every_falcon_scrape_job() -> None:
    """A crashed service exports no fl_ metric, so only `up` can report it (audit 2026-11-23: the Sentinel
    restart-looped on the demo stack and no alert fired)."""
    rule = next(r for r in _alert_rules() if r["alert"] == "ServiceDown")
    assert re.search(r"\bup\{", rule["expr"]) and "== 0" in rule["expr"]
    assert rule["labels"]["severity"] == "critical"
    prom = yaml.safe_load((ROOT / "infra" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
    jobs = {j["job_name"]: j for j in prom["scrape_configs"]}
    pattern = re.search(r'job=~"([^"]+)"', rule["expr"])
    assert pattern, rule["expr"]
    covered = set(pattern.group(1).split("|"))
    assert covered <= set(jobs), covered - set(jobs)
    targets = {t for name in covered for sc in jobs[name]["static_configs"] for t in sc["targets"]}
    for service in ("api", "worker", "sentinel", "mcp", "egress-proxy", "gateway"):
        assert any(t.split(":")[0] == service for t in targets), service


def test_feed_stale_threshold_is_the_h2_freshness_window() -> None:
    from falcon_core.signals.reputation.mirror import FRESH_MAX_AGE_S

    rule = next(r for r in _alert_rules() if r["alert"] == "FeedStale")
    assert f"> {int(FRESH_MAX_AGE_S)} " in rule["expr"], rule["expr"]


def test_feed_gauges_are_on_the_registry_services_expose() -> None:
    from prometheus_client import generate_latest

    from falcon_core.signals.reputation import metrics as feed_metrics
    from falcon_core.telemetry.metrics import REGISTRY

    feed_metrics.set_enabled("audit_probe", True)
    feed_metrics.set_age("audit_probe", 42)
    text = generate_latest(REGISTRY).decode()
    assert 'fl_feed_age_seconds{feed="audit_probe"} 42.0' in text
    assert 'fl_feed_enabled{feed="audit_probe"} 1.0' in text


def test_route_agreement_has_no_value_before_the_first_shadow_sample() -> None:
    """A fresh process must not export 0 (it would read as 0% agreement and fire RouteAgreementDrop)."""
    import math
    import subprocess
    import sys

    code = (
        "from prometheus_client import generate_latest;"
        "from falcon_core.telemetry.metrics import REGISTRY;"
        "print([l for l in generate_latest(REGISTRY).decode().splitlines() if l.startswith('fl_route_agreement_ratio')][0])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)  # noqa: S603
    line = out.stdout.strip()
    assert math.isnan(float(line.split()[-1])), line


def test_otel_collector_authenticates_to_phoenix() -> None:
    cfg = yaml.safe_load((ROOT / "infra" / "otel" / "otel-collector.yml").read_text(encoding="utf-8"))
    headers = cfg["exporters"]["otlphttp/phoenix"]["headers"]
    assert headers["authorization"] == "Bearer ${env:PHOENIX_INGEST_KEY}"
