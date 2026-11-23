"""Aggregators: raw cascade runs (``work/gaps/raw``) -> published area reports.

Every number is computed from the raw run files; nothing is typed here. Prices (``PRICES``) are the one external
input: Anthropic list prices read from the official pricing page on the date recorded next to them.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from typing import Any

from evals.gaps import corpus
from evals.gaps.common import PUBLISHED, envelope, mean_ci, not_evaluated, pctl, rate
from evals.gaps.faithfulness import check_doc, mutation_report, summarise
from evals.gaps.jobs import RAW
from falcon_core.signals.url.canonical import canonicalize

RANK = {"no_warning_signs": 0, "suspicious": 1, "dangerous": 2}
ITEMS = {i.item_id: i for i in [*corpus.ITEMS, *corpus.new_lookalike_set()]}

# Anthropic list prices, USD per million tokens. Source: https://platform.claude.com/docs/en/about-claude/pricing
# (read 2026-11-23). Haiku 5.5 price applies to prompts up to 100,000 tokens; all calls here are far below that.
PRICES_SOURCE = "hxxps://platform[.]claude[.]com/docs/en/about-claude/pricing"  # defanged; DECISIONS.md has the link
PRICES_DATE = "2026-11-23"
PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write_5m": 0.125, "cache_read": 0.01},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write_5m": 2.50, "cache_read": 0.10},
}


def load_runs(name: str) -> list[dict[str, Any]]:
    p = RAW / f"{name}.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json(name: str) -> dict[str, Any] | None:
    p = RAW / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def meta(name: str) -> dict[str, Any]:
    p = RAW / f"{name}.meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


def verdict_of(r: dict[str, Any]) -> str | None:
    return (r.get("doc") or {}).get("verdict")


def tier_of(r: dict[str, Any]) -> str | None:
    return (r.get("doc") or {}).get("tier_reached")


def call_cost(c: dict[str, Any]) -> float | None:
    p = PRICES.get(str(c.get("model")))
    if p is None or c.get("route") != "cloud":
        return None
    return (
        c["input_tokens"] * p["input"]
        + c["output_tokens"] * p["output"]
        + c.get("cache_write_tokens", 0) * p["cache_write_5m"]
        + c.get("cache_read_tokens", 0) * p["cache_read"]
    ) / 1_000_000


def _ok_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in runs if r["ok"] and r.get("doc")]


# ---------------------------------------------------------------------------------------------- stability


def stability() -> dict[str, Any]:
    local = load_runs("local_s12")
    det = load_runs("noai_s12")
    m = meta("local_s12")

    def block(runs: list[dict[str, Any]]) -> dict[str, Any]:
        by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in runs:
            by_item[r["item_id"]].append(r)
        full = {k: v for k, v in by_item.items() if len(v) >= 3}
        rows = []
        agree_exact = agree_warn = 0
        pair_agree = pair_total = 0
        var_by_tier: dict[str, list[float]] = defaultdict(list)
        sd_by_tier: dict[str, list[float]] = defaultdict(list)
        for iid, rs in sorted(full.items()):
            ok = [r for r in rs if r["ok"] and r.get("doc")]
            verdicts = [verdict_of(r) for r in ok]
            scores = [float((r["doc"] or {}).get("risk_score", 0)) for r in ok]
            tiers = [tier_of(r) for r in ok]
            n_fail = len(rs) - len(ok)
            complete = n_fail == 0
            same_label = complete and len(set(verdicts)) == 1
            same_warn = complete and len({v != "no_warning_signs" for v in verdicts}) == 1
            agree_exact += int(same_label)
            agree_warn += int(same_warn)
            for i in range(len(verdicts)):
                for j in range(i + 1, len(verdicts)):
                    pair_total += 1
                    pair_agree += int(verdicts[i] == verdicts[j])
            modal_tier = Counter(tiers).most_common(1)[0][0] if tiers else "none"
            if len(scores) >= 2:
                var_by_tier[str(modal_tier)].append(statistics.pvariance(scores))
                sd_by_tier[str(modal_tier)].append(statistics.pstdev(scores))
            rows.append(
                {
                    "item_id": iid,
                    "kind": ITEMS[iid].kind,
                    "runs_ok": len(ok),
                    "runs_failed": n_fail,
                    "failure_modes": sorted({str(r["error"])[:60] for r in rs if not r["ok"]}),
                    "verdicts": verdicts,
                    "tiers": tiers,
                    "scores": scores,
                    "label_stable": same_label,
                    "score_range": (max(scores) - min(scores)) if scores else None,
                    "llm_calls_per_run": [len(r["calls"]) for r in rs],
                }
            )
        n_items = len(full)
        completed = [r for r in rows if r["runs_failed"] == 0]
        return {
            "items": n_items,
            "items_with_all_three_runs_completed": len(completed),
            "label_agreement_among_items_with_three_completed_runs": rate(
                sum(1 for r in completed if r["label_stable"]), len(completed)
            ),
            "runs_total": len(runs),
            "runs_failed": sum(1 for r in runs if not r["ok"]),
            "label_agreement_all_three_identical": rate(agree_exact, n_items),
            "warning_vs_none_agreement_all_three": rate(agree_warn, n_items),
            "pairwise_label_agreement": rate(pair_agree, pair_total),
            "score_variance_by_final_tier": {
                t: {
                    "items": len(v),
                    "mean_within_item_variance": round(statistics.fmean(v), 4),
                    "mean_within_item_sd": round(statistics.fmean(sd_by_tier[t]), 4),
                    "max_within_item_sd": round(max(sd_by_tier[t]), 4),
                }
                for t, v in sorted(var_by_tier.items())
            },
            "per_item": rows,
        }

    # what the AI layers changed: every completed AI-on run against the AI-off verdict of the same item
    off_by_item = {r["item_id"]: r for r in det if r["repeat"] == 0 and r["ok"] and r.get("doc")}
    pairs = [(r, off_by_item[r["item_id"]]) for r in _ok_runs(local) if r["item_id"] in off_by_item]
    contribution: dict[str, Any] = {
        "completed_ai_on_runs_compared": len(pairs),
        "label_differs_from_ai_off": rate(sum(1 for a, b in pairs if verdict_of(a) != verdict_of(b)), len(pairs)),
        "score_differs_from_ai_off": rate(
            sum(1 for a, b in pairs if a["doc"]["risk_score"] != b["doc"]["risk_score"]), len(pairs)
        ),
        "score_abs_diff": mean_ci(
            [abs(float(a["doc"]["risk_score"]) - float(b["doc"]["risk_score"])) for a, b in pairs]
        ),
        "llm_calls_answered": rate(
            sum(1 for a, _ in pairs if any(c["status"] in ("ok", "repaired") for c in a["calls"])), len(pairs)
        ),
        "reading": "the model only adds risk-side evidence next to the deterministic evidence; zero differences mean the "  # noqa: E501
        "arbiter reached the same score with and without the AI layers on these fixtures",
    }
    body: dict[str, Any] = {
        "ai_layers_contribution_local": contribution,
        "ai_layers_on": block(local) if local else not_evaluated("local_s12 run missing"),
        "deterministic_control_ai_off": block(det) if det else not_evaluated("control run missing"),
        "definition": "3 repeats of the shipped cascade on the same 12 synthetic fixture inputs, extractor + investigator on; "  # noqa: E501
        "a run that crashed or timed out counts as a failed run and makes that item 'not stable'.",
        "caveat": "fixture-backed renderer, stub DNS, no network signals; the local model shares the GPU with other jobs, so "  # noqa: E501
        "timeouts are possible and are counted, not hidden.",
    }
    return envelope(
        "stability",
        scope="repeat-run stability of the shipped cascade, local (sovereign) route, 12 fixtures x 3 runs",
        provenance="synthetic fixtures (Falcon Demo Bank, .test hosts), offline substitutes for sandbox and network",
        n={"items": 12, "runs_per_item": 3},
        route="local",
        model_ids={"local": m.get("local_model"), "t1": "t1_hgb fitted" if m.get("t1_fitted") else "draft"},
        body=body,
    )


# ---------------------------------------------------------------------------------------------- routes


def _lat(runs: list[dict[str, Any]]) -> dict[str, Any]:
    v = [float(r["ms"]) for r in runs if r["ok"]]
    return {"n": len(v), "p50_ms": pctl(v, 50), "p95_ms": pctl(v, 95), "mean": mean_ci(v)}


def _calls(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for r in runs for c in r["calls"]]


def _tok(calls: list[dict[str, Any]]) -> dict[str, Any]:
    by_role: dict[str, dict[str, Any]] = {}
    for role in sorted({c["role"] for c in calls}):
        cs = [c for c in calls if c["role"] == role]
        by_role[role] = {
            "calls": len(cs),
            "input_tokens": sum(c["input_tokens"] for c in cs),
            "output_tokens": sum(c["output_tokens"] for c in cs),
            "cache_read_tokens": sum(c["cache_read_tokens"] for c in cs),
            "cache_write_tokens": sum(c["cache_write_tokens"] for c in cs),
            "latency_ms_p50": pctl([float(c["ms"]) for c in cs], 50),
            "latency_ms_p95": pctl([float(c["ms"]) for c in cs], 95),
            "models": sorted({str(c["model"]) for c in cs}),
            "statuses": dict(Counter(c["status"] for c in cs)),
            "fell_back": sum(1 for c in cs if c["fell_back"]),
        }
    return by_role


def cloud_usage() -> dict[str, Any]:
    """Cloud provider calls spent per job, from each job's own router records (cap 300 across all)."""
    parts: dict[str, int] = {}
    for name in ("cloud_all", "cloud_t3extra"):
        runs = load_runs(name)
        parts[f"cascade:{name}"] = sum(c["cloud_provider_calls"] for r in runs for c in r["calls"])
    ex = load_json("extractor_cloud")
    parts["extractor_eval"] = int(ex["cloud_provider_calls"]) if ex else 0
    sn = load_json("sentinel_cloud")
    parts["sentinel_replay"] = sum(c["cloud_provider_calls"] for c in sn["router_calls"]) if sn else 0
    total = sum(parts.values())
    return {"by_job": parts, "total": total, "cap": 300, "within_cap": total <= 300}


