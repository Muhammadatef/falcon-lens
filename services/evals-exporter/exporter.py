"""Falcon Lens evals exporter: publishes the committed eval artifacts to Prometheus (read-only).

It reads ``evals/results/published/**.json`` and serves them as gauges so Grafana can show the numbers that the
eval harness generated. Nothing is computed from live traffic and nothing is typed in: a value is exported only if
it is in an artifact (the one exception is a Wilson 95% interval for red-team rates, from k/n in the artifact,
because that artifact carries no interval of its own).

When to use it:
    It runs as the ``evals-exporter`` service of the ``obs`` compose profile; Prometheus scrapes it.

How to run:
    python services/evals-exporter/exporter.py            (env: FL_EVALS_DIR, FL_EXPORTER_PORT)

Inputs:
    FL_EVALS_DIR   directory with the published artifacts (default /data/published; mounted read-only).
    FL_EXPORTER_PORT  listen port (default 9109).

Outputs / side effects:
    HTTP on 0.0.0.0:<port>: /healthz, /readyz, /metrics. Never writes files, makes no outbound network calls.

Layout understood (everything else falls back to a generic flattener):
    <ts>.json                 main T1 + arbiter artifact (``metrics`` map "split.name", "split.name_ci95")
    fp_regress/*.json         held-out real-site false-alarm runs (``false_positive_rate``, ``by_serves_web``)
    redteam/*.json            red-team runs (``attack_success_rate``, per-case ``kind``, or ``by_category``)
    message_text/*.json, dspy/*.json, fits/*.json, route_compare, cost_per_check, ...   generic: numeric leaves and
    {value, ci95} objects (dotted keys split into path parts). redteam also reads summary.overall / summary.by_category.
    provenance is normalised to real / synthetic / fixture / mixed / unknown (per row for mixed artifacts).

Metrics (all gauges):
    fl_eval_metric{metric,split,source,artifact,provenance}, fl_eval_ci_low / fl_eval_ci_high (same labels),
    fl_eval_n (same labels, when the artifact states n), fl_eval_artifact_timestamp{source,artifact},
    fl_eval_artifact_latest{source,artifact} (1 for the newest artifact of a source),
    fl_eval_artifact_info{source,artifact,git_sha,created_at,provenance,dataset_hash,set,role,route} (1),
    fl_eval_exporter_artifacts, fl_eval_exporter_errors.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_BYTES = 5_000_000
MAX_METRICS_PER_ARTIFACT = 400
SKIP_KEYS = {"items", "cases", "grid", "reliability", "ablation", "model_ids", "seeds", "splits_lock", "thresholds"}
SPLITS = {"val", "test", "train", "heldout"}
# provenance defaults per source; an artifact's own "provenance" field wins when present.
DEFAULT_PROVENANCE = {
    "main": "real",
    "fp_regress": "real",
    "redteam": "synthetic",
    "message_text": "synthetic",
    "dspy": "unknown",
    "fits": "real",
    "arabic_clarity": "fixture",
}
PROVENANCE_VALUES = ("real", "synthetic", "fixture", "mixed", "unknown")
# Sources whose artifact text says "real ... + synthetic ...": rows are labelled one by one (see row_provenance).
MIXED_SOURCES = {"synthetic_split", "sandbox_t2", "faithfulness"}
_LABEL_ESC = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n"})


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n."""
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def normalise_provenance(raw: Any) -> str:
    """Map an artifact's free-text provenance onto the bounded label set real/synthetic/fixture/mixed/unknown."""
    t = str(raw or "").strip().lower()
    if not t:
        return "unknown"
    if t in PROVENANCE_VALUES:
        return t
    if t.startswith("synthetic fixtures") or "fixture-backed" in t or t.startswith("shipped arabic"):
        return "fixture"
    if t.startswith("synthetic"):
        return "synthetic"
    if t.startswith("real"):
        return "mixed" if "synthetic" in t or "fixture" in t else "real"
    return "mixed" if "real" in t and "synthetic" in t else "unknown"


