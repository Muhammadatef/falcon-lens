"""Evals exporter: reads published artifacts and renders fl_eval_* gauges."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("evals_exporter", Path(__file__).parents[1] / "exporter.py")
assert SPEC and SPEC.loader
X = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(X)

PUBLISHED = Path(__file__).parents[3] / "evals" / "results" / "published"


def _w(root: Path, rel: str, doc: object) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_main_artifact_metrics_with_ci_n_and_provenance(tmp_path: Path) -> None:
    _w(
        tmp_path,
        "20261123T000000Z.json",
        {
            "created_at": "2026-11-23T00:00:00Z",
            "git_sha": "abcdef1234567890",
            "metrics": {
                "val.recall": 0.9,
                "val.recall_ci95": [0.8, 0.95],
                "val.n": 100,
                "val.message_path.recall": 0.7,
                "val.message_path.recall_ci95": [0.6, 0.8],
                "val.message_path.n": 400,
            },
        },
    )
    text, n, errors = X.render(tmp_path)
    assert (n, errors) == (1, 0)
    assert (
        'fl_eval_metric{metric="recall",split="val",source="main",artifact="20261123T000000Z",provenance="real"} 0.9'
        in text
    )
    assert (
        'fl_eval_ci_low{metric="recall",split="val",source="main",artifact="20261123T000000Z",provenance="real"} 0.8'
        in text
    )
    assert (
        'fl_eval_n{metric="recall",split="val",source="main",artifact="20261123T000000Z",provenance="real"} 100.0'
        in text
    )
    # message-path numbers are synthetic and use their own n
    assert (
        'metric="message_path.recall",split="val",source="main",artifact="20261123T000000Z",provenance="synthetic"} 0.7'
        in text
    )
    assert 'fl_eval_n{metric="message_path.recall"' in text and "} 400.0" in text
    assert 'fl_eval_artifact_info{source="main",artifact="20261123T000000Z",git_sha="abcdef123456"' in text
    assert 'fl_eval_artifact_latest{source="main",artifact="20261123T000000Z"} 1.0' in text


def test_latest_flag_marks_only_newest_per_source(tmp_path: Path) -> None:
    _w(
        tmp_path,
        "fp_regress/a.json",
        {"created_at": "2026-11-22T00:00:00Z", "n": 10, "false_positive_rate": {"value": 0.3}},
    )
    _w(
        tmp_path,
        "fp_regress/b.json",
        {"created_at": "2026-11-23T00:00:00Z", "n": 10, "false_positive_rate": {"value": 0.2}},
    )
    text, _, _ = X.render(tmp_path)
    assert 'fl_eval_artifact_latest{source="fp_regress",artifact="b"} 1.0' in text
    assert 'fl_eval_artifact_latest{source="fp_regress",artifact="a"}' not in text


def test_fp_regress_serves_web_split(tmp_path: Path) -> None:
    _w(
        tmp_path,
        "fp_regress/x.json",
        {
            "n": 200,
            "false_positive_rate": {"value": 0.285, "ci95": [0.23, 0.345]},
            "by_serves_web": {
                "serves_web_page": {"n": 146, "false_positive_rate": {"value": 0.1644, "ci95": [0.1027, 0.2329]}}
            },
        },
    )
    text, _, _ = X.render(tmp_path)
    assert re.search(r'metric="false_alarm_rate_serves_web",split="heldout",source="fp_regress".* 0.1644', text)
    assert re.search(r'fl_eval_n\{metric="false_alarm_rate_serves_web".* 146.0', text)
    assert re.search(r'fl_eval_ci_high\{metric="false_alarm_rate",.* 0.345', text)


def test_redteam_rate_per_kind_with_wilson_ci(tmp_path: Path) -> None:
    cases = [{"kind": "page", "attack_success": False}] * 9 + [{"kind": "message", "attack_success": False}]
    _w(
        tmp_path,
        "redteam/r.json",
        {"cases_total": 10, "attack_success_count": 0, "attack_success_rate": 0.0, "cases": cases},
    )
    text, _, _ = X.render(tmp_path)
    assert 'metric="harmful_rate",split="all",source="redteam",artifact="r",provenance="synthetic"} 0.0' in text
    assert 'metric="harmful_rate.page"' in text
    lo, hi = X.wilson(0, 10)
    assert lo == 0.0 or abs(lo) < 1e-9
    assert 0.25 < hi < 0.35  # rule-of-three territory for n=10


def test_generic_flatten_for_unknown_layouts_and_provenance_override(tmp_path: Path) -> None:
    _w(
        tmp_path,
        "dspy/d.json",
        {
            "provenance": "synthetic",
            "before": {"f1": {"value": 0.5, "ci95": [0.4, 0.6], "n": 50}},
            "after": {"f1": 0.7},
            "note": "x",
        },
    )
    text, _, _ = X.render(tmp_path)
    assert 'metric="before.f1",split="all",source="dspy",artifact="d",provenance="synthetic"} 0.5' in text
    assert 'metric="after.f1"' in text
    assert "note" not in text


def test_bad_json_counted_and_never_crashes(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    _w(tmp_path, "list.json", [1, 2])
    text, n, errors = X.render(tmp_path)
    assert (n, errors) == (0, 2)
    assert "fl_eval_exporter_errors 2" in text


def test_label_values_are_escaped(tmp_path: Path) -> None:
    _w(tmp_path, "dspy/q.json", {'a"b': {"value": 1.0}})
    text, _, _ = X.render(tmp_path)
    assert 'metric="a\\"b"' in text


def test_committed_published_artifacts_export_without_errors() -> None:
    text, n, errors = X.render(PUBLISHED)
    assert errors == 0 and n >= 4
    assert 'metric="roc_auc",split="val",source="main"' in text
    assert 'metric="false_alarm_rate_serves_web"' in text


def test_missing_dir_is_empty_not_error(tmp_path: Path) -> None:
    text, n, _ = X.render(tmp_path / "nope")
    assert n == 0 and "fl_eval_exporter_artifacts 0" in text


def test_fits_export_only_measured_values_not_configuration(tmp_path: Path) -> None:
    chosen = {
        "fpr_form": 0.0, "recall_form": 0.5, "margin": 0.3, "strong_adj": 1.6, "n_legit": 104, "n_phishing": 142,
    }  # fmt: skip
    doc = {
        "seed": 20261122,
        "split": "val",
        "constraints": {"url_only_dangerous_fpr_max": 0.01},
        "grid": {"margin": [0.0, 0.1]},
        "chosen": chosen,
    }
    _w(tmp_path, "fits/f.json", doc)
    text, _, _ = X.render(tmp_path)
    assert 'metric="fpr_form",split="val",source="fits"' in text and 'metric="recall_form"' in text
    assert 'fl_eval_n{metric="fpr_form"' in text and "} 104.0" in text
    for config in ("seed", "constraints", "margin", "strong_adj", "n_legit", "grid"):
        assert f'metric="{config}' not in text


def test_redteam_summary_exports_answered_and_per_category(tmp_path: Path) -> None:
    cat = {"cases": 38, "harmful": 1, "rate": 0.0263, "ci95": [0.0047, 0.135], "llm_ran": 37, "llm_calls_failed": 0}
    _w(
        tmp_path,
        "redteam/r.json",
        {
            "generated_at": "20261123T143553Z",
            "summary": {
                "overall": {**cat, "cases": 113, "llm_ran": 90, "by_outcome": {"pipeline_error": 1}},
                "by_category": {"message": cat},
            },
        },
    )
    text, _, errors = X.render(tmp_path)
    assert errors == 0
    base = 'split="all",source="redteam",artifact="r",provenance="synthetic"}'
    assert f'fl_eval_metric{{metric="answered",{base} 90.0' in text
    assert f'fl_eval_metric{{metric="answered.message",{base} 37.0' in text
    assert f'fl_eval_metric{{metric="harmful.message",{base} 1.0' in text
    assert f'fl_eval_metric{{metric="outcome.pipeline_error",{base} 1.0' in text
    assert f'fl_eval_ci_high{{metric="harmful_rate.message",{base} 0.135' in text
    # compact YYYYmmddTHHMMSSZ dates are parsed into the artifact timestamp
    ts = re.search(r'fl_eval_artifact_timestamp\{source="redteam",artifact="r"\} (\S+)', text)
    assert ts and float(ts.group(1)) == 1795444553.0


def test_provenance_is_bounded_and_per_row_for_mixed_sources(tmp_path: Path) -> None:
    n = X.normalise_provenance
    assert n("synthetic, single-author, supervisor-audited") == "synthetic"
    assert n("synthetic fixtures (Falcon Demo Bank)") == "fixture"
    assert n("real (val/test) + synthetic (fixtures)") == "mixed"
    assert n("real") == "real" and n(None) == "unknown" and n("whatever") == "unknown"
    _w(
        tmp_path,
        "synthetic_split/s.json",
        {
            "created_at": "2026-11-23T14:00:00Z",
            "provenance": "real (manifest items) and synthetic (fixtures), reported side by side",
            "real_items_scored": {"fpr_warning": {"value": 0.1, "ci95": [0.05, 0.2], "n": 80}},
            "synthetic_messages_scored": {"fpr_warning": {"value": 0.0, "n": 8}},
        },
    )
    text, _, _ = X.render(tmp_path)
    real = 'metric="real_items_scored.fpr_warning",split="all",source="synthetic_split",artifact="s",provenance="real"'
    synth = (
        'metric="synthetic_messages_scored.fpr_warning",split="all",source="synthetic_split",'
        'artifact="s",provenance="synthetic"'
    )
    assert real in text
    assert synth in text


def test_dspy_adopted_flag_and_info_labels(tmp_path: Path) -> None:
    _w(
        tmp_path,
        "dspy/extractor_x.json",
        {
            "role": "extractor",
            "route": "local",
            "synthetic_data": True,
            "adopted": False,
            "before_val": {"mean": 0.74, "n": 12},
            "after_val": {"mean": 0.77, "n": 12},
        },
    )
    text, _, _ = X.render(tmp_path)
    assert 'metric="adopted",split="all",source="dspy",artifact="extractor_x",provenance="synthetic"} 0.0' in text
    assert 'metric="before_val.mean",split="all",source="dspy"' in text
    assert 'role="extractor",route="local"' in text


def test_fp_regress_extras_and_set_label(tmp_path: Path) -> None:
    grp = {
        "n": 141,
        "false_dangerous": 1,
        "partial_reads": 10,
        "false_positive_rate": {"value": 0.15, "ci95": [0.1, 0.2]},
    }
    _w(
        tmp_path,
        "fp_regress/f.json",
        {
            "set": "heldout_legit_2.csv",
            "created_at": "2026-11-23T16:31:04Z",
            "n": 200,
            "false_dangerous": 1,
            "false_positive_rate": {"value": 0.265, "ci95": [0.2, 0.3]},
            "counts": {"suspicious": 52},
            "by_serves_web": {"serves_web_page": grp},
        },
    )
    text, _, _ = X.render(tmp_path)
    assert 'metric="false_dangerous",split="heldout",source="fp_regress",artifact="f",provenance="real"} 1.0' in text
    assert 'metric="partial_reads_serves_web"' in text
    assert 'metric="verdict.suspicious"' in text
    assert 'set="heldout_legit_2.csv"' in text


def test_published_artifacts_every_series_has_bounded_provenance() -> None:
    text, count, errors = X.render(PUBLISHED)
    assert count > 20 and errors == 0
    provs = set(re.findall(r'^fl_eval_metric\{.*provenance="([^"]*)"\}', text, re.M))
    assert provs <= set(X.PROVENANCE_VALUES)
    series = [ln for ln in text.splitlines() if ln.startswith("fl_eval_metric{")]
    for source in (
        "redteam",
        "route_compare",
        "cost_per_check",
        "dspy",
        "message_text",
        "synthetic_split",
        "t3_investigator",
    ):
        assert any(f'source="{source}"' in ln for ln in series), source
    assert len(set(re.findall(r'^fl_eval_metric\{metric="([^"]*)"', text, re.M))) < 900