def routes() -> dict[str, Any]:
    loc = _ok_by_item(load_runs("local_s12"), repeat=0)
    loc.update(_ok_by_item(load_runs("local_rest"), repeat=0))
    cl = _ok_by_item(load_runs("cloud_all"), repeat=0)
    common = sorted(set(loc) & set(cl))
    same = sum(1 for i in common if verdict_of(loc[i]) == verdict_of(cl[i]))
    same_w = sum(
        1 for i in common if (verdict_of(loc[i]) != "no_warning_signs") == (verdict_of(cl[i]) != "no_warning_signs")
    )
    diffs = [abs(float(loc[i]["doc"]["risk_score"]) - float(cl[i]["doc"]["risk_score"])) for i in common]
    same_tier = sum(1 for i in common if tier_of(loc[i]) == tier_of(cl[i]))

    def acc(sel: dict[str, dict[str, Any]]) -> dict[str, Any]:
        ph = [i for i in sel if ITEMS[i].phish]
        lg = [i for i in sel if not ITEMS[i].phish]
        warn = lambda i: verdict_of(sel[i]) != "no_warning_signs"  # noqa: E731
        return {
            "n": len(sel),
            "recall_warning_on_phishing_fixtures": rate(sum(warn(i) for i in ph), len(ph)),
            "warning_rate_on_benign_fixtures": rate(sum(warn(i) for i in lg), len(lg)),
            "dangerous_on_phishing_fixtures": rate(sum(verdict_of(sel[i]) == "dangerous" for i in ph), len(ph)),
        }

    ext = {r: load_json(f"extractor_{r}") for r in ("local", "cloud")}
    ext_art = {
        r: ({k: v for k, v in d.items() if k != "rows"} if d else not_evaluated(f"extractor_{r} run missing"))
        for r, d in ext.items()
    }
    ext_agree = None
    if ext["local"] and ext["cloud"]:
        a = {r["item_id"]: r["got"] for r in ext["local"]["rows"]}
        b = {r["item_id"]: r["got"] for r in ext["cloud"]["rows"]}
        both = [i for i in a if i in b and a[i] and b[i]]
        ext_agree = {
            "items_with_both_routes_extracted": len(both),
            "brand": rate(sum(a[i]["brand"] == b[i]["brand"] for i in both), len(both)),
            "script_category": rate(sum(a[i]["script"] == b[i]["script"] for i in both), len(both)),
            "language": rate(sum(a[i]["language"] == b[i]["language"] for i in both), len(both)),
            "requested_data": rate(sum(a[i]["requested"] == b[i]["requested"] for i in both), len(both)),
        }
    loc_all = [r for r in load_runs("local_s12") + load_runs("local_rest") if r["repeat"] == 0]
    cl_all = load_runs("cloud_all")
    body = {
        "same_inputs": {"n_common_items": len(common), "items": common},
        "verdict_agreement": {
            "exact_label": rate(same, len(common)),
            "warning_vs_none": rate(same_w, len(common)),
            "same_final_tier": rate(same_tier, len(common)),
            "risk_score_abs_diff": mean_ci(diffs),
            "disagreements": [
                {"item_id": i, "local": verdict_of(loc[i]), "cloud": verdict_of(cl[i])}
                for i in common
                if verdict_of(loc[i]) != verdict_of(cl[i])
            ],
        },
        "accuracy_vs_author_labels": {
            "local": acc({i: loc[i] for i in common}),
            "cloud": acc({i: cl[i] for i in common}),
        },
        "cascade_latency": {
            "local": _lat(loc_all),
            "cloud": _lat(cl_all),
            "caveat": "local latency includes waiting on a shared GPU queue (other jobs ran on the same model); read it as an upper bound, not as the model's speed",  # noqa: E501
        },
        "llm_calls": {"local": _tok(_calls(loc_all)), "cloud": _tok(_calls(cl_all))},
        "runs_failed": {
            "local": sum(1 for r in loc_all if not r["ok"]),
            "cloud": sum(1 for r in cl_all if not r["ok"]),
        },
        "extractor_field_accuracy": ext_art,
        "extractor_route_agreement": ext_agree or not_evaluated("needs both extractor runs"),
        "cloud_calls_used": cloud_usage(),
    }
    return envelope(
        "route_compare",
        scope="same synthetic fixtures through the cloud (Anthropic API) and local (sovereign, Ollama) routes of the shipped cascade",  # noqa: E501
        provenance="synthetic fixtures (Falcon Demo Bank, .test hosts); offline sandbox and network substitutes",
        n={"cascade_items_both_routes": len(common), "extractor_items": len(corpus.ITEMS)},
        route="local+cloud",
        model_ids={
            "local": meta("local_s12").get("local_model"),
            "cloud": meta("cloud_all").get("cloud_models"),
        },
        body=body,
        notes=["Labels are the author's, set before any model ran; items are not tuned after seeing results."],
    )


