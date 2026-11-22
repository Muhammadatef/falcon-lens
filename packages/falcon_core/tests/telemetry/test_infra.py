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
    return {f"fl_{n}" for n in re.findall(r"`([a-z_]+)(?:\{[^}]*\})?`", block)}


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


def test_six_dashboards_provisioned_with_5s_refresh() -> None:
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
            assert base in documented or name in documented or name == "fl_http_requests_total", (
                f"{path.name}: {name}"
            )
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