def row_provenance(source: str, metric: str, default: str) -> str:
    """Per-row provenance where one artifact carries both real and synthetic numbers."""
    if metric.startswith("message_path."):
        return "synthetic"
    if source == "synthetic_split":
        if metric.startswith("synthetic_"):
            return "synthetic"
        if metric.startswith(("real_", "manifest_")) or metric.startswith("n.real"):
            return "real"
        if metric.startswith("n.synthetic"):
            return "synthetic"
    elif source == "sandbox_t2":
        if metric.startswith("real_site"):
            return "real"
        if "synthetic" in metric or "fixture" in metric:
            return "fixture"
    elif source == "faithfulness":
        if "real_items" in metric:
            return "real"
        if "sentinel" in metric or "fixture" in metric or "replay" in metric:
            return "synthetic"
        return "real" if metric.split(".")[0] in {"val", "test", "reasons_vs_evidence"} else default
    return default


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v) if math.isfinite(v) else None


def _ci(node: Any) -> tuple[float | None, float | None]:
    """CI from {"ci95": [lo, hi]} or {"ci_low": lo, "ci_high": hi}."""
    if not isinstance(node, dict):
        return None, None
    pair = node.get("ci95")
    if isinstance(pair, list) and len(pair) == 2:
        return _num(pair[0]), _num(pair[1])
    return _num(node.get("ci_low")), _num(node.get("ci_high"))


class Row:
    """One exported number."""

    def __init__(
        self,
        metric: str,
        split: str,
        value: float,
        lo: float | None = None,
        hi: float | None = None,
        n: float | None = None,
    ) -> None:
        self.metric, self.split, self.value, self.lo, self.hi, self.n = metric, split, value, lo, hi, n


def _main_rows(doc: dict[str, Any]) -> list[Row]:
    m = doc.get("metrics", {})
    rows: list[Row] = []
    for key, val in m.items():
        if key.endswith("_ci95") or key.endswith(".n"):
            continue
        v = _num(val)
        if v is None or "." not in key:
            continue
        split, name = key.split(".", 1)
        ci = m.get(f"{key}_ci95")
        lo, hi = (_num(ci[0]), _num(ci[1])) if isinstance(ci, list) and len(ci) == 2 else (None, None)
        n_key = f"{split}.message_path.n" if name.startswith("message_path.") else f"{split}.n"
        rows.append(Row(name, split, v, lo, hi, _num(m.get(n_key))))
    return rows


def _fp_rows(doc: dict[str, Any]) -> list[Row]:
    rows: list[Row] = []
    n = _num(doc.get("n"))
    fpr = doc.get("false_positive_rate")
    if isinstance(fpr, dict) and _num(fpr.get("value")) is not None:
        lo, hi = _ci(fpr)
        rows.append(Row("false_alarm_rate", "heldout", float(fpr["value"]), lo, hi, n))
    groups = (
        ("serves_web_page", "false_alarm_rate_serves_web"),
        ("no_web_host", "false_alarm_rate_no_web_host"),
    )
    for grp, name in groups:
        g = (doc.get("by_serves_web") or {}).get(grp)
        if isinstance(g, dict) and isinstance(g.get("false_positive_rate"), dict):
            f = g["false_positive_rate"]
            if _num(f.get("value")) is not None:
                lo, hi = _ci(f)
                rows.append(Row(name, "heldout", float(f["value"]), lo, hi, _num(g.get("n"))))
    for key in ("degraded", "errors", "false_dangerous", "http_429"):
        if _num(doc.get(key)) is not None:
            rows.append(Row(key, "heldout", float(doc[key]), n=n))
    counts = doc.get("counts")
    if isinstance(counts, dict):
        for label, cnt in counts.items():
            if _num(cnt) is not None:
                rows.append(Row(f"verdict.{label}", "heldout", float(cnt), n=n))
    for grp, suffix in (("serves_web_page", "serves_web"), ("no_web_host", "no_web_host")):
        g = (doc.get("by_serves_web") or {}).get(grp)
        if isinstance(g, dict):
            for key in ("degraded", "false_dangerous", "partial_reads", "static_fallback"):
                if _num(g.get(key)) is not None:
                    rows.append(Row(f"{key}_{suffix}", "heldout", float(g[key]), n=_num(g.get("n"))))
    for tier, cnt in (doc.get("by_tier") or {}).items():
        if _num(cnt) is not None:
            rows.append(Row(f"tier_reached.{tier}", "heldout", float(cnt), n=n))
    for reason, cnt in (doc.get("degraded_reasons") or {}).items():
        if _num(cnt) is not None:
            rows.append(Row(f"degraded_reason.{reason}", "heldout", float(cnt), n=n))
    return rows


