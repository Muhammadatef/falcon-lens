#!/usr/bin/env python3
"""Generates the seven Falcon Lens Grafana dashboards into infra/grafana/dashboards/*.json.

The JSON is committed (Grafana provisions it from disk); this script keeps the seven consistent: 5 s refresh,
a REPLAY banner, `source`-split series, EN | AR titles, a description on every panel that states the
thresholds' rationale and what "No data" means, and a runbook link where an alert exists.
Run: uv run python infra/grafana/gen_dashboards.py

When to use it:
    After you change a dashboard definition in this file. Grafana reads the generated JSON, not this script.

How to run:
    uv run python infra/grafana/gen_dashboards.py       (no make target; restart Grafana to reload)

Inputs:
    None (no env vars or arguments).

Outputs / side effects:
    Deletes every *.json in infra/grafana/dashboards/ and rewrites the seven dashboard files there, printing
    one line per file. No network calls. Commit the regenerated JSON together with this file. Exits non-zero
    if a panel lacks a bilingual title, a threshold rationale or a no-data explanation.

Truth rules: every number is a live `fl_` metric or comes from a published eval artifact through the
evals-exporter (`fl_eval_*`). Nothing is typed in; threshold lines are visual limits, stated in each description.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

OUT = Path(__file__).parent / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
RB = "https://github.com/Muhammadatef/falcon-lens/blob/main/docs/RUNBOOK.md#"

ORANGE = "#F5A623"  # replay
AMBER = "#E8B339"
GREEN = "#3FB68B"
RED = "#E5484D"
BLUE = "#5B9BF0"
GOLD = "#D4AF37"  # falcon accent
MUTED = "#8A94A6"

Panel = dict[str, Any]
Steps = list[tuple[float | None, str]]

GOOD_BAD: Steps = [(None, GREEN), (1, RED)]
OK_WARN: Steps = [(None, GREEN), (1, AMBER)]
INFO: Steps = [(None, BLUE)]

ND_TRAFFIC = "no checks ran in this time range; run make seed, make replay or make demo, or send a real check"
ND_LLM = "the AI tiers made no call in this range (T3/extractor/Sentinel idle, or the stack runs without AI)"
ND_NEW = "the service has not emitted this metric yet: it appears after the first event of its kind"
ND_EVAL = "the evals-exporter is not running (obs profile) or evals/results/published has no matching artifact"
ND_SENT = "the Sentinel has not processed events in this range (no incidents yet, or the service is down)"
ND_SEC = (
    "nothing of this kind happened in this range, which is the healthy state; the series appears at the first event"
)

REPLAY_NOTE = (
    "Counters without a source label (LLM, sandbox, security) include replayed traffic while the banner says REPLAY."
)


def src(expr: str) -> str:
    """Rename source=replay/live to REPLAY/LIVE so legends carry the badge."""
    return (
        f'label_replace(label_replace({expr}, "source", "REPLAY", "source", "replay"),'
        ' "source", "LIVE", "source", "live")'
    )


REPLAY_OVERRIDES: list[dict[str, Any]] = [
    {
        "matcher": {"id": "byRegexp", "options": ".*REPLAY.*"},
        "properties": [
            {"id": "color", "value": {"mode": "fixed", "fixedColor": ORANGE}},
            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}},
        ],
    },
    {
        "matcher": {"id": "byRegexp", "options": ".*LIVE.*"},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREEN}}],
    },
]

NAV = [
    ("fl-command-overview", "Command overview", "مركز القيادة"),
    ("fl-detection-quality", "Detection quality", "جودة الكشف"),
    ("fl-pipeline", "Pipeline performance", "أداء المسار"),
    ("fl-ai-ops", "AI operations", "عمليات الذكاء الاصطناعي"),
    ("fl-security", "Security", "الأمن"),
    ("fl-sentinel", "Sentinel", "الحارس"),
    ("fl-model-quality", "Model quality", "جودة النموذج"),
]


def desc(what: str, thr: str, nodata: str) -> str:
    """The description every panel carries: meaning, threshold rationale, and why it may show no data."""
    return f"{what} Thresholds: {thr}. No data: {nodata}."


def links(rb: str | None) -> list[dict[str, Any]]:
    return [{"title": f"Runbook: {rb}", "url": RB + rb, "targetBlank": True}] if rb else []


class Board:
    """A dashboard under construction: collects panels and renders Grafana JSON."""

    def __init__(self, uid: str, title: str, tags: list[str], refresh: str = "5s") -> None:
        self.uid, self.title, self.tags, self.refresh = uid, title, tags, refresh
        self.panels: list[Panel] = []
        self._id = 0
        self.row_y = 0
        self.col_x = 0
        self.row_h = 0

    def _place(self, w: int, h: int) -> dict[str, int]:
        if self.col_x + w > 24:
            self.row_y += self.row_h
            self.col_x, self.row_h = 0, 0
        pos = {"h": h, "w": w, "x": self.col_x, "y": self.row_y}
        self.col_x += w
        self.row_h = max(self.row_h, h)
        return pos

    def newline(self) -> None:
        self.row_y += self.row_h
        self.col_x, self.row_h = 0, 0

    def add(self, panel: Panel, w: int, h: int) -> Panel:
        if panel.get("type") == "stat" and w < 6:
            w = 6  # bilingual titles are cut off in narrower tiles
        self._id += 1
        panel["id"] = self._id
        panel["gridPos"] = self._place(w, h)
        self.panels.append(panel)
        return panel

    def row(self, title: str) -> None:
        self.newline()
        self._id += 1
        self.panels.append(
            {
                "id": self._id,
                "type": "row",
                "title": title,
                "collapsed": False,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.row_y},
                "panels": [],
            }
        )
        self.row_y += 1

    def json(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "tags": ["falcon-lens", *self.tags],
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 3,
            "editable": False,
            "graphTooltip": 1,
            "refresh": self.refresh,
            "time": {"from": "now-30m", "to": "now"},
            "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m"]},
            "style": "dark",
            "links": [
                {
                    "title": f"{t} | {a}",
                    "type": "link",
                    "url": f"/d/{u}",
                    "icon": "dashboard",
                    "targetBlank": False,
                }
                for u, t, a in NAV
            ],
            "annotations": {"list": []},
            "templating": {"list": []},
            "panels": self.panels,
        }


def target(expr: str, legend: str = "", ref: str = "A", instant: bool = False) -> dict[str, Any]:
    """A Prometheus query target for a panel."""
    t: dict[str, Any] = {"refId": ref, "expr": expr, "datasource": PROM, "legendFormat": legend}
    if instant:
        t["instant"] = True
    return t


def _thresholds(steps: Steps) -> dict[str, Any]:
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}


def ts(
    title: str,
    targets: list[dict[str, Any]],
    d: str,
    unit: str = "short",
    replay: bool = False,
    stack: bool = False,
    steps: Steps | None = None,
    rb: str | None = None,
    pmin: float | None = None,
    pmax: float | None = None,
) -> Panel:
    """A time-series panel; `steps` draws dashed threshold lines."""
    custom: dict[str, Any] = {
        "lineWidth": 2,
        "fillOpacity": 18,
        "showPoints": "never",
        "spanNulls": True,
        "stacking": {"mode": "normal" if stack else "none", "group": "A"},
    }
    defaults: dict[str, Any] = {"unit": unit, "custom": custom}
    if steps:
        defaults["thresholds"] = _thresholds(steps)
        custom["thresholdsStyle"] = {"mode": "dashed"}
    if pmin is not None:
        defaults["min"] = pmin
    if pmax is not None:
        defaults["max"] = pmax
    note = " Series with source=replay are drawn dashed orange and labelled REPLAY." if replay else ""
    return {
        "type": "timeseries",
        "title": title + (" | REPLAY-aware" if replay else ""),
        "description": d + note,
        "links": links(rb),
        "datasource": PROM,
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": REPLAY_OVERRIDES if replay else []},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def stat(
    title: str,
    expr: str,
    d: str,
    unit: str = "short",
    steps: Steps | None = None,
    decimals: int | None = None,
    graph: bool = False,
    rb: str | None = None,
    nodata: str = "No data",
) -> Panel:
    """A single-value (stat) panel. Sparklines are off unless `graph`."""
    dflt: dict[str, Any] = {
        "unit": unit,
        "color": {"mode": "thresholds"},
        "thresholds": _thresholds(steps or INFO),
        "noValue": nodata if len(nodata) <= 40 else "No data",  # the full reason is in the description
    }
    if decimals is not None:
        dflt["decimals"] = decimals
    return {
        "type": "stat",
        "title": title,
        "description": d,
        "links": links(rb),
        "datasource": PROM,
        "targets": [target(expr)],
        "fieldConfig": {"defaults": dflt, "overrides": []},
        "options": {
            "colorMode": "background",
            "graphMode": "area" if graph else "none",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    }


def banner(board: Board) -> None:
    """Top strip: REPLAY vs LIVE (fl_checks_total{source}) and the synthetic demo emitter, if running."""
    expr = 'clamp_max(sum(increase(fl_checks_total{source="replay"}[5m])), 1) or vector(0)'
    p = stat(
        "Data source | مصدر البيانات",
        expr,
        desc(
            'REPLAY when any fl_checks_total{source="replay"} was recorded in the last 5 minutes. Replayed or '
            "synthetic data is never presented as live. " + REPLAY_NOTE,
            "green = LIVE only, orange = replayed data present (a label, not a fault)",
            "no check was recorded at all; the panel then reads LIVE",
        ),
    )
    p["fieldConfig"]["defaults"]["mappings"] = [
        {
            "type": "value",
            "options": {
                "1": {"text": "REPLAY DATA ACTIVE | بيانات إعادة تشغيل", "color": ORANGE, "index": 0},
                "0": {"text": "LIVE | مباشر", "color": GREEN, "index": 1},
            },
        }
    ]
    p["fieldConfig"]["defaults"]["thresholds"]["steps"] = [
        {"color": GREEN, "value": None},
        {"color": ORANGE, "value": 1},
    ]
    p["options"]["textMode"] = "value"
    board.add(p, 8, 3)


def markdown(title: str, content: str) -> Panel:
    """A text (markdown) panel."""
    return {
        "type": "text",
        "title": title,
        "options": {"mode": "markdown", "content": content},
        "transparent": True,
    }


def table(
    title: str,
    targets: list[dict[str, Any]],
    d: str,
    transformations: list[dict[str, Any]] | None = None,
    overrides: list[dict[str, Any]] | None = None,
    rb: str | None = None,
    nodata: str = "No data",
) -> Panel:
    """A table panel over instant queries."""
    for t in targets:
        t["format"] = "table"
        t["instant"] = True
    return {
        "type": "table",
        "title": title,
        "description": d,
        "links": links(rb),
        "datasource": PROM,
        "targets": targets,
        "transformations": transformations or [{"id": "organize", "options": {"excludeByName": {"Time": True}}}],
        "options": {"showHeader": True},
        "fieldConfig": {"defaults": {}, "overrides": overrides or []},
    }


def bargauge(
    title: str,
    expr: str,
    legend: str,
    d: str,
    unit: str = "short",
    steps: Steps | None = None,
    rb: str | None = None,
    nodata: str = "No data",
    pmax: float | None = None,
) -> Panel:
    """A bar-gauge panel (instant)."""
    dflt: dict[str, Any] = {"unit": unit, "min": 0, "noValue": nodata}
    if steps:
        dflt.update({"color": {"mode": "thresholds"}, "thresholds": _thresholds(steps)})
    else:
        dflt["color"] = {"mode": "fixed", "fixedColor": GOLD}
    if pmax is not None:
        dflt["max"] = pmax
    return {
        "type": "bargauge",
        "title": title,
        "description": d,
        "links": links(rb),
        "datasource": PROM,
        "targets": [target(expr, legend, instant=True)],
        "fieldConfig": {"defaults": dflt, "overrides": []},
        "options": {
            "orientation": "horizontal",
            "displayMode": "gradient",
            "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
        },
    }


def donut(title: str, expr: str, legend: str, d: str, nodata: str = "No data") -> Panel:
    """A donut (pie) panel."""
    return {
        "type": "piechart",
        "title": title,
        "description": d,
        "datasource": PROM,
        "targets": [target(expr, legend, instant=True)],
        "options": {
            "pieType": "donut",
            "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]},
            "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
        },
        "fieldConfig": {"defaults": {"noValue": nodata}, "overrides": []},
    }


def logs(title: str, expr: str, d: str) -> Panel:
    """A logs panel."""
    return {
        "type": "logs",
        "title": title,
        "description": d,
        "datasource": LOKI,
        "targets": [{"refId": "A", "expr": expr, "datasource": LOKI}],
        "options": {
            "showTime": True,
            "wrapLogMessage": True,
            "enableLogDetails": True,
            "sortOrder": "Descending",
        },  # fmt: skip
    }


def heatmap(title: str, expr: str, d: str, rb: str | None = None) -> Panel:
    """A heatmap panel over histogram buckets."""
    return {
        "type": "heatmap",
        "title": title,
        "description": d,
        "links": links(rb),
        "datasource": PROM,
        "targets": [{**target(expr, "{{le}}"), "format": "heatmap"}],
        "options": {
            "calculate": False,
            "color": {"scheme": "Oranges", "mode": "scheme"},
            "yAxis": {"unit": "s"},
            "cellGap": 1,
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def q(metric_expr: str, quantile: float, by: str = "") -> str:
    """histogram_quantile over a bucket rate expression, optionally keeping label(s) in `by`."""
    return f"histogram_quantile({quantile}, sum by (le{by}) ({metric_expr}))"


def ratio(num: str, den: str) -> str:
    return f"sum({num}) / clamp_min(sum({den}), 1)"


RI = "$__rate_interval"
E2E = f'rate(fl_stage_latency_seconds_bucket{{stage="total"}}[{RI}])'
LATEST = " * on (source, artifact) group_left () fl_eval_artifact_latest"


# ------------------------------------------------------------------------------------------ eval tiles


def eval_sel(metric: str, split: str, source: str, fn: str = "fl_eval_metric") -> str:
    return f'{fn}{{source="{source}",split="{split}",metric="{metric}"}}'


def eval_tile(
    title: str,
    metric: str,
    split: str,
    what: str,
    thr_text: str,
    steps: Steps | None = None,
    source: str = "main",
    unit: str = "percentunit",
    rb: str | None = "eval-regression",
    nodata: str = ND_EVAL,
    decimals: int = 3,
    ci_note: str = "CI = bootstrap 95% interval stored in the artifact.",
) -> Panel:
    """Stat tile: current value (legend = provenance), 95% CI low/high and n, all from the latest artifact."""
    targets = [
        target(eval_sel(metric, split, source) + LATEST, "{{artifact}} · {{provenance}}", "A", True),
        target(eval_sel(metric, split, source, "fl_eval_ci_low") + LATEST, "95% CI low", "B", True),
        target(eval_sel(metric, split, source, "fl_eval_ci_high") + LATEST, "95% CI high", "C", True),
        target(eval_sel(metric, split, source, "fl_eval_n") + LATEST, "n", "D", True),
    ]
    muted = {"id": "color", "value": {"mode": "fixed", "fixedColor": MUTED}}
    overrides = [{"matcher": {"id": "byFrameRefID", "options": r}, "properties": [muted]} for r in ("B", "C", "D")]
    overrides.append(
        {
            "matcher": {"id": "byFrameRefID", "options": "D"},
            "properties": [{"id": "unit", "value": "short"}, {"id": "decimals", "value": 0}],
        }
    )
    return {
        "type": "stat",
        "title": title,
        "description": desc(
            what
            + " Legend under the value = source artifact name and provenance label; "
            + ci_note
            + " n = items evaluated.",
            thr_text,
            nodata,
        ),
        "links": links(rb),
        "datasource": PROM,
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": decimals,
                "color": {"mode": "thresholds"},
                "thresholds": _thresholds(steps or INFO),
                "noValue": "No data: " + nodata,
            },
            "overrides": overrides,
        },
        "options": {
            "colorMode": "value",
            "graphMode": "none",
            "textMode": "value_and_name",
            "orientation": "horizontal",
            "justifyMode": "center",
            "text": {"valueSize": 22, "titleSize": 12},
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
    }


# ------------------------------------------------------------------------------------------ 1 overview


def overview() -> Board:
    """Dashboard 1: command overview."""
    b = Board("fl-command-overview", "Command overview | مركز القيادة", ["overview"])
    banner(b)
    b.add(
        markdown(
            "How to read this board | كيف تقرأ اللوحة",
            "KPIs of the last 5 min to 1 h. **REPLAY** series are replayed or synthetic traffic and are drawn "
            "dashed orange. The model scores are on **Model quality**.",
        ),
        16,
        3,
    )
    b.row("KPIs | المؤشرات الرئيسية")
    b.add(
        stat(
            "Checks / min | فحوصات في الدقيقة",
            "sum(rate(fl_checks_total[5m])) * 60",
            desc(
                "Finished checks per minute (all inputs, live and replay).",
                "none: volume has no good or bad value",
                ND_TRAFFIC,
            ),
            decimals=1,
            nodata=ND_TRAFFIC,
        ),
        4,
        4,
    )
    b.add(
        stat(
            "p50 latency | زمن الاستجابة (p50)",
            "fl:check_latency_seconds:p50_5m",
            desc(
                "Median end-to-end time of a check (stage=total).",
                "none for the median; the objective is on p95",
                ND_TRAFFIC,
            ),
            unit="s",
            decimals=2,
            nodata=ND_TRAFFIC,
        ),
        4,
        4,
    )
    b.add(
        stat(
            "p95 latency | زمن الاستجابة (p95)",
            "fl:check_latency_seconds:p95_5m",
            desc(
                "95th percentile end-to-end time (stage=total).",
                "green < 6 s, amber 6-8 s, red >= 8 s: the objective is p95 < 8 s and amber warns before it breaks",
                ND_TRAFFIC,
            ),
            unit="s",
            steps=[(None, GREEN), (6, AMBER), (8, RED)],
            decimals=2,
            rb="latency-burn",
            nodata=ND_TRAFFIC,
        ),
        4,
        4,
    )
    b.add(
        stat(
            "Degraded results, 1 h | نتائج متدهورة",
            "fl:degraded_ratio:increase1h",
            desc(
                "Share of checks that ended degraded (a check could not finish a tier; never shown as no warning signs).",
                "green < 5%, amber 5-15%, red >= 15%: starting points from DECISIONS.md, to tune on live traffic",
                ND_TRAFFIC,
            ),
            unit="percentunit",
            steps=[(None, GREEN), (0.05, AMBER), (0.15, RED)],
            decimals=1,
            rb="error-rate",
            nodata=ND_TRAFFIC,
        ),
        4,
        4,
    )
    b.add(
        stat(
            "Error budget used, 6 h | استهلاك الميزانية",
            "fl:slo_burn:rate6h",
            desc(
                "Slow-check share over 6 h divided by the 5% budget of the p95 < 8 s objective (1 = 100% used).",
                "green < 50%, amber 50-100%, red >= 100% of the budget",
                ND_TRAFFIC,
            ),
            unit="percentunit",
            steps=[(None, GREEN), (0.5, AMBER), (1, RED)],
            decimals=0,
            rb="latency-burn",
            nodata=ND_TRAFFIC,
        ),
        4,
        4,
    )
    b.add(
        stat(
            "SLO burn rate, 1 h | معدل الاستهلاك",
            "fl:slo_burn:rate1h",
            desc(
                "How many times faster than allowed the error budget is burning (1 = exactly on budget).",
                "green < 1, amber 1-14.4, red >= 14.4: 14.4 is the fast-burn alert level (LatencyBurnFast)",
                ND_TRAFFIC,
            ),
            steps=[(None, GREEN), (1, AMBER), (14.4, RED)],
            decimals=1,
            rb="latency-burn",
            nodata=ND_TRAFFIC,
        ),
        4,
        4,
    )
    b.add(
        stat(
            "Open incidents | الحوادث المفتوحة",
            "sum(fl_incident_open)",
            desc(
                "Incidents the Sentinel holds open (open, triaging, awaiting approval).",
                "green 0, amber >= 1, red >= 5: a heuristic for a demo-sized queue",
                ND_SENT,
            ),
            steps=[(None, GREEN), (1, AMBER), (5, RED)],
            rb="campaign-surge",
            nodata=ND_SENT,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Approvals pending | بانتظار الموافقة",
            "max(fl_approvals_pending)",
            desc(
                "External drafts waiting for a human decision. Nothing is sent without it.",
                "green 0, amber >= 1 (alert after 30 min)",
                ND_SENT,
            ),
            steps=OK_WARN,
            rb="approvals-waiting",
            nodata=ND_SENT,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Firing alerts | تنبيهات نشطة",
            'count(ALERTS{alertstate="firing"}) or vector(0)',
            desc("Prometheus alerts firing now.", "green 0, red >= 1", "Prometheus has no alert state yet"),
            steps=GOOD_BAD,
            rb="service-down",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Scrape targets down | أهداف متوقفة",
            "count(up == 0) or vector(0)",
            desc(
                "Targets Prometheus cannot scrape.",
                "green 0, red >= 1: a down service exports nothing",
                "Prometheus has no targets yet",
            ),
            steps=GOOD_BAD,
            rb="service-down",
        ),
        4,
        3,
    )
    b.row("Verdicts | الأحكام")
    b.add(
        ts(
            "Checks by verdict | الفحوصات حسب الحكم",
            [target(src(f"sum by (verdict, source) (rate(fl_checks_total[{RI}])) * 60"), "{{verdict}} · {{source}}")],
            desc(
                "Checks per minute by verdict and source. The lowest verdict is no warning signs.",
                "none: composition view",
                ND_TRAFFIC,
            ),
            replay=True,
            stack=True,
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Verdict mix % | نسبة الأحكام",
            [
                target(
                    src(
                        f"sum by (verdict, source) (rate(fl_checks_total[{RI}])) / ignoring (verdict) group_left "
                        f"sum by (source) (rate(fl_checks_total[{RI}]))"
                    ),
                    "{{verdict}} · {{source}}",
                )
            ],
            desc(
                "Share of each verdict among finished checks.",
                "none: composition view; a sudden shift is the signal",
                ND_TRAFFIC,
            ),
            unit="percentunit",
            replay=True,
            stack=True,
            pmax=1,
        ),
        7,
        8,
    )
    b.add(
        donut(
            "Verdict mix, 1 h | توزيع الأحكام",
            "sum by (verdict) (increase(fl_checks_total[1h]))",
            "{{verdict}}",
            desc("Verdict counts over the last hour.", "none: composition view", ND_TRAFFIC),
        ),
        5,
        8,
    )
    b.row("Speed and depth | السرعة والعمق")
    b.add(
        ts(
            "End-to-end latency p50 / p95 / p99 | زمن الاستجابة",
            [
                target(q(E2E, 0.5), "p50"),
                target(q(E2E, 0.95), "p95", "B"),
                target(q(E2E, 0.99), "p99", "C"),
            ],
            desc(
                "Total time of a check. Dashed line: the 8 s objective.",
                "line at 6 s amber and 8 s red (the p95 < 8 s objective)",
                ND_TRAFFIC,
            ),
            unit="s",
            steps=[(None, GREEN), (6, AMBER), (8, RED)],
            rb="latency-burn",
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Tier reached, share | المستوى الذي وصل إليه الفحص",
            [
                target(
                    src(
                        f"sum by (tier, source) (rate(fl_checks_total[{RI}])) / ignoring (tier, source) group_left "
                        f"sum(rate(fl_checks_total[{RI}]))"
                    ),
                    "{{tier}} · {{source}}",
                )
            ],
            desc(
                "Where checks ended: T0 (feeds), T1 (URL model), T2 (sandbox page), T3 (investigator).",
                "none: composition view; T3 is capped at about 15% by design (docs/EVALS.md)",
                ND_TRAFFIC,
            ),
            unit="percentunit",
            replay=True,
            stack=True,
        ),
        12,
        8,
    )
    b.add(
        bargauge(
            "Top degraded reasons, 1 h | أسباب التدهور",
            "topk(8, sum by (reason) (increase(fl_degraded_reasons_total[1h])))",
            "{{reason}}",
            desc(
                "Why final verdicts were degraded (sandbox timeout, DNS failure, signal error).",
                "none: counts; every reason is one the cascade names",
                ND_NEW,
            ),
            rb="sandbox-failure",
            nodata=ND_NEW,
        ),
        12,
        7,
    )
    b.add(
        table(
            "Firing alerts | التنبيهات النشطة",
            [target('sum by (alertname, severity) (ALERTS{alertstate="firing"})')],
            desc(
                "Alert names and severities firing now.",
                "none: any row needs a look; see the alert's runbook entry",
                "no alert is firing, which is the healthy state",
            ),
            nodata="No alert is firing",
            rb="service-down",
        ),
        12,
        7,
    )
    b.add(
        logs(
            "Service logs | سجلات الخدمات",
            '{service=~".+"}',
            desc(
                "All service logs from Loki (JSON, each line carries verdict_id).",
                "none",
                "Loki or the log shipper (alloy) is down",
            ),
        ),
        24,
        9,
    )
    return b


# ------------------------------------------------------------------------------------------ 2 detection

HARD_RULES = (
    ("H1", "brand mismatch | انتحال علامة"),
    ("H2", "known-bad feed | قائمة سيئة معروفة"),
    ("H3", "verified official cap | سقف الرسمي"),
    ("H4", "exfil to bot | تسريب إلى بوت"),
    ("H5", "dangerous link in message | رابط خطر"),
    ("H6", "OTP / remote-access ask | طلب رمز"),
)


def detection() -> Board:
    """Dashboard 2: detection quality."""
    b = Board("fl-detection-quality", "Detection quality | جودة الكشف", ["quality"])
    banner(b)
    b.add(
        markdown(
            "Where these numbers come from | مصدر الأرقام",
            "Live panels count what the cascade did (hard rules, evidence, tiers). Offline model scores with "
            "confidence intervals are on **Model quality** and come from published eval artifacts only. "
            "Nothing is typed in by hand; REPLAY traffic is marked.",
        ),
        16,
        3,
    )
    b.row("Hard rules H1-H6 | القواعد الصارمة")
    for rid, name in HARD_RULES:
        b.add(
            stat(
                f"{rid} hit rate, 1 h | {name}",
                ratio(f'increase(fl_hard_rule_fired_total{{rule="{rid}"}}[1h])', "increase(fl_checks_total[1h])"),
                desc(
                    f"Share of final verdicts where hard rule {rid} fired (docs/SCORING.md section 3).",
                    "none: a hit is a detection, not a fault; watch for sudden changes",
                    ND_NEW,
                ),
                unit="percentunit",
                decimals=1,
                nodata=ND_NEW,
            ),
            4,
            3,
        )
    b.add(
        ts(
            "Hard-rule firings by rule | إطلاق القواعد",
            [target(f"sum by (rule) (rate(fl_hard_rule_fired_total[{RI}])) * 60", "{{rule}}")],
            desc("Firings per minute for each hard rule.", "none: composition view", ND_NEW),
            stack=True,
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Floor and cap firings | الرفع والسقف",
            [target(f"sum by (effect) (rate(fl_hard_rule_fired_total[{RI}])) * 60", "{{effect}}")],
            desc(
                "floor_dangerous / floor_suspicious raise a verdict; cap_no_warning_signs (H3) lowers one for verified official domains.",
                "none: composition view",
                ND_NEW,
            ),
            stack=True,
        ),
        12,
        7,
    )
    b.row("Evidence and tiers | الأدلة والمستويات")
    b.add(
        bargauge(
            "Evidence-type frequency, 1 h | تكرار أنواع الأدلة",
            "topk(15, sum by (signal) (increase(fl_evidence_total[1h])))",
            "{{signal}}",
            desc(
                "How many final verdicts carried each evidence signal (each counted once per verdict).",
                "none: counts",
                ND_NEW,
            ),
            nodata=ND_NEW,
        ),
        12,
        10,
    )
    b.add(
        stat(
            "T1 early-exit rate, 1 h | الخروج المبكر",
            "fl:t1_early_exit_ratio:increase1h",
            desc(
                "Share of checks that ended at T0 or T1 without opening a page. Higher is faster and cheaper.",
                "none: a design target, not a limit; a drop means more page renders",
                ND_TRAFFIC,
            ),
            unit="percentunit",
            decimals=1,
            nodata=ND_TRAFFIC,
        ),
        4,
        5,
    )
    b.add(
        stat(
            "Partial-render rate, 1 h | العرض الجزئي",
            ratio(
                'increase(fl_sandbox_renders_total{outcome="partial"}[1h])', "increase(fl_sandbox_renders_total[1h])"
            ),
            desc(
                "Share of sandbox visits that returned a page with an error note (partial evidence).",
                "green < 10%, amber 10-25%, red >= 25%: heuristic; many partial pages weaken T2",
                ND_NEW,
            ),
            unit="percentunit",
            steps=[(None, GREEN), (0.1, AMBER), (0.25, RED)],
            decimals=1,
            rb="sandbox-failure",
            nodata=ND_NEW,
        ),
        4,
        5,
    )
    b.add(
        stat(
            "Escalated to T3, 1 h | تصعيد إلى T3",
            ratio('increase(fl_escalations_total{to="T3"}[1h])', "increase(fl_checks_total[1h])"),
            desc(
                "Share of checks escalated to the investigator (budget 15% in docs/EVALS.md).",
                "green <= 15%, red above: the T3 budget",
                ND_TRAFFIC,
            ),
            unit="percentunit",
            steps=[(None, GREEN), (0.15, RED)],
            decimals=1,
            nodata=ND_TRAFFIC,
        ),
        4,
        5,
    )
    b.row("Live signals | مؤشرات التشغيل")
    b.add(
        ts(
            "Verdicts by tier | الأحكام حسب المستوى",
            [target(src(f"sum by (tier, source) (rate(fl_checks_total[{RI}])) * 60"), "{{tier}} · {{source}}")],
            desc("Checks per minute by tier reached.", "none: composition view", ND_TRAFFIC),
            replay=True,
            stack=True,
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Escalations | التصعيدات",
            [target(f"sum by (from, to) (rate(fl_escalations_total[{RI}])) * 60", "{{from}} -> {{to}}")],
            desc("Tier escalations per minute.", "none: composition view", ND_TRAFFIC),
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Route agreement | اتفاق المسارات",
            [target("fl_route_agreement_ratio", "agreement")],
            desc(
                "Share of shadow-sampled checks where cloud and local routes agree.",
                "dashed line at 80%: below it RouteAgreementDrop fires",
                "shadow sampling is off (FL_SHADOW_RATE=0) so there is no measurement",
            ),
            unit="percentunit",
            steps=[(None, RED), (0.8, GREEN)],
            rb="route-agreement-drop",
            pmin=0,
            pmax=1,
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Score drift index | انحراف الدرجات",
            [target("fl_score_drift_index", "drift")],
            desc(
                "Score distribution drift against the baseline.",
                "dashed line at 0.2: above it ScoreDrift fires",
                "the drift job has not reported yet",
            ),
            steps=[(None, GREEN), (0.2, RED)],
            rb="score-drift",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "User feedback | ملاحظات المستخدمين",
            [target("sum by (type) (increase(fl_user_feedback_total[15m]))", "{{type}}")],
            desc(
                "Feedback submitted by users in 15 min windows.",
                "none: counts; false_positive above 5 in 15 min fires FalsePositiveSpike",
                "no feedback was submitted",
            ),
            rb="fp-spike",
        ),
        8,
        7,
    )
    b.add(
        bargauge(
            "Top impersonated brands, 1 h | أكثر العلامات انتحالاً",
            "topk(10, sum by (brand) (increase(fl_brand_impersonation_total[1h])))",
            "{{brand}}",
            desc(
                "Brands named most often in detections (only the registered brands; fixtures use Falcon Demo Bank).",
                "none: counts",
                "no brand impersonation was detected",
            ),
            nodata="No brand impersonation detected",
        ),
        12,
        7,
    )
    b.add(
        bargauge(
            "New campaign domains by brand | نطاقات جديدة",
            src("topk(10, sum by (brand, source) (increase(fl_campaign_new_domains_total[1h])))"),
            "{{brand}} · {{source}}",
            desc(
                "New domains the Sentinel attributed to a brand campaign. REPLAY rows are replayed events.",
                "none: counts",
                ND_SENT,
            ),
            nodata=ND_SENT,
        ),
        12,
        7,
    )
    return b


# ------------------------------------------------------------------------------------------ 3 pipeline


def pipeline() -> Board:
    """Dashboard 3: pipeline performance."""
    b = Board("fl-pipeline", "Pipeline performance | أداء المسار", ["pipeline"])
    banner(b)
    b.add(
        stat(
            "p95 end-to-end | زمن p95",
            "fl:check_latency_seconds:p95_5m",
            desc(
                "95th percentile of a whole check.",
                "green < 6 s, amber 6-8 s, red >= 8 s (objective p95 < 8 s)",
                ND_TRAFFIC,
            ),
            unit="s",
            steps=[(None, GREEN), (6, AMBER), (8, RED)],
            decimals=2,
            rb="latency-burn",
            nodata=ND_TRAFFIC,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Slow ratio (>8 s), 1 h | نسبة البطء",
            "fl:check_slow_ratio:rate1h",
            desc(
                "Share of checks slower than 8 s. Recording rule in falcon-alerts.yml.",
                "green < 5% (the budget), amber 5-72%, red >= 72% (14.4 x budget, fast burn)",
                ND_TRAFFIC,
            ),
            unit="percentunit",
            steps=[(None, GREEN), (0.05, AMBER), (0.72, RED)],
            rb="latency-burn",
            nodata=ND_TRAFFIC,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Burn rate, 1 h | معدل الاستهلاك",
            "fl:slo_burn:rate1h",
            desc("Slow ratio divided by the 5% budget.", "green < 1, amber 1-14.4, red >= 14.4", ND_TRAFFIC),
            steps=[(None, GREEN), (1, AMBER), (14.4, RED)],
            decimals=1,
            rb="latency-burn",
            nodata=ND_TRAFFIC,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Render success, 1 h | نجاح العرض",
            ratio('increase(fl_sandbox_renders_total{outcome="ok"}[1h])', "increase(fl_sandbox_renders_total[1h])"),
            desc(
                "Share of sandbox visits that rendered a full page.",
                "green >= 80%, amber 50-80%, red < 50%: heuristic; the rest are partial, timeouts or failures",
                ND_NEW,
            ),
            unit="percentunit",
            steps=[(None, RED), (0.5, AMBER), (0.8, GREEN)],
            decimals=0,
            rb="sandbox-failure",
            nodata=ND_NEW,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Job backlog | تراكم المهام",
            'sum(fl_queue_depth{state="lag"}) + sum(fl_queue_depth{state="pending"})',
            desc(
                "Jobs queued or in flight in the check queue (lag + pending).",
                "green < 10, amber 10-50, red >= 50: heuristic for a single worker",
                ND_NEW,
            ),
            steps=[(None, GREEN), (10, AMBER), (50, RED)],
            rb="latency-burn",
            nodata=ND_NEW,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Egress denied, 1 h | حظر الخروج",
            'sum(increase(fl_egress_connects_total{result="denied"}[1h]))',
            desc(
                "Connections the filtering egress proxy refused.",
                "none: expected under SSRF red-team replay; investigate on live traffic",
                "the egress proxy has served no request",
            ),
            rb="ssrf-spike",
            nodata="No egress traffic yet",
        ),
        4,
        3,
    )
    b.row("Latency per tier | الزمن لكل مستوى")
    b.add(
        heatmap(
            "End-to-end latency heatmap | خريطة الزمن",
            'sum by (le) (increase(fl_stage_latency_seconds_bucket{stage="total"}[$__rate_interval]))',
            desc(
                "Distribution of whole-check time; darker = more checks.",
                "none: read the shape; mass right of 8 s breaks the objective",
                ND_TRAFFIC,
            ),
            rb="latency-burn",
        ),
        12,
        8,
    )
    b.add(
        heatmap(
            "T1 latency heatmap | خريطة زمن T1",
            'sum by (le) (increase(fl_stage_latency_seconds_bucket{stage="T1"}[$__rate_interval]))',
            desc("T1 (URL model and signals) stage time.", "none: read the shape", ND_TRAFFIC),
        ),
        6,
        8,
    )
    b.add(
        heatmap(
            "T2 latency heatmap | خريطة زمن T2",
            'sum by (le) (increase(fl_stage_latency_seconds_bucket{stage="T2"}[$__rate_interval]))',
            desc(
                "T2 (sandbox page visit) stage time.",
                "none: read the shape; the sandbox budget is about 6 s",
                "no check reached T2",
            ),
            rb="sandbox-failure",
        ),
        6,
        8,
    )
    b.add(
        heatmap(
            "T0 latency heatmap | خريطة زمن T0",
            'sum by (le) (increase(fl_stage_latency_seconds_bucket{stage="T0"}[$__rate_interval]))',
            desc("T0 (cache and feed lookups) stage time.", "none: read the shape", ND_TRAFFIC),
        ),
        12,
        7,
    )
    b.add(
        heatmap(
            "T3 latency heatmap | خريطة زمن T3",
            'sum by (le) (increase(fl_stage_latency_seconds_bucket{stage="T3"}[$__rate_interval]))',
            desc("T3 (investigator) stage time.", "none: read the shape; LLM latency dominates", "no check reached T3"),
        ),
        12,
        7,
    )
    for qt, label in ((0.5, "p50"), (0.95, "p95"), (0.99, "p99")):
        b.add(
            ts(
                f"Stage latency {label} | زمن المرحلة",
                [target(q(f"rate(fl_stage_latency_seconds_bucket[{RI}])", qt, ", stage"), "{{stage}}")],
                desc(f"{label} per stage (T0-T3 and total).", "dashed line at 8 s (end-to-end objective)", ND_TRAFFIC),
                unit="s",
                steps=[(None, GREEN), (8, RED)],
                rb="latency-burn",
            ),
            8,
            7,
        )
    b.row("Queue, sandbox, egress | الطابور والصندوق والخروج")
    b.add(
        ts(
            "Queue depth and lag | عمق الطابور",
            [target("sum by (state) (fl_queue_depth)", "{{state}}")],
            desc(
                "Jobs waiting (lag) and delivered but unacked (pending) in the check stream.",
                "dashed line at 50 jobs (red)",
                ND_NEW,
            ),
            steps=[(None, GREEN), (10, AMBER), (50, RED)],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Enqueued vs completed / min | الوارد مقابل المنجز",
            [
                target(f"sum(rate(fl_api_jobs_enqueued_total[{RI}])) * 60", "enqueued"),
                target(src(f"sum by (source) (rate(fl_checks_total[{RI}])) * 60"), "completed · {{source}}", "B"),
            ],
            desc(
                "Jobs accepted by the API against checks finished. A widening gap is a backlog.",
                "none: compare the two lines",
                ND_TRAFFIC,
            ),
            replay=True,
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Sandbox renders by outcome | نتائج العرض",
            [target(f"sum by (outcome) (rate(fl_sandbox_renders_total[{RI}])) * 60", "{{outcome}}")],
            desc(
                "ok = full page, partial = page with an error note, timeout, failed.",
                "none: composition; timeouts above 3 in 10 min fire SandboxFailure",
                ND_NEW,
            ),
            stack=True,
            rb="sandbox-failure",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Egress allowed vs denied | الخروج المسموح والمحظور",
            [target(f"sum by (result) (rate(fl_egress_connects_total[{RI}])) * 60", "{{result}}")],
            desc(
                "Connections per minute through the egress proxy (the only way out of the sandbox).",
                "none: denied is the proxy doing its job",
                "the egress proxy has served no request",
            ),
            rb="ssrf-spike",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Tool errors | أخطاء الأدوات",
            [target("sum by (tool, reason) (increase(fl_tool_errors_total[5m]))", "{{tool}} · {{reason}}")],
            desc(
                "Signal, sandbox and investigator-tool failures by reason.",
                "none: counts; steady errors from one tool mean its feed or key is down",
                "no tool failed, which is the healthy state",
            ),
            rb="error-rate",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Cache hits by layer | إصابات الذاكرة",
            [target(f"sum by (layer) (rate(fl_cache_hits_total[{RI}])) * 60", "{{layer}}")],
            desc("Cache hits per minute (verdict cache, single-flight).", "none: composition", "no cache was hit"),
        ),
        8,
        7,
    )
    b.add(
        ts(
            "HTTP requests by status | طلبات HTTP",
            [target(f"sum by (service, status) (rate(fl_http_requests_total[{RI}]))", "{{service}} {{status}}")],
            desc(
                "Requests per second by service and status class.",
                "none: composition; 5xx above 5% for 5 min fires ErrorRateHigh",
                "no HTTP request was served",
            ),
            rb="error-rate",
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Feed age | عمر المصادر",
            [target("fl_feed_age_seconds", "{{feed}}")],
            desc(
                "Age of the last successful feed refresh.",
                "dashed line at 6 h (21600 s): past it hard rule H2 is off",
                "no feed has been polled yet",
            ),
            unit="s",
            steps=[(None, GREEN), (21600, RED)],
            rb="feed-stale",
        ),
        12,
        7,
    )
    return b


# ------------------------------------------------------------------------------------------ 4 AI ops

ROLE_COLUMNS = [
    ("A", "calls/min", "sum by (role) (rate(fl_llm_calls_total[5m])) * 60"),
    ("B", "p50 s", q("rate(fl_llm_call_seconds_bucket[5m])", 0.5, ", role")),
    ("C", "p95 s", q("rate(fl_llm_call_seconds_bucket[5m])", 0.95, ", role")),
    (
        "D",
        "failure %",
        'sum by (role) (increase(fl_llm_calls_total{outcome!="ok"}[1h])) / clamp_min(sum by (role) (increase(fl_llm_calls_total[1h])), 1)',
    ),
    ("E", "template %", "fl:llm_template_ratio:increase1h"),
]


def ai_ops() -> Board:
    """Dashboard 4: AI operations."""
    b = Board("fl-ai-ops", "AI operations | عمليات الذكاء الاصطناعي", ["ai"])
    banner(b)
    b.add(
        markdown(
            "Traces | التتبع",
            "LLM spans (OpenInference) go collector -> **Phoenix**. Filter by `verdict_id` to join a trace "
            "with its logs (Loki) and these metrics. The LLM never sets a score: the arbiter does.",
        ),
        8,
        3,
    )
    b.add(
        stat(
            "Canary leaks, 1 h | تسرب الكناري",
            "sum(increase(fl_canary_leak_total[1h]))",
            desc(
                "A canary token seen in model output means prompt exfiltration. Must stay 0.",
                "green 0, red >= 1: any leak is an incident",
                ND_SEC,
            ),
            steps=GOOD_BAD,
            rb="canary-leak",
            nodata="0 (series appears at the first leak)",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Forbidden-tool attempts, 1 h | محاولات أدوات ممنوعة",
            'sum(increase(fl_tool_errors_total{reason=~"provenance|unknown_tool"}[1h]))',
            desc(
                "Investigator tool calls the registry blocked: an unlisted tool or a URL/domain not from the evidence chain. Blocked, but must stay 0 on live traffic.",
                "green 0, red >= 1 (expected under red-team replay: check the banner)",
                ND_SEC,
            ),
            steps=GOOD_BAD,
            rb="injection-spike",
            nodata="0 (series appears at the first attempt)",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "LLM spend, 1 h | تكلفة النماذج",
            "sum(increase(fl_llm_cost_usd_total[1h])) or vector(0)",
            desc(
                "Estimated cloud spend from token counts and the price table (local route costs 0).",
                "none: no budget is set in the repo",
                ND_LLM,
            ),
            unit="currencyUSD",
            decimals=4,
            nodata=ND_LLM,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Cost / 1k checks | تكلفة لكل ألف فحص",
            "1000 * (sum(increase(fl_llm_cost_usd_total[1h])) or vector(0)) / clamp_min(sum(increase(fl_checks_total[1h])), 1)",
            desc(
                "Estimated LLM spend divided by checks, per 1000 checks.", "none: no budget is set in the repo", ND_LLM
            ),
            unit="currencyUSD",
            decimals=4,
            nodata=ND_LLM,
        ),
        4,
        3,
    )
    b.row("Per role | لكل دور")
    b.add(
        table(
            "Role scorecard, last hour | بطاقة الأدوار",
            [target(expr, "", ref) for ref, _, expr in ROLE_COLUMNS],
            desc(
                "One row per LLM role (extractor, investigator, responder...): call rate, latency, share of provider calls that "
                "failed or timed out, and share of requests that ended on the caller's template.",
                "failure and template above 10% are worth a look (heuristic); LLMFallbackActive fires on cloud->local fallback",
                ND_LLM,
            ),
            transformations=[
                {"id": "joinByField", "options": {"byField": "role", "mode": "outer"}},
                {"id": "filterFieldsByName", "options": {"include": {"pattern": "^(role|Value.*)$"}}},
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "Time 1": True,
                            "Time 2": True,
                            "Time 3": True,
                            "Time 4": True,
                            "Time 5": True,
                        },
                        "renameByName": {f"Value #{r}": n for r, n, _ in ROLE_COLUMNS},
                    },
                },
            ],
            overrides=[
                {
                    "matcher": {"id": "byName", "options": n},
                    "properties": [{"id": "unit", "value": u}, {"id": "decimals", "value": 2}],
                }
                for n, u in (
                    ("p50 s", "s"),
                    ("p95 s", "s"),
                    ("failure %", "percentunit"),
                    ("template %", "percentunit"),
                )
            ],
            rb="llm-fallback",
            nodata=ND_LLM,
        ),
        14,
        8,
    )
    b.add(
        ts(
            "LLM calls / min by role | نداءات الدور",
            [target(f"sum by (role) (rate(fl_llm_calls_total[{RI}])) * 60", "{{role}}")],
            desc("Provider calls per minute by role.", "none: volume", ND_LLM),
            stack=True,
        ),
        10,
        8,
    )
    b.add(
        ts(
            "Call latency p50 / p95 by role | زمن النداء",
            [
                target(q(f"rate(fl_llm_call_seconds_bucket[{RI}])", 0.5, ", role"), "p50 {{role}}"),
                target(q(f"rate(fl_llm_call_seconds_bucket[{RI}])", 0.95, ", role"), "p95 {{role}}", "B"),
            ],
            desc(
                "Provider call time by role.",
                "dashed line at 12 s: the default FL_LLM_TIMEOUT_S, calls beyond it time out",
                ND_LLM,
            ),
            unit="s",
            steps=[(None, GREEN), (12, RED)],
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Error / timeout rate by role | الأخطاء والمهلات",
            [
                target(
                    f'sum by (role, outcome) (rate(fl_llm_calls_total{{outcome!="ok"}}[{RI}])) * 60',
                    "{{role}} · {{outcome}}",
                )
            ],
            desc(
                "Failed provider calls per minute (timeout, error, budget).",
                "none: counts; a steady non-zero line means a provider problem",
                "every provider call succeeded",
            ),
            rb="llm-fallback",
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Template fallback % by role | الرجوع للقالب",
            [target("fl:llm_template_ratio:increase1h", "{{role}}")],
            desc(
                "Share of finished requests that ended on the caller's deterministic template or failed (the verdict stays valid).",
                "dashed lines at 10% amber and 25% red: heuristics",
                ND_LLM,
            ),
            unit="percentunit",
            steps=[(None, GREEN), (0.1, AMBER), (0.25, RED)],
            pmin=0,
            pmax=1,
            rb="llm-fallback",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Cloud to local fallbacks | الرجوع للنموذج المحلي",
            [target("sum by (role) (increase(fl_llm_fallback_total[5m]))", "{{role}}")],
            desc(
                "Times the cloud route failed and the local model answered.",
                "none: counts; any value fires LLMFallbackActive",
                "no fallback happened",
            ),
            rb="llm-fallback",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Route agreement | اتفاق المسارات",
            [target("fl_route_agreement_ratio", "agreement")],
            desc(
                "Cloud and local agreement on shadow samples.",
                "dashed line at 80%: below it RouteAgreementDrop fires",
                "shadow sampling is off",
            ),
            unit="percentunit",
            steps=[(None, RED), (0.8, GREEN)],
            rb="route-agreement-drop",
            pmin=0,
            pmax=1,
        ),
        8,
        7,
    )
    b.row("Tokens and cost by route | الرموز والتكلفة")
    b.add(
        ts(
            "Tokens / min by model and role | الرموز",
            [target(f"sum by (model, role) (rate(fl_llm_tokens_total[{RI}])) * 60", "{{model}} · {{role}}")],
            desc("Input plus output tokens per minute.", "none: volume", ND_LLM),
            stack=True,
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Tokens / min by route | الرموز حسب المسار",
            [
                target(f'sum(rate(fl_llm_tokens_total{{model=~"claude.*"}}[{RI}])) * 60', "cloud (Claude)"),
                target(f'sum(rate(fl_llm_tokens_total{{model!~"claude.*"}}[{RI}])) * 60', "local", "B"),
            ],
            desc("Tokens by route, read from the model name (claude-* is cloud).", "none: composition", ND_LLM),
            stack=True,
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Estimated cost USD / h by route | التكلفة",
            [
                target(f'sum(rate(fl_llm_cost_usd_total{{model=~"claude.*"}}[{RI}])) * 3600', "cloud (Claude)"),
                target(f'sum(rate(fl_llm_cost_usd_total{{model!~"claude.*"}}[{RI}])) * 3600', "local", "B"),
            ],
            desc(
                "Estimated spend rate from the price table; the local route is free by construction.",
                "none: no budget is set in the repo",
                ND_LLM,
            ),
            unit="currencyUSD",
        ),
        8,
        7,
    )
    b.row("Investigator (T3) | المحقق")
    b.add(
        ts(
            "Steps per run p50 / p95 | خطوات الوكيل",
            [
                target(q(f"rate(fl_agent_steps_bucket[{RI}])", 0.5), "p50"),
                target(q(f"rate(fl_agent_steps_bucket[{RI}])", 0.95), "p95", "B"),
            ],
            desc(
                "Tool calls per investigator run.",
                "dashed line at 6 calls: the usual cap, runs stopping at it ran out of budget",
                "the investigator has not run",
            ),
            steps=[(None, GREEN), (6, AMBER)],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Tool-call mix | مزيج الأدوات",
            [target("sum by (tool) (increase(fl_agent_tool_calls_total[5m]))", "{{tool}}")],
            desc(
                "Which tools the investigator called. 'unknown' = a name outside the registry (never forwarded).",
                "none: composition",
                "the investigator has called no tool",
            ),
            stack=True,
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Tool call status | حالة الأدوات",
            [target("sum by (status) (increase(fl_agent_tool_calls_total[5m]))", "{{status}}")],
            desc(
                "ok, rejected (blocked by the registry), timeout, error.",
                "none: composition; rejected is the guard working, see forbidden-tool attempts",
                "the investigator has called no tool",
            ),
            stack=True,
        ),
        8,
        7,
    )
    b.row("Sentinel LLM | نموذج الحارس")
    b.add(
        ts(
            "Sentinel asks by task and outcome | طلبات الحارس",
            [target("sum by (task, outcome) (increase(fl_sentinel_llm_calls_total[5m]))", "{{task}} · {{outcome}}")],
            desc(
                "assess, summarise and propose asks to the model: ok, timeout, budget (skipped by the per-incident budget), invalid.",
                "none: counts",
                ND_SENT,
            ),
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Sentinel ask latency p50 / p95 | زمن طلبات الحارس",
            [
                target(q(f"rate(fl_sentinel_llm_seconds_bucket[{RI}])", 0.5, ", task"), "p50 {{task}}"),
                target(q(f"rate(fl_sentinel_llm_seconds_bucket[{RI}])", 0.95, ", task"), "p95 {{task}}", "B"),
            ],
            desc(
                "Wall time of Sentinel model asks (the local model takes 15-25 s).",
                "dashed line at 120 s: the per-incident time budget",
                ND_SENT,
            ),
            unit="s",
            steps=[(None, GREEN), (120, RED)],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "LLM text accepted by verifier % | قبول المدقق",
            [target("fl:sentinel_llm_text_share:increase1h", "{{task}}")],
            desc(
                "Share of Sentinel texts that passed the verifier (cites real evidence ids, no foreign URL) and were kept; the rest fell to the template.",
                "none: a falling line means the model drifts from the evidence",
                ND_SENT,
            ),
            unit="percentunit",
            pmin=0,
            pmax=1,
        ),
        8,
        7,
    )
    return b


# ------------------------------------------------------------------------------------------ 5 security


def security() -> Board:
    """Dashboard 5: security."""
    b = Board("fl-security", "Security | الأمن", ["security"])
    banner(b)
    stats = (
        (
            "SSRF blocked, 1 h | حظر SSRF",
            "sum(increase(fl_ssrf_blocked_total[1h]))",
            "Requests the SSRF guard refused (internal names, metadata addresses, bad DNS).",
            "green 0, amber >= 1: expected under red-team replay; review the reasons on live traffic",
            OK_WARN,
            "ssrf-spike",
        ),
        (
            "Injection detected, 1 h | حقن التعليمات",
            "sum(increase(fl_injection_detected_total[1h]))",
            "Prompt-injection attempts the detector caught in untrusted text or tool arguments.",
            "green 0, amber >= 1 (attempts are blocked; the alert fires above 10 in 5 min)",
            OK_WARN,
            "injection-spike",
        ),
        (
            "Auth failures, 1 h | فشل المصادقة",
            "sum(increase(fl_auth_failures_total[1h]))",
            "Rejected credentials (API key, operator key, bearer token).",
            "green < 5, amber 5-20, red >= 20: heuristic for brute-force noise",
            [(None, GREEN), (5, AMBER), (20, RED)],
            "error-rate",
        ),
        (
            "Rate-limited (429), 1 h | تحديد المعدل",
            "sum(increase(fl_rate_limited_total[1h]))",
            "Requests refused by the per-IP and per-key limits.",
            "green 0, amber >= 1: a few are normal under load tests",
            OK_WARN,
            "error-rate",
        ),
        (
            "Canary leaks, 1 h | تسرب الكناري",
            "sum(increase(fl_canary_leak_total[1h]))",
            "Canary token seen in model output. Must stay 0.",
            "green 0, red >= 1",
            GOOD_BAD,
            "canary-leak",
        ),
        (
            "Forbidden-tool attempts, 1 h | أدوات ممنوعة",
            'sum(increase(fl_tool_errors_total{reason=~"provenance|unknown_tool"}[1h]))',
            "Blocked investigator tool calls outside the evidence chain or the registry.",
            "green 0, red >= 1",
            GOOD_BAD,
            "injection-spike",
        ),
    )
    for title, expr, what, thr, steps, rb in stats:
        b.add(
            stat(
                title, expr, desc(what, thr, ND_SEC), steps=steps, rb=rb, nodata="0 (series appears at the first event)"
            ),
            4,
            3,
        )
    b.row("Blocked and detected | المحظور والمكتشف")
    b.add(
        ts(
            "SSRF blocked by reason | حظر SSRF حسب السبب",
            [target("sum by (reason) (increase(fl_ssrf_blocked_total[5m]))", "{{reason}}")],
            desc(
                "Guard refusals in 5 min windows by reason.",
                "none: composition; above 10 in 5 min fires SSRFSpike",
                ND_SEC,
            ),
            stack=True,
            rb="ssrf-spike",
        ),
        12,
        8,
    )
    b.add(
        bargauge(
            "SSRF reasons, 1 h | أسباب الحظر",
            "sum by (reason) (increase(fl_ssrf_blocked_total[1h]))",
            "{{reason}}",
            desc("Why the guard refused, last hour.", "none: counts", ND_SEC),
            rb="ssrf-spike",
            nodata="No SSRF blocks, the healthy state",
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Injection and canary | الحقن والكناري",
            [
                target("sum(increase(fl_injection_detected_total[5m]))", "injection detected"),
                target("sum(increase(fl_canary_leak_total[5m]))", "canary leak", "B"),
            ],
            desc("Injection detections and canary leaks per 5 min.", "none: counts; canary must be 0", ND_SEC),
            rb="injection-spike",
        ),
        12,
        7,
    )
    b.add(
        bargauge(
            "Injection evidence by type, 1 h | أنواع الحقن",
            'topk(10, sum by (signal) (increase(fl_evidence_total{signal=~".*inject.*"}[1h])))',
            "{{signal}}",
            desc("Injection-family evidence on final verdicts, by signal.", "none: counts", ND_SEC),
            rb="injection-spike",
            nodata="No injection evidence, the healthy state",
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Rate limited by scope | تحديد المعدل",
            [target("sum by (scope) (increase(fl_rate_limited_total[5m]))", "{{scope}}")],
            desc("429 responses from the rate limiters by scope.", "none: counts", ND_SEC),
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Auth failures and 401/403 | فشل المصادقة",
            [
                target("sum(increase(fl_auth_failures_total[5m]))", "auth failures"),
                target('sum(increase(fl_http_requests_total{status=~"401|403"}[5m]))', "HTTP 401/403", "B"),
            ],
            desc(
                "Failed authentications and unauthorised responses per 5 min.",
                "dashed line at 20 (red): see the stat above",
                ND_SEC,
            ),
            steps=[(None, GREEN), (20, RED)],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Egress denied | الخروج المحظور",
            [target(f'sum(rate(fl_egress_connects_total{{result="denied"}}[{RI}])) * 60', "denied / min")],
            desc(
                "Connections the egress proxy refused (sandbox traffic to blocked destinations).",
                "none: counts",
                "the egress proxy has served no request",
            ),
            rb="ssrf-spike",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Replay vs live checks | إعادة التشغيل مقابل المباشر",
            [target(src(f"sum by (source) (rate(fl_checks_total[{RI}])) * 60"), "{{source}}")],
            desc("Red-team replay spikes the panels on this board; compare with live volume.", "none", ND_TRAFFIC),
            replay=True,
        ),
        24,
        6,
    )
    b.add(
        logs(
            "Security log lines | سجلات أمنية",
            '{service=~".+"} |~ "(?i)ssrf|injection|canary|blocked|auth"',
            desc("Security-relevant log lines from Loki.", "none", "Loki or the log shipper is down"),
        ),
        24,
        10,
    )
    return b


# ------------------------------------------------------------------------------------------ 6 sentinel


def sentinel() -> Board:
    """Dashboard 6: Sentinel incidents and approvals."""
    b = Board("fl-sentinel", "Sentinel | الحارس", ["sentinel"])
    banner(b)
    b.add(
        stat(
            "Event lag | تأخر الأحداث",
            "max(fl_event_lag_seconds)",
            desc(
                "Age of the oldest unprocessed bus event.",
                "green < 30 s, amber 30-60 s, red >= 60 s (SentinelLag fires above 60 s)",
                ND_SENT,
            ),
            unit="s",
            steps=[(None, GREEN), (30, AMBER), (60, RED)],
            rb="sentinel-lag",
            nodata=ND_SENT,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Dead letters, 1 h | رسائل ميتة",
            "sum(increase(fl_sentinel_dead_letter_total[1h]))",
            desc("Events moved to the dead-letter stream.", "green 0, red >= 1", ND_SEC),
            steps=GOOD_BAD,
            rb="sentinel-dlq",
            nodata="0 (series appears at the first dead letter)",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Approvals pending | بانتظار الموافقة",
            "max(fl_approvals_pending)",
            desc("External drafts awaiting a human.", "green 0, amber >= 1 (ApprovalsWaiting after 30 min)", ND_SENT),
            steps=OK_WARN,
            rb="approvals-waiting",
            nodata=ND_SENT,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Open incidents | الحوادث المفتوحة",
            "sum(fl_incident_open)",
            desc("Incidents open, triaging or awaiting approval.", "green 0, amber >= 1, red >= 5: heuristic", ND_SENT),
            steps=[(None, GREEN), (1, AMBER), (5, RED)],
            rb="campaign-surge",
            nodata=ND_SENT,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Avg triage time | متوسط زمن الفرز",
            'sum(rate(fl_sentinel_node_seconds_sum[15m])) / (sum(rate(fl_sentinel_node_seconds_count{node="enrich"}[15m])) > 0)',
            desc(
                "Mean wall time of one triage run (sum of its graph nodes).",
                "green < 60 s, amber 60-120 s, red >= 120 s: the per-incident time budget is 120 s",
                ND_SENT,
            ),
            unit="s",
            steps=[(None, GREEN), (60, AMBER), (120, RED)],
            decimals=1,
            nodata=ND_SENT,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Blocks reverted, 24 h | حظر مُلغى",
            "sum(increase(fl_blocks_reverted_total[24h]))",
            desc(
                "Blocks an operator undid (a proxy for wrong blocks).",
                "none: counts; a rise means false blocks",
                ND_SEC,
            ),
            nodata="0 (series appears at the first revert)",
        ),
        4,
        3,
    )
    b.row("Incidents | الحوادث")
    b.add(
        ts(
            "Incidents opened by type | الحوادث حسب النوع",
            [
                target(
                    src("sum by (type, severity, source) (increase(fl_incidents_total[5m]))"),
                    "{{type}} · {{severity}} · {{source}}",
                )
            ],
            desc(
                "Incidents created per 5 min by type, severity and source.",
                "none: counts; a new high severity fires NewHighIncident",
                ND_SENT,
            ),
            replay=True,
            rb="campaign-surge",
        ),
        8,
        8,
    )
    b.add(
        ts(
            "Open incidents by severity | المفتوحة حسب الخطورة",
            [target("sum by (severity) (fl_incident_open)", "{{severity}}")],
            desc("Open incidents by severity.", "none: composition", ND_SENT),
            stack=True,
        ),
        8,
        8,
    )
    b.add(
        ts(
            "Incidents by status | الحوادث حسب الحالة",
            [target("max by (status) (fl_incident_status)", "{{status}}")],
            desc(
                "Incidents by lifecycle status (open, triaging, awaiting_approval, mitigated, closed).",
                "none: composition",
                ND_NEW,
            ),
            stack=True,
        ),
        8,
        8,
    )
    b.add(
        bargauge(
            "Incidents by rule, 24 h | الحوادث حسب القاعدة",
            "sum by (rule) (increase(fl_rule_fired_total[24h]))",
            "{{rule}}",
            desc(
                "Rule firings that created or changed an incident.",
                "none: counts; R1 is the campaign-surge rule",
                ND_SENT,
            ),
            rb="campaign-surge",
            nodata=ND_SENT,
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Time to incident p50 / p95 | الزمن حتى الحادثة",
            [
                target(q("rate(fl_time_to_incident_seconds_bucket[10m])", 0.5), "p50"),
                target(q("rate(fl_time_to_incident_seconds_bucket[10m])", 0.95), "p95", "B"),
            ],
            desc(
                "Seconds from the triggering event to the incident (live source only).",
                "dashed line at 60 s: amber above, an incident older than a minute is late for a demo",
                ND_SENT,
            ),
            unit="s",
            steps=[(None, GREEN), (60, AMBER), (300, RED)],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Rules fired | القواعد المفعّلة",
            [target("sum by (rule) (increase(fl_rule_fired_total[5m]))", "{{rule}}")],
            desc("Rule firings per 5 min.", "none: counts", ND_SENT),
        ),
        8,
        7,
    )
    b.row("Approvals and actions | الموافقات والإجراءات")
    b.add(
        ts(
            "Approval turnaround p50 / p95 | زمن الموافقة",
            [
                target(q("rate(fl_approval_turnaround_seconds_bucket[1h])", 0.5, ", decision"), "p50 {{decision}}"),
                target(
                    q("rate(fl_approval_turnaround_seconds_bucket[1h])", 0.95, ", decision"), "p95 {{decision}}", "B"
                ),
            ],
            desc(
                "Seconds from a draft being proposed to the operator's decision.",
                "dashed line at 1800 s (30 min): the ApprovalsWaiting alert",
                "no operator decision was made in the window",
            ),
            unit="s",
            steps=[(None, GREEN), (1800, AMBER)],
            rb="approvals-waiting",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Approved vs rejected | الموافقة والرفض",
            [target("sum by (decision) (increase(fl_approval_turnaround_seconds_count[1h]))", "{{decision}}")],
            desc("Operator decisions per hour.", "none: counts", "no operator decision was made in the window"),
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Actions by mode | الإجراءات",
            [target("sum by (action, mode) (increase(fl_sentinel_actions_total[5m]))", "{{action}} · {{mode}}")],
            desc(
                "Executed Sentinel tool calls. External drafts are never sent without approval.",
                "none: counts",
                ND_SENT,
            ),
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Executed vs awaiting approval | منفذ مقابل منتظر",
            [
                target("sum(increase(fl_sentinel_actions_total[1h]))", "executed (1 h)"),
                target("max(fl_approvals_pending)", "awaiting approval", "B"),
            ],
            desc(
                "Actions executed in the last hour against drafts waiting for a human now.",
                "none: compare the two",
                ND_SENT,
            ),
        ),
        8,
        7,
    )
    b.row("LangGraph and summaries | مخطط الحارس")
    b.add(
        ts(
            "Graph node duration p50 / p95 | زمن العقد",
            [
                target(q(f"rate(fl_sentinel_node_seconds_bucket[{RI}])", 0.5, ", node"), "p50 {{node}}"),
                target(q(f"rate(fl_sentinel_node_seconds_bucket[{RI}])", 0.95, ", node"), "p95 {{node}}", "B"),
            ],
            desc(
                "Wall time of each triage node: enrich, compare, assess, summarise, propose, act (act is timed when it finishes, after approval).",
                "dashed line at 120 s: the per-incident budget",
                ND_SENT,
            ),
            unit="s",
            steps=[(None, GREEN), (120, RED)],
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Template vs LLM text | قالب أم نموذج",
            [
                target(
                    "sum by (task, generated_by) (increase(fl_sentinel_text_total[1h]))", "{{task}} · {{generated_by}}"
                )
            ],
            desc(
                "Severity reasons and summaries written by the model (llm) or by the deterministic template (the model failed or the verifier rejected it).",
                "none: composition; template text only, less specific than model text",
                ND_SENT,
            ),
            stack=True,
        ),
        12,
        8,
    )
    b.add(
        ts(
            "New campaign domains | نطاقات حملات جديدة",
            [
                target(
                    src("sum by (brand, source) (increase(fl_campaign_new_domains_total[5m]))"),
                    "{{brand}} · {{source}}",
                )
            ],
            desc("Domains attributed to a brand campaign. REPLAY rows are replayed events.", "none: counts", ND_SENT),
            replay=True,
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Event lag and approvals | التأخر والموافقات",
            [
                target("max(fl_event_lag_seconds)", "event lag (s)"),
                target("max(fl_approvals_pending)", "approvals pending", "B"),
            ],
            desc("Bus lag in seconds and drafts waiting.", "none: see the stats above for the alert levels", ND_SENT),
            rb="sentinel-lag",
        ),
        12,
        7,
    )
    b.add(
        logs(
            "Sentinel logs | سجلات الحارس",
            '{service="sentinel"}',
            desc("Sentinel logs from Loki.", "none", "Loki or the log shipper is down"),
        ),
        24,
        9,
    )
    return b


# ------------------------------------------------------------------------------------------ 7 model quality

PCT_BANDS: Steps = [(None, RED), (0.9, GREEN)]
FPR_BANDS: Steps = [(None, GREEN), (0.02, RED)]

SPLIT_NOTE = (
    "Offline T1 + arbiter on real URLs (OpenPhish community feed plus a curated legitimate list); not a field "
    "estimate (see the artifact's data_notes)."
)


def model_quality() -> Board:
    """Dashboard 7: model quality, from published eval artifacts only."""
    b = Board("fl-model-quality", "Model quality | جودة النموذج", ["quality", "evals"])
    banner(b)
    b.add(
        markdown(
            "Where these numbers come from | مصدر الأرقام",
            "Every tile reads the eval gauges (metric family `eval`), served by the **evals-exporter** from the published artifacts in "
            "`evals/results/published/` (read-only). Tiles show the **latest** artifact per source: value, "
            "bootstrap 95% CI, n and provenance (real or synthetic). No value is typed here; if an artifact is "
            "missing the tile says so. Offline scores are not live accuracy.",
        ),
        16,
        3,
    )
    b.row("Latest artifacts | آخر الأدلة المنشورة")
    b.add(
        table(
            "Artifacts | الملفات المنشورة",
            [target("fl_eval_artifact_info")],
            desc(
                "Every published artifact: source, name, date, git sha, provenance and dataset hash prefix. Sources: main "
                "(T1 + arbiter), fp_regress (held-out real sites), redteam, message_text, dspy, fits.",
                "none: metadata",
                ND_EVAL,
            ),
            transformations=[
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "Value": True,
                            "__name__": True,
                            "job": True,
                            "instance": True,
                            "service": True,
                        },
                        "indexByName": {
                            "source": 0,
                            "artifact": 1,
                            "created_at": 2,
                            "git_sha": 3,
                            "provenance": 4,
                            "dataset_hash": 5,
                        },
                    },
                },
                {"id": "sortBy", "options": {"sort": [{"field": "created_at", "desc": True}]}},
            ],
            nodata=ND_EVAL,
        ),
        24,
        7,
    )
    for split, label in (("val", "Validation | التحقق"), ("test", "Test | الاختبار")):
        b.row(f"{label}: URL model + arbiter (real)")
        tiles = (
            (
                "Recall | الاستدعاء",
                "recall",
                "Share of phishing items that received a warning (suspicious or dangerous).",
                "green >= 90%, red below: the target in docs/EVALS.md",
                PCT_BANDS,
                "percentunit",
            ),
            (
                "Precision | الدقة",
                "precision",
                "Share of warnings that were phishing.",
                "none: docs/EVALS.md sets no precision target",
                None,
                "percentunit",
            ),
            (
                "F1 | مقياس F1",
                "f1",
                "Harmonic mean of precision and recall.",
                "none: docs/EVALS.md sets no F1 target",
                None,
                "percentunit",
            ),
            (
                "False-alarm rate FPR | الإنذار الكاذب",
                "fpr",
                "Share of legitimate items that received a warning.",
                "green <= 2%, red above: the target in docs/EVALS.md",
                FPR_BANDS,
                "percentunit",
            ),
            (
                "ROC-AUC | المساحة تحت ROC",
                "roc_auc",
                "Ranking quality of the calibrated probability across all cut points.",
                "none: docs/EVALS.md sets no AUC target",
                None,
                "percentunit",
            ),
            (
                "PR-AUC | المساحة تحت PR",
                "pr_auc",
                "Average precision: ranking quality that weighs the rare class.",
                "none: docs/EVALS.md sets no PR-AUC target",
                None,
                "percentunit",
            ),
            (
                "Accuracy | الدقة الكلية",
                "accuracy",
                "Correct calls at the warning operating point. Read with FPR and recall: classes are imbalanced.",
                "none: docs/EVALS.md sets no accuracy target",
                None,
                "percentunit",
            ),
            (
                "Calibration error ECE | خطأ المعايرة",
                "ece",
                "Expected calibration error of the probability (lower is better).",
                "none: docs/EVALS.md sets no ECE target",
                None,
                "short",
            ),
        )
        for title, metric, what, thr, steps, unit in tiles:
            b.add(
                eval_tile(
                    f"{title} · {split}",
                    metric,
                    split,
                    what + " " + SPLIT_NOTE,
                    thr,
                    steps,
                    unit=unit,
                    rb="eval-regression",
                ),
                6,
                6,
            )
    b.row("Held-out real sites | مواقع حقيقية خارج العينة")
    b.add(
        eval_tile(
            "False-alarm rate, sites that serve web | الإنذار الكاذب (مواقع تعمل)",
            "false_alarm_rate_serves_web",
            "heldout",
            "Share of held-out real legitimate sites that serve a web page (serves-web) which received a warning, through the running stack. Real sites, live pipeline.",
            "green <= 2%, red above: the target in docs/EVALS.md; this run is a regression check, not tuned on",
            FPR_BANDS,
            source="fp_regress",
            rb="fp-spike",
            nodata="no fp_regress artifact is published yet (run make regress-legit LIVE=1 and publish)",
        ),
        8,
        5,
    )
    b.add(
        eval_tile(
            "False-alarm rate, all held-out sites | الإنذار الكاذب (الكل)",
            "false_alarm_rate",
            "heldout",
            "Share of all held-out legitimate sites with a warning, including hosts that serve no web page (DNS-only names that degrade).",
            "green <= 2%, red above: the target in docs/EVALS.md",
            FPR_BANDS,
            source="fp_regress",
            rb="fp-spike",
            nodata="no fp_regress artifact is published yet",
        ),
        8,
        5,
    )
    b.add(
        table(
            "Held-out runs over time | تشغيلات سابقة",
            [
                target('fl_eval_metric{source="fp_regress",metric="false_alarm_rate_serves_web"}', "", "A"),
                target('fl_eval_ci_low{source="fp_regress",metric="false_alarm_rate_serves_web"}', "", "B"),
                target('fl_eval_ci_high{source="fp_regress",metric="false_alarm_rate_serves_web"}', "", "C"),
                target('fl_eval_n{source="fp_regress",metric="false_alarm_rate_serves_web"}', "", "D"),
            ],
            desc(
                "Every published fp_regress run (serves-web false-alarm rate with CI and n), newest by artifact name.",
                "none: history, compare runs",
                "no fp_regress artifact is published yet",
            ),
            transformations=[
                {"id": "merge", "options": {}},
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "job": True,
                            "instance": True,
                            "service": True,
                            "source": True,
                            "split": True,
                            "metric": True,
                        },
                        "renameByName": {
                            "Value #A": "rate",
                            "Value #B": "CI low",
                            "Value #C": "CI high",
                            "Value #D": "n",
                        },
                    },
                },
            ],
            overrides=[
                {
                    "matcher": {"id": "byName", "options": n},
                    "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 3}],
                }
                for n in ("rate", "CI low", "CI high")
            ],
            nodata="No fp_regress artifact is published yet",
        ),
        8,
        5,
    )
    b.row("Red team and messages | الفريق الأحمر والرسائل")
    b.add(
        eval_tile(
            "Red-team harmful rate | معدل نجاح الهجوم",
            "harmful_rate",
            "all",
            "Share of synthetic injection cases where the attack changed the outcome (target 0%, docs/EVALS.md). Synthetic fixtures (Falcon Demo Bank), reference pipeline.",
            "green 0%, red above: the target is zero injection success",
            [(None, GREEN), (0.0001, RED)],
            source="redteam",
            ci_note="CI = Wilson 95% interval computed by the exporter from k/n in the artifact (the artifact stores no interval).",
            rb="injection-spike",
            nodata="no red-team artifact is published yet (evals/results/published/redteam/ is empty)",
        ),
        8,
        5,
    )
    b.add(
        bargauge(
            "Red-team harmful rate by category | حسب الفئة",
            'fl_eval_metric{source="redteam",metric=~"harmful_rate\\\\..+"}' + LATEST,
            "{{metric}} ({{provenance}})",
            desc(
                "Harmful rate per case kind (page, message, email, url, image) from the latest red-team artifact; synthetic.",
                "green 0%, red above",
                "no red-team artifact is published yet",
            ),
            unit="percentunit",
            steps=[(None, GREEN), (0.0001, RED)],
            nodata="No red-team artifact is published yet",
            pmax=1,
        ),
        8,
        5,
    )
    b.add(
        table(
            "DSPy before / after | قبل وبعد DSPy",
            [target('fl_eval_metric{source="dspy"}' + LATEST)],
            desc(
                "Prompt-optimisation results exactly as stored in the dspy artifact (labels carry provenance).",
                "none: metadata and values as published",
                "no dspy artifact is published yet",
            ),
            transformations=[
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "job": True,
                            "instance": True,
                            "service": True,
                            "source": True,
                        },
                        "renameByName": {"Value": "value"},
                    },
                }
            ],
            nodata="No dspy artifact is published yet",
        ),
        8,
        5,
    )
    msg = (
        (
            "Message-text recall | استدعاء الرسائل",
            "message_path.recall",
            "Share of phishing messages (URLs wrapped in synthetic English/Arabic templates) that received a warning.",
            "none: the message set is synthetic and pending audit, so no target is applied",
            None,
        ),
        (
            "Message-text FPR | الإنذار الكاذب للرسائل",
            "message_path.fpr",
            "Share of legitimate messages that received a warning.",
            "none: synthetic and pending audit, no target is applied",
            None,
        ),
    )
    for title, metric, what, thr, steps in msg:
        b.add(
            eval_tile(
                f"{title} · val · SYNTHETIC, pending audit",
                metric,
                "val",
                what + " SYNTHETIC templates built from real URLs; pending native-speaker audit.",
                thr,
                steps,
                rb="eval-regression",
            ),
            12,
            5,
        )
    for title, metric, what in (
        (
            "Message-text recall | استدعاء الرسائل · test · SYNTHETIC",
            "message_path.recall",
            "Same as val, on the test split.",
        ),
        (
            "Message-text FPR | الإنذار الكاذب للرسائل · test · SYNTHETIC",
            "message_path.fpr",
            "Same as val, on the test split.",
        ),
    ):
        b.add(
            eval_tile(
                title,
                metric,
                "test",
                what + " SYNTHETIC templates, pending audit.",
                "none: synthetic and pending audit",
                None,
            ),
            12,
            5,
        )
    b.row("All headline metrics with CI | كل المقاييس")
    cols = (
        ("A", "value", "fl_eval_metric"),
        ("B", "CI low", "fl_eval_ci_low"),
        ("C", "CI high", "fl_eval_ci_high"),
        ("D", "n", "fl_eval_n"),
    )
    b.add(
        table(
            "Latest main artifact | آخر ملف رئيسي",
            [target(f'{fn}{{source="main"}}' + LATEST, "", ref) for ref, _, fn in cols],
            desc(
                "Every metric of the latest main artifact with bootstrap 95% CI, n and provenance. message_path.* rows are synthetic.",
                "none: reference table",
                ND_EVAL,
            ),
            transformations=[
                {"id": "merge", "options": {}},
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "job": True,
                            "instance": True,
                            "service": True,
                            "source": True,
                        },
                        "renameByName": {f"Value #{r}": n for r, n, _ in cols},
                        "indexByName": {
                            "split": 0,
                            "metric": 1,
                            "value": 2,
                            "CI low": 3,
                            "CI high": 4,
                            "n": 5,
                            "provenance": 6,
                            "artifact": 7,
                        },
                    },
                },
                {"id": "sortBy", "options": {"sort": [{"field": "split"}, {"field": "metric"}]}},
            ],
            nodata=ND_EVAL,
        ),
        24,
        12,
    )
    return b


# ------------------------------------------------------------------------------------------ validation


def validate(board: Board) -> list[str]:
    """Panel rules of the brief: bilingual title, thresholds rationale, no-data explanation."""
    errs: list[str] = []
    for p in board.panels:
        t = p.get("type")
        if t in ("row", "text"):
            continue
        name = f"{board.uid}: {p.get('title')}"
        if " | " not in p.get("title", ""):
            errs.append(f"{name}: title needs 'EN | AR'")
        d = p.get("description", "")
        if t != "logs" and ("Thresholds:" not in d or "No data:" not in d):
            errs.append(f"{name}: description needs 'Thresholds:' and 'No data:'")
    return errs


def main() -> None:
    """Rewrite all seven dashboard JSON files in infra/grafana/dashboards/."""
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    names = {
        "fl-command-overview": "1-command-overview",
        "fl-detection-quality": "2-detection-quality",
        "fl-pipeline": "3-pipeline-performance",
        "fl-ai-ops": "4-ai-operations",
        "fl-security": "5-security",
        "fl-sentinel": "6-sentinel",
        "fl-model-quality": "7-model-quality",
    }
    boards = (overview(), detection(), pipeline(), ai_ops(), security(), sentinel(), model_quality())
    problems = [e for bd in boards for e in validate(bd)]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(1)
    for board in boards:
        path = OUT / f"{names[board.uid]}.json"
        path.write_text(json.dumps(board.json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote", path.name, len(board.panels), "panels")


if __name__ == "__main__":
    main()