def _ok_by_item(runs: list[dict[str, Any]], repeat: int) -> dict[str, dict[str, Any]]:
    return {r["item_id"]: r for r in runs if r["repeat"] == repeat and r["ok"] and r.get("doc")}


# ---------------------------------------------------------------------------------------------- cost


def cost() -> dict[str, Any]:
    cl = load_runs("cloud_all") + load_runs("cloud_t3extra")
    per_check: list[float] = []
    by_kind: dict[str, list[float]] = defaultdict(list)
    by_tier: dict[str, list[float]] = defaultdict(list)
    router_cost: list[float] = []
    tokens_in: list[float] = []
    tokens_out: list[float] = []
    for r in cl:
        if not r["ok"]:
            continue
        cs = [call_cost(c) for c in r["calls"]]
        usd = sum(x for x in cs if x is not None)
        per_check.append(usd)
        by_kind[ITEMS[r["item_id"]].kind].append(usd)
        by_tier[str(tier_of(r))].append(usd)
        router_cost.append(sum(c["cost_usd"] for c in r["calls"]))
        tokens_in.append(sum(c["input_tokens"] + c["cache_read_tokens"] + c["cache_write_tokens"] for c in r["calls"]))
        tokens_out.append(sum(c["output_tokens"] for c in r["calls"]))
    loc = [r for r in load_runs("local_s12") + load_runs("local_rest") if r["ok"]]

    def _usd(c: dict[str, Any], model: str | None = None) -> float:
        p = PRICES.get(str(model or c.get("model")))
        if p is None:
            return 0.0
        return (
            c["input_tokens"] * p["input"]
            + c["output_tokens"] * p["output"]
            + c.get("cache_write_tokens", 0) * p["cache_write_5m"]
            + c.get("cache_read_tokens", 0) * p["cache_read"]
        ) / 1_000_000

    ex = load_json("extractor_cloud")
    sn = load_json("sentinel_cloud")
    spend = (
        sum(call_cost(c) or 0.0 for r in cl for c in r["calls"])
        + (sum(_usd(r, ex["model"]) for r in ex["rows"]) if ex else 0.0)
        + (sum(call_cost(c) or 0.0 for c in sn["router_calls"]) if sn else 0.0)
    )
    body = {
        "total_spend_usd": {
            "value": round(spend, 4),
            "method": "all cloud calls of this evaluation (cascade, extractor eval, sentinel replay): logged tokens x recorded prices",  # noqa: E501
        },
        "prices": {
            "source": PRICES_SOURCE,
            "read_on": PRICES_DATE,
            "usd_per_mtok": PRICES,
            "tier_note": "Haiku 5.5 up to 100k-token prompts; all calls are far below",
        },
        "cloud_route": {
            "checks": len(per_check),
            "usd_per_check": mean_ci(per_check),
            "usd_per_check_p95": pctl(per_check, 95),
            "usd_per_check_by_input_kind": {k: mean_ci(v) for k, v in sorted(by_kind.items())},
            "usd_per_check_by_final_tier": {k: mean_ci(v) for k, v in sorted(by_tier.items())},
            "tokens_per_check_input": mean_ci(tokens_in),
            "tokens_per_check_output": mean_ci(tokens_out),
            "usd_per_1000_checks_at_mean": round(1000 * (statistics.fmean(per_check) if per_check else 0.0), 4),
            "cross_check_router_accounting_usd_per_check": mean_ci(router_cost),
            "method": "tokens actually used per check (router usage, all roles) x list prices above",
        },
        "local_route": {
            "marginal_api_cost_usd_per_check": 0.0,
            "checks": len(loc),
            "tokens_per_check_input": mean_ci([float(sum(c["input_tokens"] for c in r["calls"])) for r in loc]),
            "tokens_per_check_output": mean_ci([float(sum(c["output_tokens"] for c in r["calls"])) for r in loc]),
            "energy": not_evaluated(
                "electricity / GPU energy was not measured; local is zero marginal API cost, not zero cost"
            ),
        },
        "excluded": "infrastructure, hosting, bandwidth and the deterministic tiers (no per-call cost)",
    }
    return envelope(
        "cost_per_check",
        scope="AI cost per check from tokens actually used on the synthetic fixture corpus, cloud route; local route zero marginal API cost",  # noqa: E501
        provenance="synthetic fixtures; cost depends on prompt sizes of this corpus (short pages and messages)",
        n={"cloud_checks": len(per_check), "local_checks": len(loc)},
        route="cloud (priced) + local (zero marginal)",
        model_ids={"cloud": meta("cloud_all").get("cloud_models"), "local": meta("local_s12").get("local_model")},
        body=body,
    )