def _redteam_node_rows(suffix: str, node: dict[str, Any]) -> list[Row]:
    """harmful rate + counts of one summary node. 'answered' is the number of cases where the model replied."""
    rows: list[Row] = []
    cases = _num(node.get("cases"))
    lo, hi = _ci(node)
    rate = _num(node.get("rate"))
    sfx = f".{suffix}" if suffix else ""
    if rate is not None:
        rows.append(Row(f"harmful_rate{sfx}", "all", rate, lo, hi, cases))
    for src, name in (
        ("harmful", "harmful"),
        ("llm_ran", "answered"),
        ("llm_calls_failed", "llm_calls_failed"),
        ("attack_degraded", "attack_degraded"),
        ("cases", "cases"),
    ):
        v = _num(node.get(src))
        if v is not None:
            rows.append(Row(f"{name}{sfx}", "all", v, n=cases))
    return rows


def _redteam_summary_rows(summary: dict[str, Any]) -> list[Row]:
    rows = _redteam_node_rows("", summary["overall"])
    for outcome, cnt in (summary["overall"].get("by_outcome") or {}).items():
        if _num(cnt) is not None:
            rows.append(Row(f"outcome.{outcome}", "all", float(cnt), n=_num(summary["overall"].get("cases"))))
    for cat, node in sorted((summary.get("by_category") or {}).items()):
        if isinstance(node, dict):
            rows += _redteam_node_rows(str(cat), node)
    return rows


def _redteam_rows(doc: dict[str, Any]) -> list[Row]:
    rows: list[Row] = []
    total = _num(doc.get("cases_total"))
    count = _num(doc.get("attack_success_count"))
    rate = _num(doc.get("attack_success_rate"))
    if rate is not None:
        lo, hi = _ci(doc)
        if lo is None and count is not None and total:
            lo, hi = wilson(int(count), int(total))
        rows.append(Row("harmful_rate", "all", rate, lo, hi, total))
    summary = doc.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("overall"), dict):
        rows += _redteam_summary_rows(summary)
        return rows
    by_cat = doc.get("by_category")
    if isinstance(by_cat, dict):
        for cat, node in by_cat.items():
            if isinstance(node, dict):
                r, n = _num(node.get("rate", node.get("attack_success_rate"))), _num(node.get("n", node.get("cases")))
                lo, hi = _ci(node)
                if r is not None:
                    rows.append(Row(f"harmful_rate.{cat}", "all", r, lo, hi, n))
    elif isinstance(doc.get("cases"), list):
        agg: dict[str, list[int]] = {}
        for c in doc["cases"]:
            if isinstance(c, dict):
                a = agg.setdefault(str(c.get("kind", "other")), [0, 0])
                a[0] += int(bool(c.get("attack_success")))
                a[1] += 1
        for cat, (k, cases) in sorted(agg.items()):
            lo, hi = wilson(k, cases)
            rows.append(Row(f"harmful_rate.{cat}", "all", k / cases, lo, hi, float(cases)))
    ab = doc.get("ablation")
    if isinstance(ab, dict) and _num(ab.get("attack_success_rate")) is not None:
        rows.append(
            Row(
                "harmful_rate_without_neutralise",
                "all",
                float(ab["attack_success_rate"]),
                n=_num(ab.get("cases_total")),
            )
        )
    return rows


def _walk(node: Any, path: list[str], out: list[Row], depth: int = 0) -> None:
    if depth > 5 or len(out) >= MAX_METRICS_PER_ARTIFACT:
        return
    if isinstance(node, dict):
        v = _num(node.get("value"))
        if v is not None:
            lo, hi = _ci(node)
            split = next((p for p in path if p in SPLITS), "all")
            name = ".".join(p for p in path if p not in SPLITS) or "value"
            out.append(Row(name, split, v, lo, hi, _num(node.get("n"))))
            return
        for k, child in node.items():
            if k in SKIP_KEYS or str(k).endswith("_ci95"):
                continue
            _walk(child, [*path, *str(k).split(".")], out, depth + 1)
    else:
        v = _num(node)
        if v is not None and path:
            split = next((p for p in path if p in SPLITS), "all")
            out.append(Row(".".join(p for p in path if p not in SPLITS), split, v))


def _generic_rows(doc: dict[str, Any]) -> list[Row]:
    out: list[Row] = []
    _walk(doc, [], out)
    return out


def _dspy_rows(doc: dict[str, Any]) -> list[Row]:
    """Generic numbers plus the adoption decision (adopted 0/1) and the before/after validation means."""
    rows = _generic_rows(doc)
    if isinstance(doc.get("adopted"), bool):
        rows.append(Row("adopted", "all", 1.0 if doc["adopted"] else 0.0))
    return rows


