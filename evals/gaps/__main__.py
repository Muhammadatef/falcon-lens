"""``python -m evals.gaps <area> [...]``: write the gap-closing artifacts under ``evals/results/published/<area>/``.

Areas: synthetic, faithfulness, stability, routes, cost, sandbox, brand-new, t3, arabic, all.
The raw runs these read come from ``python -m evals.gaps.jobs`` (see that module); the offline areas
(synthetic, arabic, faithfulness' val/test part) need no model.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evals.gaps import arabic, offline, reports
from evals.gaps.common import envelope, not_evaluated, rate, write_artifact


def sentinel_summary(route: str) -> dict[str, Any]:
    raw = reports.load_json(f"sentinel_{route}")
    if raw is None:
        return not_evaluated(f"sentinel {route} run missing")
    rows = raw["rows"]
    n = len(rows)
    llm_rows = [r for r in rows if r["summary_by"] == "llm"]
    raw_in_llm = sum(r["raw_claims"] for r in llm_rows)
    kept = sum(r["kept_claims"] for r in llm_rows)
    out = {k: v for k, v in raw.items() if k not in ("rows", "router_calls")}
    out["summary_verifier_accept_rate"] = rate(len(llm_rows), n)
    returned = [r for r in rows if r["raw_summary_returned"]]
    out["summary_verifier_accept_rate_among_model_answers"] = rate(len(llm_rows), len(returned))
    out["triage_budget_exhausted_runs"] = rate(sum(1 for r in rows if r["wall_s"] >= 119.9), n)
    out["accept_rate_note"] = (
        "the first rate counts every triage run, so a model that did not answer inside the 120 s triage budget "
        "(common on the shared local GPU) lowers it; the 'among model answers' rate is the verifier's own accept rate"
    )
    out["claims_retained_in_accepted_summaries"] = rate(kept, raw_in_llm)
    out["kept_claims_cite_valid_evidence"] = rate(sum(r["kept_claims_citing_valid_ids"] for r in llm_rows), kept)
    out["claim_to_evidence_coverage_raw_model_output"] = {
        "all_cited_ids_exist": rate(
            sum(r["raw_claims_all_ids_valid"] for r in rows), sum(r["raw_claims"] for r in rows)
        ),
        "at_least_one_cited_id_exists": rate(
            sum(r["raw_claims_some_id_valid"] for r in rows), sum(r["raw_claims"] for r in rows)
        ),
    }
    out["by_incident_type"] = {
        t: rate(
            sum(1 for r in rows if r["incident_type"] == t and r["summary_by"] == "llm"),
            sum(1 for r in rows if r["incident_type"] == t),
        )
        for t in sorted({r["incident_type"] for r in rows})
    }
    calls = raw["router_calls"]
    out["tokens"] = {
        "input": sum(c["input_tokens"] for c in calls),
        "output": sum(c["output_tokens"] for c in calls),
        "calls": len(calls),
        "models": sorted({str(c["model"]) for c in calls}),
        "cloud_provider_calls": sum(c["cloud_provider_calls"] for c in calls),
    }
    out["per_run"] = rows
    return out


def faithfulness() -> dict[str, Any]:
    off = offline.faithfulness_offline()
    body = {
        "user_facing_reasons_template_only": {
            "decision": "L1 decision D3: reasons are catalog templates selected from evidence; no model writes them",
            "offline_val_test_real_items": off,
            "cascade_fixture_verdicts_synthetic": reports.faithfulness_cascade(),
            "offline_note": "the offline val/test pipeline does not add the url.classifier evidence the cascade adds when the fitted T1 model fires, so some suspicious verdicts there carry no reason; in the cascade they do (see cascade_fixture_verdicts_synthetic.verdicts_without_reasons_by_verdict)",  # noqa: E501
            "checks": "R1 cited ids exist in the verdict; R2 text is exactly one catalog template in both languages; R3 the template's claim matches the cited evidence (signal, present, polarity vs verdict, hard-rule tag); R4 generated_by=template, at most 3 reasons",  # noqa: E501
        },
        "sentinel_llm_summaries": {
            "provenance": "synthetic replay fixture (planted Falcon Demo Bank campaign, source=replay), 3 incidents per run",  # noqa: E501
            "local": sentinel_summary("local"),
            "cloud": sentinel_summary("cloud"),
        },
    }
    return envelope(
        "faithfulness",
        scope="explanation faithfulness: template reasons vs evidence (val/test + fixture cascade verdicts) and Sentinel LLM summaries (verifier accept rate, claim->evidence coverage)",  # noqa: E501
        provenance="real (val/test URL items, offline) + synthetic (fixture verdicts, replayed incidents), reported apart",  # noqa: E501
        n={"val": off["val"]["verdicts"], "test": off["test"]["verdicts"]},
        route="none for reasons; local and cloud for Sentinel summaries",
        model_ids={"reasons": "none (templates)", "sentinel": "see sentinel_llm_summaries.<route>.router_calls models"},
        body=body,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.gaps")
    ap.add_argument(
        "area",
        choices=[
            "synthetic",
            "faithfulness",
            "stability",
            "routes",
            "cost",
            "sandbox",
            "brand-new",
            "t3",
            "arabic",
            "all",
        ],
    )
    ap.add_argument("--ingest", type=Path, help="arabic: a filled rating sheet CSV")
    a = ap.parse_args(argv)
    todo = (
        ["synthetic", "faithfulness", "stability", "routes", "cost", "sandbox", "brand-new", "t3", "arabic"]
        if a.area == "all"
        else [a.area]
    )
    for area in todo:
        if area == "synthetic":
            path = write_artifact("synthetic_split", offline.synthetic_split())
        elif area == "faithfulness":
            path = write_artifact("faithfulness", faithfulness())
        elif area == "stability":
            path = write_artifact("stability", reports.stability())
        elif area == "routes":
            path = write_artifact("route_compare", reports.routes())
        elif area == "cost":
            path = write_artifact("cost_per_check", reports.cost())
        elif area == "sandbox":
            path = write_artifact("sandbox_t2", reports.sealed_browser())
        elif area == "brand-new":
            path = write_artifact("brand_new_pages", reports.brand_new())
        elif area == "t3":
            path = write_artifact("t3_investigator", reports.t3())
        else:
            path = write_artifact("arabic_clarity", arabic.report(a.ingest))
        print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