# ---------------------------------------------------------------------------------------------- T2 / new pages


def _stage(r: dict[str, Any], tier: str) -> str | None:
    docs = [e for e in r["emitted"] if e["tier"] == tier]
    return docs[-1]["verdict"] if docs else None


def _h1(r: dict[str, Any]) -> bool:
    return any(e.get("hard_rule") == "H1" for e in (r.get("doc") or {}).get("evidence", []))


def sealed_browser() -> dict[str, Any]:
    arts = []
    skipped: list[str] = []
    loaded = [(f, json.loads(f.read_text())) for f in (PUBLISHED / "fp_regress").glob("*.json")]
    for f, d in sorted(loaded, key=lambda fd: str(fd[1].get("created_at"))):
        if "items" not in d:
            skipped.append(f.name)
            continue
        items = d["items"]
        web = [i for i in items if str(i.get("serves_web")) == "1"]
        reached = [i for i in web if i["tier"] in ("T2", "T3")]
        clean = [i for i in reached if not i["degraded_reasons"]]
        attempted = [i for i in items if i["tier"] in ("T2", "T3")]
        att_reasons: Counter[str] = Counter(r for i in attempted for r in i["degraded_reasons"])
        arts.append(
            {
                "artifact": f.name,
                "t2_attempted_all_items": len(attempted),
                "t2_render_clean_of_attempted": rate(
                    sum(1 for i in attempted if not i["degraded_reasons"]), len(attempted)
                ),
                "t2_degraded_of_attempted": rate(sum(1 for i in attempted if i["degraded_reasons"]), len(attempted)),
                "t2_degraded_reasons_of_attempted": dict(att_reasons),
                "t2_outcome_of_attempted": {
                    "clean": rate(sum(1 for i in attempted if not i["degraded_reasons"]), len(attempted)),
                    "partial_render": rate(
                        sum(1 for i in attempted if any(r.startswith("partial_render") for r in i["degraded_reasons"])),
                        len(attempted),
                    ),
                    "sandbox_unavailable": rate(
                        sum(
                            1
                            for i in attempted
                            if any(r.startswith("sandbox_unavailable") for r in i["degraded_reasons"])
                        ),
                        len(attempted),
                    ),
                    "not_rendered": rate(
                        sum(1 for i in attempted if any(r.startswith("not_rendered") for r in i["degraded_reasons"])),
                        len(attempted),
                    ),
                    "note": "an item can carry several reasons; the rows are not exclusive",
                },
                "tier_attempt_note": "attempted = verdict ended at T2 or T3; T1 exits never opened a page",
                "git_sha": d["git_sha"],
                "n": d["n"],
                "serves_web_pages": len(web),
                "t2_reached_of_web": rate(len(reached), len(web)),
                "t2_render_clean_of_web": rate(len(clean), len(web)),
                "t2_degraded_of_web": rate(sum(1 for i in web if i["degraded_reasons"]), len(web)),
                "degraded_reasons_all_items": d["degraded_reasons"],
                "by_tier_all_items": d["by_tier"],
                "false_positive_rate_all_items": d["false_positive_rate"],
                "no_web_host_items": d["by_serves_web"].get("no_web_host", {}).get("n"),
            }
        )
    # T2 contribution on the fixtures, offline renderer: verdict at the end of T1 vs the final verdict
    contrib: dict[str, Any] = {}
    for name in ("new_noai", "cloud_all"):
        runs = [r for r in _ok_runs(load_runs(name)) if ITEMS[r["item_id"]].kind == "page"]
        ph = [r for r in runs if ITEMS[r["item_id"]].phish]
        lg = [r for r in runs if not ITEMS[r["item_id"]].phish]
        t1 = lambda r: _stage(r, "T1")  # noqa: E731
        contrib[name] = {
            "pages": len(runs),
            "phishing_fixtures": len(ph),
            "benign_fixtures": len(lg),
            "recall_warning_after_T1": rate(sum(t1(r) not in (None, "no_warning_signs") for r in ph), len(ph)),
            "recall_warning_after_T2": rate(sum(verdict_of(r) != "no_warning_signs" for r in ph), len(ph)),
            "dangerous_after_T1": rate(sum(t1(r) == "dangerous" for r in ph), len(ph)),
            "dangerous_after_T2": rate(sum(verdict_of(r) == "dangerous" for r in ph), len(ph)),
            "benign_warned_after_T1": rate(sum(t1(r) not in (None, "no_warning_signs") for r in lg), len(lg)),
            "benign_warned_after_T2": rate(sum(verdict_of(r) != "no_warning_signs" for r in lg), len(lg)),
            "label_changed_by_T2": rate(
                sum(1 for r in runs if t1(r) is not None and t1(r) != verdict_of(r)), len(runs)
            ),
        }
    from evals.common import private_dir

    snap_dir = private_dir() / "snapshots"
    snap_files = [f for f in snap_dir.rglob("*") if f.is_file()] if snap_dir.exists() else []
    snap_ext = dict(Counter(f.suffix.lower() for f in snap_files))
    body = {
        "real_site_render_health_held_out_legit": {
            "what": "live running stack (real Playwright sandbox) on 200 held-out legitimate domains; render success and degraded rates only",  # noqa: E501
            "artifacts": arts,
            "headline": arts[-1] if arts else not_evaluated("no fp_regress artifact"),
            "artifacts_without_per_item_rows_skipped": skipped,
            "read_with": "degraded = the page could not be fully checked (timeout, DNS, blocked, render failure); it is a coverage gap, not a detection result",  # noqa: E501
        },
        "t2_contribution_on_fixtures_offline_renderer": {
            "provenance": "synthetic fixtures; fixture-backed renderer (html to SandboxFeatures), NOT the Playwright sandbox",  # noqa: E501
            **contrib,
        },
        "phishing_side_t2_recall": not_evaluated(
            "needs labelled phishing page snapshots; data/private holds only unlabelled screenshots (no page DOM, no labels), and live visits to phishing pages are out of scope (defensive-only rules)"  # noqa: E501
        ),
        "private_snapshot_inventory": {
            "files_by_extension": snap_ext,
            "labelled_phishing_dom_snapshots": sum(
                v for k, v in snap_ext.items() if k in (".html", ".htm", ".mhtml", ".json")
            ),
            "note": "only unlabelled screenshots are present; none were used",
        },
    }
    return envelope(
        "sandbox_t2",
        scope="T2 sealed-browser layer: real-site render health on held-out legit domains (recorded runs) + T2 contribution on fixtures",  # noqa: E501
        provenance="real (held-out legit domains, recorded fp_regress runs) and synthetic (fixtures), kept apart",
        n={"fp_regress_latest_n": arts[-1]["n"] if arts else 0},
        route="none (deterministic T2 signals; model not involved in these figures)",
        model_ids={"llm": "none"},
        body=body,
    )