def _fits_rows(doc: dict[str, Any]) -> list[Row]:
    """Measured values of a threshold fit only (rates on the fit split, with their n); never the fitted
    parameters (margin, strong_adj), the constraints, the seed or the grid, which are configuration."""
    chosen = doc.get("chosen")
    if not isinstance(chosen, dict):
        return []
    split = str(doc.get("split", "val"))
    rows: list[Row] = []
    for key, n_key in (
        ("fpr_form", "n_legit"),
        ("fpr_url_only", "n_legit"),
        ("recall_form", "n_phishing"),
        ("recall_url_only", "n_phishing"),
    ):
        v = _num(chosen.get(key))
        if v is not None:
            rows.append(Row(key, split, v, n=_num(chosen.get(n_key))))
    return rows


def _w95(node: Any) -> tuple[float | None, float | None]:
    pair = node.get("wilson95") or node.get("bootstrap95") if isinstance(node, dict) else None
    return (_num(pair[0]), _num(pair[1])) if isinstance(pair, list) and len(pair) == 2 else (None, None)


def _fresh200_rows(doc: dict[str, Any]) -> list[Row]:
    """Headline aggregates only (bounded names): confusion metrics of the main and second-source runs plus the
    degraded rate per class. Never the per-group breakdowns, examples, tiers or reasons."""
    rows: list[Row] = []
    for split, key in (("main", "results"), ("second_source", "results_second_source")):
        res = doc.get(key)
        if not isinstance(res, dict):
            continue
        for scope, block in (("all", "overall_all_phishing"), ("live", "overall_live_phishing_only")):
            for mode, sub in (("any", "any_warning"), ("dangerous", "dangerous_only")):
                node = (res.get(block) or {}).get(sub) or {}
                for name in ("recall", "false_positive_rate", "precision", "f1", "accuracy"):
                    m = node.get(name)
                    v = _num(m.get("value")) if isinstance(m, dict) else None
                    if v is None:
                        continue
                    lo, hi = _w95(m)
                    rows.append(Row(f"{scope}_{mode}_{name}", split, v, lo, hi))
        for g in ("phishing_all", "legit_all"):
            d = ((res.get("groups") or {}).get(g) or {}).get("degraded")
            v = _num(d.get("value")) if isinstance(d, dict) else None
            if v is not None:
                lo, hi = _w95(d)
                rows.append(Row(f"{g}_degraded_rate", split, v, lo, hi, _num(d.get("n"))))
    return rows


def artifact_rows(source: str, doc: dict[str, Any]) -> list[Row]:
    """The rows of one artifact, by source layout."""
    if source == "main":
        return _main_rows(doc)
    if source == "fp_regress":
        return _fp_rows(doc)
    if source == "redteam":
        return _redteam_rows(doc)
    if source == "fits":
        return _fits_rows(doc)
    if source == "dspy":
        return _dspy_rows(doc)
    if source == "fresh200":
        return _fresh200_rows(doc)
    return _generic_rows(doc)


def _timestamp(doc: dict[str, Any], path: Path) -> float:
    for key in ("created_at", "generated_at", "fit_date", "date"):
        val = doc.get(key)
        if isinstance(val, str):
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y%m%dT%H%M%SZ", "%Y-%m-%d"):
                try:
                    return datetime.strptime(val, fmt).replace(tzinfo=UTC).timestamp()
                except ValueError:
                    continue
    return path.stat().st_mtime


