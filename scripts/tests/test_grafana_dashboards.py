"""The provisioned Grafana dashboards: valid JSON, stable UIDs, panel rules, and only metrics that exist."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "infra" / "grafana" / "dashboards"
UIDS = {
    "1-command-overview": "fl-command-overview",
    "2-detection-quality": "fl-detection-quality",
    "3-pipeline-performance": "fl-pipeline",
    "4-ai-operations": "fl-ai-ops",
    "5-security": "fl-security",
    "6-sentinel": "fl-sentinel",
    "7-model-quality": "fl-model-quality",
}
SUFFIXES = ("_bucket", "_count", "_sum", "_total", "_created")


def _source_metric_names() -> set[str]:
    """Every fl_ metric name declared in the code base (quoted literals and telemetry helper calls)."""
    names: set[str] = set()
    for base in ("packages/falcon_core/src", "services", "scripts"):
        for p in (ROOT / base).rglob("*.py"):
            if "tests" in p.parts:
                continue
            text = p.read_text(encoding="utf-8")
            names |= set(re.findall(r'"(fl_[a-z0-9_]+)"', text))
            if p.name == "metrics.py" and "telemetry" in p.parts:
                names |= {f"fl_{n}" for n in re.findall(r'_[cgh]\(\s*"([a-z0-9_]+)"', text)}
    return names


def _known(name: str, declared: set[str]) -> bool:
    cands = {name}
    for s in SUFFIXES:
        if name.endswith(s):
            cands.add(name[: -len(s)])
    # counters are declared without or with _total; histograms without suffix
    return any(c in declared or f"{c}_total" in declared for c in cands)


def _recorded_rules() -> set[str]:
    out: set[str] = set()
    for f in (ROOT / "infra" / "prometheus" / "rules").glob("*.yml"):
        for g in yaml.safe_load(f.read_text())["groups"]:
            out |= {r["record"] for r in g["rules"] if "record" in r}
    return out


def _exprs(panel: dict) -> list[str]:
    return [t["expr"] for t in panel.get("targets", []) if "expr" in t]


def _boards() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(DASH.glob("*.json"))}


def test_seven_dashboards_with_stable_uids() -> None:
    boards = _boards()
    assert set(boards) == set(UIDS)
    for stem, uid in UIDS.items():
        assert boards[stem]["uid"] == uid
    ids = [p["id"] for b in boards.values() for p in b["panels"]]
    assert all(isinstance(i, int) for i in ids)
    for b in boards.values():
        pids = [p["id"] for p in b["panels"]]
        assert len(pids) == len(set(pids))
        assert {link["url"] for link in b["links"]} == {f"/d/{u}" for u in UIDS.values()}


def test_every_panel_is_bilingual_and_explains_thresholds_and_no_data() -> None:
    for b in _boards().values():
        for p in b["panels"]:
            if p["type"] in ("row", "text"):
                continue
            assert " | " in p["title"], (b["uid"], p["title"])
            if p["type"] != "logs":
                assert "Thresholds:" in p["description"] and "No data:" in p["description"], (b["uid"], p["title"])


def test_queries_only_use_metrics_that_exist() -> None:
    declared = _source_metric_names() | {
        "fl_eval_metric", "fl_eval_ci_low", "fl_eval_ci_high", "fl_eval_n", "fl_eval_artifact_info",
        "fl_egress_connects_total",  # rendered by hand in services/egress (f-string, not a quoted literal)
        "fl_eval_artifact_latest", "fl_eval_artifact_timestamp",
    }  # fmt: skip
    rules = _recorded_rules()
    unknown: set[str] = set()
    for b in _boards().values():
        for p in b["panels"]:
            for e in _exprs(p):
                for rec in re.findall(r"\bfl:[a-z0-9_:]+", e):
                    assert rec in rules, (b["uid"], p["title"], rec)
                for m in re.findall(r"\bfl_[a-z0-9_]+", e):
                    if not _known(m, declared):
                        unknown.add(f"{b['uid']}: {m}")
    assert not unknown, sorted(unknown)


def test_runbook_links_point_to_existing_anchors() -> None:
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    anchors = set(re.findall(r"^## (\S+)", runbook, re.M))
    seen = 0
    for b in _boards().values():
        for p in b["panels"]:
            for link in p.get("links", []):
                seen += 1
                assert link["url"].split("#")[1] in anchors, (b["uid"], p["title"], link["url"])
    assert seen > 40


def test_every_alert_has_a_runbook_anchor() -> None:
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    anchors = set(re.findall(r"^## (\S+)", runbook, re.M))
    for f in (ROOT / "infra" / "prometheus" / "rules").glob("*.yml"):
        for g in yaml.safe_load(f.read_text())["groups"]:
            for r in g["rules"]:
                if "alert" in r:
                    assert r["annotations"]["runbook_url"].split("#")[1] in anchors, r["alert"]


def test_eval_panels_only_read_exporter_metrics_and_replay_series_are_labelled() -> None:
    mq = _boards()["7-model-quality"]
    for p in mq["panels"][1:]:  # the first panel is the shared REPLAY/LIVE banner
        for e in _exprs(p):
            assert "fl_eval_" in e, p["title"]
    for stem, b in _boards().items():
        if stem == "7-model-quality":
            continue
        for p in b["panels"]:
            if any("fl_checks_total" in e and "by (" in e and "source" in e for e in _exprs(p)):
                assert "REPLAY" in p["title"], (stem, p["title"])


def test_scrape_job_for_the_evals_exporter() -> None:
    cfg = yaml.safe_load((ROOT / "infra" / "prometheus" / "prometheus.yml").read_text())
    jobs = {j["job_name"]: j for j in cfg["scrape_configs"]}
    assert jobs["evals-exporter"]["static_configs"][0]["targets"] == ["evals-exporter:9109"]