def brand_new() -> dict[str, Any]:
    runs = _ok_runs(load_runs("new_noai"))
    groups = {
        "new_lookalike_brand_pages": [r for r in runs if "new_lookalike" in ITEMS[r["item_id"]].tags],
        "new_generic_credential_pages": [r for r in runs if "new_generic" in ITEMS[r["item_id"]].tags],
        "benign_controls_novel_hosts": [r for r in runs if "new_benign" in ITEMS[r["item_id"]].tags],
        "official_control": [r for r in runs if "official" in ITEMS[r["item_id"]].tags],
    }
    out: dict[str, Any] = {}
    for g, rs in groups.items():
        n = len(rs)
        out[g] = {
            "n": n,
            "warning_after_T1": rate(sum(_stage(r, "T1") not in (None, "no_warning_signs") for r in rs), n),
            "warning_final": rate(sum(verdict_of(r) != "no_warning_signs" for r in rs), n),
            "dangerous_final": rate(sum(verdict_of(r) == "dangerous" for r in rs), n),
            "h1_fired": rate(sum(_h1(r) for r in rs), n),
            "verdicts": dict(Counter(verdict_of(r) for r in rs)),
        }
    kinds = Counter(
        t for r in groups["new_lookalike_brand_pages"] for t in ITEMS[r["item_id"]].tags if t != "new_lookalike"
    )
    per_kind = {}
    for k in kinds:
        rs = [r for r in groups["new_lookalike_brand_pages"] if k in ITEMS[r["item_id"]].tags]
        per_kind[k] = {"n": len(rs), "dangerous_final": rate(sum(verdict_of(r) == "dangerous" for r in rs), len(rs))}
    body = {
        "definition": "a page on a host that is in no feed, no training data and no brand registry entry, imitating the invented "  # noqa: E501
        "Falcon Demo Bank (or asking for credentials generically); detection = warning (suspicious/dangerous), "
        "dangerous = H1 brand mismatch + credential form.",
        "groups": out,
        "lookalike_by_pattern": per_kind,
        "not_in_any_feed": "OpenPhish mirror is an empty in-memory set in this run and reputation lookups are offline: no item can hit a blocklist, so detection here is by construction independent of feeds",  # noqa: E501
        "ai_layers": "off in this run (deterministic cascade: T0, T1 + fitted classifier, T2 page signals, arbiter)",
        "caveat": ".test hosts raise the URL-only prior (every .test page, including benign ones, is warned at T1); read warning rates together with the benign-control row, and treat 'dangerous' (H1) as the discriminating figure",  # noqa: E501
        "per_item": [
            {
                "item_id": r["item_id"],
                "tags": list(ITEMS[r["item_id"]].tags),
                "after_T1": _stage(r, "T1"),
                "final": verdict_of(r),
                "h1": _h1(r),
            }
            for r in runs
        ],
    }
    return envelope(
        "brand_new_pages",
        scope="detection of brand-new lookalike fixtures on never-seen hosts (deterministic path), synthetic only",
        provenance="synthetic (invented Falcon Demo Bank lookalikes on .test hosts generated 2026-11-23); fixture-backed renderer",  # noqa: E501
        n={k: v["n"] for k, v in out.items()},
        route="none",
        model_ids={"llm": "off", "t1": "t1_hgb fitted"},
        body=body,
    )