def _source_of(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    return rel.parts[0] if len(rel.parts) > 1 else "main"


def _esc(v: Any) -> str:
    return str(v).translate(_LABEL_ESC)


def _line(name: str, labels: dict[str, Any], value: float) -> str:
    lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
    return f"{name}{{{lab}}} {value!r}"


def iter_artifacts(root: Path) -> Iterator[tuple[str, Path]]:
    """(source, path) for every readable .json under root."""
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*.json")):
        if p.is_file() and not p.is_symlink() and p.stat().st_size <= MAX_BYTES:
            yield _source_of(root, p), p


def render(root: Path) -> tuple[str, int, int]:
    """Prometheus text for the artifacts under root; also (artifact count, error count)."""
    docs: list[tuple[str, Path, dict[str, Any], float]] = []
    errors = 0
    for source, path in iter_artifacts(root):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("not an object")
            docs.append((source, path, doc, _timestamp(doc, path)))
        except (OSError, ValueError):
            errors += 1
    latest: dict[str, float] = {}
    for source, _, _, ts in docs:
        latest[source] = max(latest.get(source, 0.0), ts)
    heads = {
        "fl_eval_metric": "Value from a published eval artifact (labels: metric, split, source, artifact, provenance)",
        "fl_eval_ci_low": "Lower bound of the artifact's 95% confidence interval",
        "fl_eval_ci_high": "Upper bound of the artifact's 95% confidence interval",
        "fl_eval_n": "Sample size behind the metric, as stated in the artifact",
        "fl_eval_artifact_timestamp": "Artifact creation time (unix seconds; file mtime if the artifact has no date)",
        "fl_eval_artifact_latest": "1 for the newest artifact of each source",
        "fl_eval_artifact_info": "Artifact metadata (sha, date, provenance, dataset hash, fp set, dspy role, route)",
    }
    body: dict[str, list[str]] = {k: [] for k in heads}
    for source, path, doc, ts in docs:
        base = {"source": source, "artifact": path.stem}
        default_prov = DEFAULT_PROVENANCE.get(source, "unknown")
        raw_prov = doc.get("provenance")
        if raw_prov is None and doc.get("synthetic_data") is True:
            raw_prov = "synthetic"
        prov = normalise_provenance(raw_prov) if raw_prov else default_prov
        if source in MIXED_SOURCES and prov != "mixed" and raw_prov:
            prov = normalise_provenance(raw_prov)
        body["fl_eval_artifact_timestamp"].append(_line("fl_eval_artifact_timestamp", base, ts))
        if ts == latest[source]:
            body["fl_eval_artifact_latest"].append(_line("fl_eval_artifact_latest", base, 1.0))
        info = {
            **base,
            "git_sha": str(doc.get("git_sha", ""))[:12],
            "created_at": doc.get("created_at") or doc.get("generated_at") or "",
            "provenance": prov,
            "set": str(doc.get("set") or "")[:60],
            "role": str(doc.get("role") or "")[:30],
            "route": str(doc.get("route") or doc.get("model_route") or "")[:30],
            "dataset_hash": str(doc.get("dataset_hash", ""))[:12],
        }
        body["fl_eval_artifact_info"].append(_line("fl_eval_artifact_info", info, 1.0))
        for row in artifact_rows(source, doc):
            row_prov = row_provenance(source, row.metric, prov)
            lab = {"metric": row.metric, "split": row.split, **base, "provenance": row_prov}
            body["fl_eval_metric"].append(_line("fl_eval_metric", lab, row.value))
            for name, val in (("fl_eval_ci_low", row.lo), ("fl_eval_ci_high", row.hi), ("fl_eval_n", row.n)):
                if val is not None and math.isfinite(val):
                    body[name].append(_line(name, lab, val))
    lines: list[str] = []
    for name, text in heads.items():
        lines += [f"# HELP {name} {text}", f"# TYPE {name} gauge", *body[name]]
    lines += [
        "# HELP fl_eval_exporter_artifacts Artifacts read in the last scrape",
        "# TYPE fl_eval_exporter_artifacts gauge",
        f"fl_eval_exporter_artifacts {len(docs)}",
        "# HELP fl_eval_exporter_errors Artifacts that could not be parsed in the last scrape",
        "# TYPE fl_eval_exporter_errors gauge",
        f"fl_eval_exporter_errors {errors}",
    ]
    return "\n".join(lines) + "\n", len(docs), errors


class Handler(BaseHTTPRequestHandler):
    """/healthz, /readyz, /metrics."""

    root: Path = Path(os.environ.get("FL_EVALS_DIR", "/data/published"))

    def _send(self, code: int, body: str, ctype: str = "text/plain; version=0.0.4; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send(200, "ok\n")
        elif path == "/readyz":
            ready = self.root.is_dir()
            self._send(200 if ready else 503, "ready\n" if ready else "evals directory missing\n")
        elif path == "/metrics":
            text, _, _ = render(self.root)
            self._send(200, text)
        else:
            self._send(404, "not found\n")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write(json.dumps({"service": "evals-exporter", "msg": format % args}) + "\n")


def main() -> None:
    """Serve until killed."""
    port = int(os.environ.get("FL_EXPORTER_PORT", "9109"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104


if __name__ == "__main__":
    main()
