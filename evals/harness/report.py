"""HTML report and Prometheus textfile rendered from an eval artifact dict (no numbers are typed here).

When to use it:
    As a library, imported by run.py after the numbers are computed. No files are written here and no
    network is used; it only turns a result dict into HTML text and Prometheus text.
"""

from __future__ import annotations

import html
import json
from typing import Any

HEADLINE = ("precision", "recall", "f1", "fpr", "accuracy", "roc_auc", "pr_auc", "ece")


def _n(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def _fmt(m: Any) -> str:
    if isinstance(m, dict) and "value" in m:
        if m["value"] is None:
            return "n/a"
        return f"{m['value']:.4f} [{_n(m['ci_low'])}, {_n(m['ci_high'])}]"
    if isinstance(m, dict) and m.get("status") == "not_evaluated":
        return f"not_evaluated ({m['reason']})"
    return str(m)


def render_prom(doc: dict[str, Any]) -> str:
    """Textfile-collector format. Route is `none`: T1 and the arbiter use no LLM; LLM routes are not emitted."""
    lines = [
        "# HELP fl_eval_metric Offline eval headline metric (value, ci_low, ci_high) from evals/results/latest.json",
        "# TYPE fl_eval_metric gauge",
    ]
    for split, s in sorted(doc["splits"].items()):
        for name in HEADLINE:
            m = s["overall"][name]
            for suffix, key in (("", "value"), ("_ci_low", "ci_low"), ("_ci_high", "ci_high")):
                if m[key] is not None:
                    lines.append(f'fl_eval_metric{{name="{name}{suffix}",split="{split}",route="none"}} {m[key]}')
        fd = s["verified_official"]["false_dangerous"]
        lines.append(f'fl_eval_metric{{name="official_false_dangerous",split="{split}",route="none"}} {fd}')
    lines.append(f'fl_eval_info{{git_sha="{doc["git_sha"]}",dataset_hash="{doc["dataset_hash"][:12]}"}} 1')
    return "\n".join(lines) + "\n"


def render_html(doc: dict[str, Any]) -> str:
    """Render the eval artifact as a standalone HTML page."""
    e = html.escape
    parts = [
        "<!doctype html><meta charset=utf-8><title>Falcon Lens eval</title>",
        "<style>body{font:14px sans-serif;margin:2em}td,th{border:1px solid #ccc;padding:3px 8px;text-align:left}"
        "table{border-collapse:collapse;margin:1em 0}</style>",
        "<h1>Falcon Lens eval report</h1>",
        "<p>Generated from the eval artifact; offline T1 + arbiter only. Items not evaluated are listed as such.</p>",
        "<table>",
    ]
    for k in ("created_at", "git_sha", "dataset_hash", "temporal_cut", "temporal_cut_note"):
        parts.append(f"<tr><th>{k}</th><td>{e(str(doc[k]))}</td></tr>")
    for k in ("thresholds", "seeds", "model_ids", "splits_lock"):
        parts.append(f"<tr><th>{k}</th><td><code>{e(json.dumps(doc[k]))}</code></td></tr>")
    parts.append("</table>")
    for split, s in doc["splits"].items():
        parts.append(f"<h2>Split: {e(split)}</h2><p>{e(s['operating_point'])}</p><table>")
        parts.append("<tr><th>metric</th><th>all</th><th>real</th><th>synthetic</th></tr>")
        for name in HEADLINE:
            cells = []
            for grp in ("overall", "real", "synthetic"):
                g = s[grp]
                cells.append(_fmt(g[name]) if name in g else _fmt(g))
            parts.append(f"<tr><th>{name}</th>" + "".join(f"<td>{e(c)}</td>" for c in cells) + "</tr>")
        parts.append("</table>")
        o = s["overall"]
        parts.append(f"<p>n={o['n']} (phishing {o['n_phishing']}, legit {o['n_legit']})</p>")
        for title, key in (
            ("Verified-official", "verified_official"),
            ("Zero-day", "zero_day"),
            ("Latency (ms)", "latency_ms"),
            ("LLM", "llm"),
            ("Routes (cloud vs sovereign)", "routes"),
            ("Dangerous verdict only", "dangerous_only"),
            ("Legit false-warning rate by category", "legit_by_category"),
            ("Ablation (validation)", "ablation"),
        ):
            if key in s:
                parts.append(f"<h3>{title}</h3><pre>{e(json.dumps(s[key], indent=1))}</pre>")
        parts.append("<h3>Reliability</h3><pre>" + e(json.dumps(o["reliability"], indent=1)) + "</pre>")
    parts.append("<h2>Not evaluated</h2><pre>" + e(json.dumps(doc["not_evaluated"], indent=1)) + "</pre>")
    parts.append("<h2>Data notes</h2><pre>" + e(json.dumps(doc["data_notes"], indent=1)) + "</pre>")
    return "\n".join(parts)