# ---------------------------------------------------------------------------------------------- T3


def _target_ok(value: str, allowed: set[str]) -> bool:
    for u in (value, f"https://{value}/"):
        c = canonicalize(u)
        if c.ok and (c.registrable or c.host_ascii) in allowed:
            return True
    return False


def t3() -> dict[str, Any]:
    sources = {"cloud": ["cloud_all", "cloud_t3extra"], "local": ["local_s12", "local_rest"]}
    out: dict[str, Any] = {}
    for route, names in sources.items():
        runs = [r for n in names for r in _ok_runs(load_runs(n))]
        reached = [r for r in runs if any(e["tier"] == "T3" for e in r["emitted"])]
        forb = 0
        calls_per: list[float] = []
        changed = 0
        score_deltas: list[float] = []
        stop_reasons: Counter[str] = Counter()
        up = down = 0
        rows = []
        for r in reached:
            item = ITEMS[r["item_id"]]
            allowed = {canonicalize(item.url or "").registrable or ""} if item.url else set()
            bad = [t for t in r["tool_calls"] if not _target_ok(str(t["arg"]), allowed)]
            forb += int(bool(bad))
            tr = (r["doc"] or {}).get("trace") or []
            t3_line = next((s["summary"] for s in tr if s.get("name") == "T3"), "")
            n_calls = sum(1 for s in tr if s.get("kind") == "tool")
            calls_per.append(float(n_calls))
            if "stopped (" in t3_line:
                stop_reasons[t3_line.split("stopped (")[1].split(")")[0]] += 1
            else:
                stop_reasons["investigator_unavailable"] += 1
            before = _stage(r, "T2")
            after = verdict_of(r)
            changed += int(before != after)
            up += int(before is not None and RANK[str(after)] > RANK[before])
            down += int(before is not None and RANK[str(after)] < RANK[before])
            score_deltas.append(
                float(r["doc"]["risk_score"]) - float(next(e["score"] for e in r["emitted"] if e["tier"] == "T2"))
            )
            rows.append(
                {
                    "item_id": r["item_id"],
                    "repeat": r["repeat"],
                    "T2": before,
                    "final": after,
                    "tool_calls": n_calls,
                    "forbidden_tool_calls": len(bad),
                    "stop": t3_line[:80],
                }
            )
        out[route] = {
            "checks_run": len(runs),
            "reached_T3": rate(len(reached), len(runs)),
            "forbidden_tool_call_rate": rate(forb, len(reached)) if reached else not_evaluated("no run reached T3"),
            "tool_calls_per_investigation": mean_ci(calls_per),
            "max_tool_calls_observed": max(calls_per) if calls_per else None,
            "label_changed_vs_no_T3": rate(changed, len(reached)) if reached else not_evaluated("no run reached T3"),
            "label_raised": up,
            "label_lowered": down,
            "score_delta_vs_T2": mean_ci(score_deltas),
            "stop_reasons": dict(stop_reasons),
            "rows": rows,
        }
    from falcon_core.agent import investigator as inv_mod

    caps = {
        "max_tool_calls": inv_mod.MAX_TOOL_CALLS,
        "time_budget_s": inv_mod.TIME_BUDGET_S,
        "output_token_budget": inv_mod.OUTPUT_TOKEN_BUDGET,
    }
    for rt in out.values():
        mx = rt["max_tool_calls_observed"]
        rt["step_budget_adherence"] = (
            {"cap": caps["max_tool_calls"], "max_observed": mx, "within_cap": mx <= caps["max_tool_calls"]}
            if mx is not None
            else not_evaluated("no run reached T3")
        )
    body = {
        "by_route": out,
        "definition": "T3 = the investigator ran (uncertain band, no hard rule, page rendered). 'no-T3' is the same run's T2 document emitted just before the investigator. "  # noqa: E501
        "A forbidden tool call is a tool target outside the registrable domain of the input URL (ProvenanceRule), checked on the recorded calls.",  # noqa: E501
        "shipped_caps": caps,
        "tools_backend": "offline: the tool backends return no network data in this run, so T3 evidence additions are limited; this measures behaviour (budget, provenance), not the value of live lookups",  # noqa: E501
    }
    return envelope(
        "t3_investigator",
        scope="the AI investigator (T3) on fixtures that truly reach the uncertain band",
        provenance="synthetic fixtures (Falcon Demo Bank / invented club pages, .test hosts); offline tool backends",
        n={r: out[r]["reached_T3"]["k"] if isinstance(out[r]["reached_T3"], dict) else 0 for r in out},
        route="local + cloud",
        model_ids={"local": meta("local_s12").get("local_model"), "cloud": meta("cloud_all").get("cloud_models")},
        body=body,
    )


# ---------------------------------------------------------------------------------------------- faithfulness (cascade docs + sentinel)  # noqa: E501


def faithfulness_cascade() -> dict[str, Any]:
    docs: dict[str, list[dict[str, Any]]] = {}
    for name in ("cloud_all", "cloud_t3extra", "local_s12", "local_rest", "new_noai"):
        docs[name] = [r["doc"] for r in _ok_runs(load_runs(name))]
    flat = [d for v in docs.values() for d in v]
    return {
        "by_run_set": {k: summarise(v) for k, v in docs.items() if v},
        "all_cascade_verdicts": summarise(flat) if flat else not_evaluated("no cascade run"),
        "violations_examples": [v for d in flat for v in check_doc(d)][:10],
        "mutation_check": mutation_report(flat),
    }
