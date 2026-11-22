#!/usr/bin/env python3
"""Generates the six Falcon Lens Grafana dashboards into infra/grafana/dashboards/*.json.

The JSON is committed (Grafana provisions it from disk); this script keeps the six
consistent: 5 s refresh, a REPLAY banner, `source`-split series, EN | AR titles.
Run: uv run python infra/grafana/gen_dashboards.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).parent / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

ORANGE = "#F5A623"  # replay
GREEN = "#3FB68B"
RED = "#E5484D"
BLUE = "#5B9BF0"
GOLD = "#D4AF37"  # falcon accent
MUTED = "#8A94A6"

Panel = dict[str, Any]


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


class Board:
    def __init__(self, uid: str, title: str, tags: list[str]) -> None:
        self.uid, self.title, self.tags = uid, title, tags
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
            "version": 2,
            "editable": False,
            "graphTooltip": 1,
            "refresh": "5s",
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


NAV = [
    ("fl-command-overview", "Command overview", "مركز القيادة"),
    ("fl-detection-quality", "Detection quality", "جودة الكشف"),
    ("fl-pipeline", "Pipeline performance", "أداء المسار"),
    ("fl-ai-ops", "AI operations", "عمليات الذكاء الاصطناعي"),
    ("fl-security", "Security", "الأمن"),
    ("fl-sentinel", "Sentinel", "الحارس"),
]


def target(expr: str, legend: str = "", ref: str = "A", instant: bool = False) -> dict[str, Any]:
    t: dict[str, Any] = {"refId": ref, "expr": expr, "datasource": PROM, "legendFormat": legend}
    if instant:
        t["instant"] = True
    return t


def ts(
    title: str,
    targets: list[dict[str, Any]],
    unit: str = "short",
    replay: bool = False,
    stack: bool = False,
    desc: str = "",
) -> Panel:
    overrides = REPLAY_OVERRIDES if replay else []
    return {
        "type": "timeseries",
        "title": title + (" | REPLAY-aware" if replay else ""),
        "description": desc
        + (
            " Series with source=replay are drawn dashed orange and labelled REPLAY."
            if replay
            else ""
        ),
        "datasource": PROM,
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {
                    "lineWidth": 2,
                    "fillOpacity": 18,
                    "showPoints": "never",
                    "spanNulls": True,
                    "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                },
            },
            "overrides": overrides,
        },
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def stat(
    title: str,
    expr: str,
    unit: str = "short",
    steps: list[tuple[float | None, str]] | None = None,
    desc: str = "",
    decimals: int | None = None,
    graph: bool = True,
) -> Panel:
    steps = steps or [(None, BLUE)]
    d: dict[str, Any] = {
        "unit": unit,
        "color": {"mode": "thresholds"},
        "thresholds": {
            "mode": "absolute",
            "steps": [{"color": c, "value": v} for v, c in steps],
        },
    }
    if decimals is not None:
        d["decimals"] = decimals
    return {
        "type": "stat",
        "title": title,
        "description": desc,
        "datasource": PROM,
        "targets": [target(expr)],
        "fieldConfig": {"defaults": d, "overrides": []},
        "options": {
            "colorMode": "background",
            "graphMode": "area" if graph else "none",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    }


def banner(board: Board) -> None:
    """Top strip: REPLAY vs LIVE, driven by the `source` label of fl_checks_total."""
    expr = 'clamp_max(sum(increase(fl_checks_total{source="replay"}[5m])), 1) or vector(0)'
    p = stat(
        "Data source | مصدر البيانات",
        expr,
        desc='REPLAY when any fl_checks_total{source="replay"} was recorded in the last 5 minutes.'
        " Replayed or synthetic data is never presented as live.",
        graph=False,
    )
    p["fieldConfig"]["defaults"]["mappings"] = [
        {
            "type": "value",
            "options": {
                "1": {
                    "text": "REPLAY DATA ACTIVE | بيانات إعادة تشغيل",
                    "color": ORANGE,
                    "index": 0,
                },
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
    return {
        "type": "text",
        "title": title,
        "options": {"mode": "markdown", "content": content},
        "transparent": True,
    }


def table(title: str, targets: list[dict[str, Any]], desc: str = "") -> Panel:
    for t in targets:
        t["format"] = "table"
        t["instant"] = True
    return {
        "type": "table",
        "title": title,
        "description": desc,
        "datasource": PROM,
        "targets": targets,
        "transformations": [
            {"id": "organize", "options": {"excludeByName": {"Time": True}}},
        ],
        "options": {"showHeader": True},
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def bargauge(title: str, expr: str, legend: str, unit: str = "short") -> Panel:
    return {
        "type": "bargauge",
        "title": title,
        "datasource": PROM,
        "targets": [target(expr, legend, instant=True)],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "fixed", "fixedColor": GOLD},
                "min": 0,
            },
            "overrides": [],
        },
        "options": {
            "orientation": "horizontal",
            "displayMode": "gradient",
            "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
        },
    }


def donut(title: str, expr: str, legend: str, replay: bool = False) -> Panel:
    return {
        "type": "piechart",
        "title": title,
        "datasource": PROM,
        "targets": [target(expr, legend, instant=True)],
        "options": {
            "pieType": "donut",
            "legend": {"displayMode": "table", "placement": "right", "values": ["value"]},
            "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def logs(title: str, expr: str) -> Panel:
    return {
        "type": "logs",
        "title": title,
        "datasource": LOKI,
        "targets": [{"refId": "A", "expr": expr, "datasource": LOKI}],
        "options": {
            "showTime": True,
            "wrapLogMessage": True,
            "enableLogDetails": True,
            "sortOrder": "Descending",
        },  # fmt: skip
    }


def heatmap(title: str, expr: str) -> Panel:
    return {
        "type": "heatmap",
        "title": title,
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


def q(metric_expr: str, quantile: float, stage_sel: str = "") -> str:
    return f"histogram_quantile({quantile}, sum by (le{stage_sel}) ({metric_expr}))"


GOOD_BAD = [(None, GREEN), (1, RED)]


def overview() -> Board:
    b = Board("fl-command-overview", "Command overview | مركز القيادة", ["overview"])
    banner(b)
    b.add(
        stat(
            "Checks / min | فحوصات في الدقيقة",
            "sum(rate(fl_checks_total[1m])) * 60",
            decimals=1,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "p95 latency | زمن الاستجابة (p95)",
            "histogram_quantile(0.95, sum by (le) "
            '(rate(fl_stage_latency_seconds_bucket{stage="total"}[5m])))',
            unit="s",
            steps=[(None, GREEN), (6, ORANGE), (8, RED)],
            desc="End-to-end (stage=total). Objective: p95 < 8 s.",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Open incidents | الحوادث المفتوحة",
            "sum(fl_incident_open)",
            steps=[(None, GREEN), (1, ORANGE), (5, RED)],
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Approvals pending | بانتظار الموافقة",
            "sum(fl_approvals_pending)",
            steps=[(None, GREEN), (1, ORANGE)],
        ),
        4,
        3,
    )
    b.row("Verdicts | الأحكام")
    b.add(
        ts(
            "Checks by verdict | الفحوصات حسب الحكم",
            [
                target(
                    src("sum by (verdict, source) (rate(fl_checks_total[1m])) * 60"),
                    "{{verdict}} · {{source}}",
                )
            ],
            replay=True,
            stack=True,
        ),
        14,
        9,
    )
    b.add(
        donut(
            "Verdict mix, last hour | توزيع الأحكام",
            "sum by (verdict) (increase(fl_checks_total[1h]))",
            "{{verdict}}",
        ),
        10,
        9,
    )
    b.row("Health | الصحة")
    b.add(
        ts(
            "Checks by source | الفحوصات حسب المصدر",
            [target(src("sum by (source) (rate(fl_checks_total[1m])) * 60"), "{{source}}")],
            replay=True,
        ),
        8,
        7,
    )
    b.add(
        table(
            "Firing alerts | التنبيهات النشطة",
            [target('sum by (alertname, severity) (ALERTS{alertstate="firing"})')],
        ),
        8,
        7,
    )
    b.add(
        stat(
            "Scrape targets down | أهداف متوقفة",
            "count(up == 0) or vector(0)",
            steps=GOOD_BAD,
        ),
        4,
        7,
    )
    b.add(
        stat(
            "Degraded results / h | نتائج متدهورة",
            "sum(increase(fl_degraded_total[1h]))",
            steps=[(None, GREEN), (1, ORANGE)],
        ),
        4,
        7,
    )
    b.add(logs("Service logs | سجلات الخدمات", '{service=~".+"}'), 24, 10)
    return b


def detection() -> Board:
    b = Board("fl-detection-quality", "Detection quality | جودة الكشف", ["quality"])
    banner(b)
    b.add(
        markdown(
            "Where these numbers come from",
            "Eval panels show `fl_eval_metric`, written from the latest **generated eval artifact**"
            " (`evals/results/`). Nothing here is typed in by hand. Panels fed by replayed traffic"
            " are marked REPLAY.",
        ),
        16,
        3,
    )
    b.row("Eval artifact | نتائج التقييم")
    b.add(
        table(
            "Latest eval metrics | آخر مقاييس التقييم",
            [target("fl_eval_metric")],
            desc="From the latest eval artifact. Labels: name, split, route.",
        ),
        12,
        9,
    )
    b.add(
        ts(
            "Eval metrics over time | المقاييس عبر الزمن",
            [target("fl_eval_metric", "{{name}} · {{split}} · {{route}}")],
        ),
        12,
        9,
    )
    b.row("Live signals | مؤشرات التشغيل")
    b.add(
        ts(
            "Route agreement | اتفاق المسارات",
            [target("fl_route_agreement_ratio", "agreement")],
            unit="percentunit",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Score drift index | انحراف الدرجات",
            [target("fl_score_drift_index", "drift")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "User feedback | ملاحظات المستخدمين",
            [target("sum by (type) (increase(fl_user_feedback_total[15m]))", "{{type}}")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Verdicts by tier | الأحكام حسب المستوى",
            [
                target(
                    src("sum by (tier, source) (rate(fl_checks_total[1m])) * 60"),
                    "{{tier}} · {{source}}",
                )
            ],
            replay=True,
            stack=True,
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Escalations | التصعيدات",
            [
                target(
                    "sum by (from, to) (rate(fl_escalations_total[5m])) * 60",
                    "{{from}} -> {{to}}",
                )
            ],
        ),
        12,
        8,
    )
    b.add(
        bargauge(
            "Top impersonated brands, 1 h | أكثر العلامات انتحالاً",
            "topk(10, sum by (brand) (increase(fl_brand_impersonation_total[1h])))",
            "{{brand}}",
        ),
        12,
        8,
    )
    b.add(
        bargauge(
            "New campaign domains by brand | نطاقات جديدة",
            src("topk(10, sum by (brand, source) (increase(fl_campaign_new_domains_total[1h])))"),
            "{{brand}} · {{source}}",
        ),
        12,
        8,
    )
    return b


def pipeline() -> Board:
    b = Board("fl-pipeline", "Pipeline performance | أداء المسار", ["pipeline"])
    banner(b)
    b.add(
        stat(
            "p95 end-to-end | زمن p95",
            q('rate(fl_stage_latency_seconds_bucket{stage="total"}[5m])', 0.95),
            unit="s",
            steps=[(None, GREEN), (6, ORANGE), (8, RED)],
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Slow ratio (>8 s), 1 h | نسبة البطء",
            "fl:check_slow_ratio:rate1h",
            unit="percentunit",
            steps=[(None, GREEN), (0.05, ORANGE), (0.72, RED)],
            desc="Budget is 5%. Recording rule from infra/prometheus/rules/falcon-alerts.yml.",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Burn rate, 1 h | معدل الاستهلاك",
            "fl:check_slow_ratio:rate1h / 0.05",
            steps=[(None, GREEN), (1, ORANGE), (14.4, RED)],
            decimals=1,
        ),
        4,
        3,
    )
    b.row("Latency per stage | الزمن لكل مرحلة")
    for qt, label in ((0.5, "p50"), (0.95, "p95"), (0.99, "p99")):
        b.add(
            ts(
                f"Stage latency {label} | زمن المرحلة",
                [
                    target(
                        q("rate(fl_stage_latency_seconds_bucket[5m])", qt, ", stage"),
                        "{{stage}}",
                    )
                ],
                unit="s",
            ),
            8,
            8,
        )
    b.add(
        heatmap(
            "End-to-end latency heatmap | خريطة الزمن",
            'sum by (le) (increase(fl_stage_latency_seconds_bucket{stage="total"}[1m]))',
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Checks by tier | الفحوصات حسب المستوى",
            [
                target(
                    src("sum by (tier, source) (rate(fl_checks_total[1m])) * 60"),
                    "{{tier}} · {{source}}",
                )
            ],
            replay=True,
            stack=True,
        ),
        12,
        8,
    )
    b.row("Errors and caches | الأخطاء والذاكرة المؤقتة")
    b.add(
        ts(
            "Tool errors | أخطاء الأدوات",
            [
                target(
                    "sum by (tool, reason) (increase(fl_tool_errors_total[5m]))",
                    "{{tool}} · {{reason}}",
                )
            ],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Cache hits by layer | إصابات الذاكرة",
            [target("sum by (layer) (rate(fl_cache_hits_total[1m])) * 60", "{{layer}}")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Sandbox timeouts | مهلات الصندوق",
            [target("sum(increase(fl_sandbox_timeouts_total[5m]))", "timeouts")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "API requests by status | طلبات الواجهة",
            [
                target(
                    "sum by (service, status) (rate(fl_http_requests_total[1m]))",
                    "{{service}} {{status}}",
                )
            ],
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Feed age | عمر المصادر",
            [target("fl_feed_age_seconds", "{{feed}}")],
            unit="s",
            desc="Alert FeedStale fires above 1 h for enabled feeds.",
        ),
        12,
        7,
    )
    return b


def ai_ops() -> Board:
    b = Board("fl-ai-ops", "AI operations | عمليات الذكاء الاصطناعي", ["ai"])
    banner(b)
    b.add(
        stat(
            "LLM spend, 1 h | تكلفة النماذج",
            "sum(increase(fl_llm_cost_usd_total[1h]))",
            unit="currencyUSD",
            decimals=4,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Fallbacks, 1 h | الرجوع للنموذج المحلي",
            "sum(increase(fl_llm_fallback_total[1h]))",
            steps=[(None, GREEN), (1, ORANGE)],
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Canary leaks | تسرب الكناري",
            "sum(increase(fl_canary_leak_total[1h]))",
            steps=GOOD_BAD,
            desc="Must stay 0. A canary seen in model output means prompt exfiltration.",
        ),
        4,
        3,
    )
    b.add(
        markdown(
            "Traces | التتبع",
            "LLM spans (OpenInference) go collector -> **Phoenix**."
            " Filter by `verdict_id` to join a trace with its logs (Loki) and metrics.",
        ),
        4,
        3,
    )
    b.row("Usage | الاستخدام")
    b.add(
        ts(
            "Tokens / min by model and role | الرموز",
            [
                target(
                    "sum by (model, role) (rate(fl_llm_tokens_total[1m])) * 60",
                    "{{model}} · {{role}}",
                )
            ],
            stack=True,
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Cost rate (USD/h) | معدل التكلفة",
            [target("sum by (model) (rate(fl_llm_cost_usd_total[5m])) * 3600", "{{model}}")],
            unit="currencyUSD",
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Fallbacks by role | الرجوع حسب الدور",
            [target("sum by (role) (increase(fl_llm_fallback_total[5m]))", "{{role}}")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Route agreement | اتفاق المسارات",
            [target("fl_route_agreement_ratio", "agreement")],
            unit="percentunit",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Agent steps p50 / p95 | خطوات الوكيل",
            [
                target(q("rate(fl_agent_steps_bucket[5m])", 0.5), "p50"),
                target(q("rate(fl_agent_steps_bucket[5m])", 0.95), "p95", ref="B"),
            ],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Escalations to LLM tier | التصعيد للنموذج",
            [
                target(
                    "sum by (from, to) (rate(fl_escalations_total[5m])) * 60", "{{from}} -> {{to}}"
                )
            ],
        ),
        12,
        7,
    )
    b.add(
        ts(
            "Checks reaching T3 | فحوصات المستوى الثالث",
            [
                target(
                    src('sum by (source) (rate(fl_checks_total{tier="t3"}[5m])) * 60'), "{{source}}"
                )
            ],
            replay=True,
        ),
        12,
        7,
    )
    return b


def security() -> Board:
    b = Board("fl-security", "Security | الأمن", ["security"])
    banner(b)
    b.add(
        stat(
            "SSRF blocked, 1 h | حظر SSRF",
            "sum(increase(fl_ssrf_blocked_total[1h]))",
            steps=[(None, GREEN), (1, ORANGE)],
            desc="Expected under redteam replay. On live traffic, review the reasons.",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Injection detected, 1 h | حقن التعليمات",
            "sum(increase(fl_injection_detected_total[1h]))",
            steps=[(None, GREEN), (1, ORANGE)],
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Auth failures, 1 h | فشل المصادقة",
            "sum(increase(fl_auth_failures_total[1h]))",
            steps=[(None, GREEN), (5, ORANGE), (20, RED)],
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Canary leaks | تسرب الكناري",
            "sum(increase(fl_canary_leak_total[1h]))",
            steps=GOOD_BAD,
        ),
        4,
        3,
    )
    b.row("Blocked and detected | المحظور والمكتشف")
    b.add(
        ts(
            "SSRF blocked by reason | حظر SSRF حسب السبب",
            [target("sum by (reason) (increase(fl_ssrf_blocked_total[5m]))", "{{reason}}")],
            stack=True,
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Injection and canary | الحقن والكناري",
            [
                target("sum(increase(fl_injection_detected_total[5m]))", "injection"),
                target("sum(increase(fl_canary_leak_total[5m]))", "canary leak", ref="B"),
            ],
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Rate limited by scope | تحديد المعدل",
            [target("sum by (scope) (increase(fl_rate_limited_total[5m]))", "{{scope}}")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Auth failures | فشل المصادقة",
            [target("sum(increase(fl_auth_failures_total[5m]))", "failures")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Replay vs live checks | إعادة التشغيل مقابل المباشر",
            [target(src("sum by (source) (rate(fl_checks_total[1m])) * 60"), "{{source}}")],
            replay=True,
            desc="Redteam replay spikes the panels on this board; compare with live volume.",
        ),
        8,
        7,
    )
    b.add(
        logs(
            "Security log lines | سجلات أمنية",
            '{service=~".+"} |~ "(?i)ssrf|injection|canary|blocked|auth"',
        ),
        24,
        10,
    )
    return b


def sentinel() -> Board:
    b = Board("fl-sentinel", "Sentinel | الحارس", ["sentinel"])
    banner(b)
    b.add(
        stat(
            "Event lag | تأخر الأحداث",
            "max(fl_event_lag_seconds)",
            unit="s",
            steps=[(None, GREEN), (30, ORANGE), (60, RED)],
            desc="Alert SentinelLag above 60 s.",
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Dead letters, 1 h | رسائل ميتة",
            "sum(increase(fl_sentinel_dead_letter_total[1h]))",
            steps=GOOD_BAD,
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Approvals pending | بانتظار الموافقة",
            "sum(fl_approvals_pending)",
            steps=[(None, GREEN), (1, ORANGE)],
        ),
        4,
        3,
    )
    b.add(
        stat(
            "Blocks reverted, 24 h | حظر مُلغى",
            "sum(increase(fl_blocks_reverted_total[24h]))",
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
            replay=True,
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Open incidents by severity | الحوادث المفتوحة",
            [target("sum by (severity) (fl_incident_open)", "{{severity}}")],
            stack=True,
        ),
        12,
        8,
    )
    b.add(
        ts(
            "Time to incident p50 / p95 | الزمن حتى الحادثة",
            [
                target(q("rate(fl_time_to_incident_seconds_bucket[10m])", 0.5), "p50"),
                target(q("rate(fl_time_to_incident_seconds_bucket[10m])", 0.95), "p95", ref="B"),
            ],
            unit="s",
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Rules fired | القواعد المفعّلة",
            [target("sum by (rule) (increase(fl_rule_fired_total[5m]))", "{{rule}}")],
        ),
        8,
        7,
    )
    b.add(
        ts(
            "Actions by mode | الإجراءات",
            [
                target(
                    "sum by (action, mode) (increase(fl_sentinel_actions_total[5m]))",
                    "{{action}} · {{mode}}",
                )
            ],
        ),
        8,
        7,
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
                target("sum(fl_approvals_pending)", "approvals pending", ref="B"),
            ],
        ),
        12,
        7,
    )
    b.add(logs("Sentinel logs | سجلات الحارس", '{service="sentinel"}'), 24, 9)
    return b


def main() -> None:
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
    }
    for board in (overview(), detection(), pipeline(), ai_ops(), security(), sentinel()):
        path = OUT / f"{names[board.uid]}.json"
        path.write_text(
            json.dumps(board.json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("wrote", path.name, len(board.panels), "panels")


if __name__ == "__main__":
    main()
