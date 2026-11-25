#!/usr/bin/env python3
# ruff: noqa: E501
"""Aggregate the held-out BEFORE/AFTER runs, apply the adoption gate, publish aggregates only.

    uv run python -m evals.uae_coverage.report

Reads data/private/evals/uae_heldout/raw_{before,after,h7only,brandsonly}.jsonl (URL rig) and msg_{before,after}.jsonl
(message path), writes evals/results/published/uae_coverage/uae_coverage_<sha>_<ts>.json. No URL or message text is
written. CIs: Wilson 95% per proportion; paired percentile bootstrap 95% (2000 resamples, seed 7) for after-before.

Gate (L1, 2026-11-25), per component: Dangerous recall on phishing goes UP, UAE-targeted warned goes UP, legit
warned (suspicious+dangerous) does NOT go up, legit dangerous stays 0. A component that fails stays behind its flag.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from typing import Any

from evals.common import ROOT, git_sha, private_dir
from evals.fresh200.metrics import wilson

PRIV = private_dir() / "evals" / "uae_heldout"
WARN = ("suspicious", "dangerous")


def load(name: str) -> dict[str, dict[str, Any]]:
    p = PRIV / name
    if not p.exists():
        return {}
    rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    return {str(r.get("url", r.get("id"))): r for r in rows}


def prop(rows: list[dict[str, Any]], pred: Any) -> dict[str, Any]:
    k, n = sum(1 for r in rows if pred(r)), len(rows)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None, "wilson95": [round(lo, 4), round(hi, 4)]}


def paired_diff(pairs: list[tuple[bool, bool]], seed: int = 7, n_boot: int = 2000) -> dict[str, Any]:
    n = len(pairs)
    if not n:
        return {"value": None, "boot95": None}
    d = sum(int(a) - int(b) for b, a in pairs) / n
    rng = random.Random(seed)  # noqa: S311 - statistics
    vals = sorted(
        sum(int(a) - int(b) for b, a in (pairs[rng.randrange(n)] for _ in range(n))) / n for _ in range(n_boot)
    )
    return {
        "value": round(d, 4),
        "boot95": [round(vals[int(0.025 * n_boot)], 4), round(vals[int(0.975 * n_boot) - 1], 4)],
    }


GROUPS = {
    "phishing_all": lambda r: r["label"] == 1,
    "phishing_feed": lambda r: r["group"] == "phishing",
    "phishing_uae": lambda r: r["group"] == "phishing_uae",
    "legit_all": lambda r: r["label"] == 0,
    "legit_global": lambda r: r["group"] == "legit_global",
    "legit_official": lambda r: r["group"] == "legit_official",
}


def url_compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = [k for k in after if k in before and "error" not in after[k] and "error" not in before[k]]
    out: dict[str, Any] = {"n_paired": len(keys), "n_errors": len(set(before) | set(after)) - len(keys), "groups": {}}
    for g, sel in GROUPS.items():
        ks = [k for k in keys if sel(after[k])]
        b, a = [before[k] for k in ks], [after[k] for k in ks]
        out["groups"][g] = {
            "before": {
                "warned": prop(b, lambda r: r["verdict"] in WARN),
                "dangerous": prop(b, lambda r: r["verdict"] == "dangerous"),
            },
            "after": {
                "warned": prop(a, lambda r: r["verdict"] in WARN),
                "dangerous": prop(a, lambda r: r["verdict"] == "dangerous"),
            },
            "diff_warned": paired_diff([(before[k]["verdict"] in WARN, after[k]["verdict"] in WARN) for k in ks]),
            "diff_dangerous": paired_diff(
                [(before[k]["verdict"] == "dangerous", after[k]["verdict"] == "dangerous") for k in ks]
            ),
            "changed_verdicts": sum(1 for k in ks if before[k]["verdict"] != after[k]["verdict"]),
        }
    fired: dict[str, int] = {}
    for k in keys:
        for h in after[k].get("hard_rules", []):
            fired[h] = fired.get(h, 0) + 1
    out["after_hard_rule_counts"] = fired
    out["after_brand_claims"] = sum(1 for k in keys if "brand.claimed_not_owned" in after[k].get("risk_signals", []))
    return out


def gate(c: dict[str, Any]) -> dict[str, Any]:
    g = c["groups"]

    def k(group: str, side: str, m: str) -> int:
        return int(g[group][side][m]["k"])

    checks = {
        "dangerous_recall_up": k("phishing_all", "after", "dangerous") > k("phishing_all", "before", "dangerous"),
        "uae_warned_up": k("phishing_uae", "after", "warned") > k("phishing_uae", "before", "warned"),
        "legit_warned_not_up": k("legit_all", "after", "warned") <= k("legit_all", "before", "warned"),
        "legit_dangerous_zero": k("legit_all", "after", "dangerous") == 0,
    }
    return {"checks": checks, "pass": all(checks.values())}


def msg_compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = [k for k in after if k in before]
    res: dict[str, Any] = {}
    for name, sel in {
        "scam": lambda r: r["label"] == "scam",
        "legitimate": lambda r: r["label"] != "scam",
    }.items():
        ks = [k for k in keys if sel(after[k])]
        res[name] = {
            "before": {"warned": prop([before[k] for k in ks], lambda r: r["verdict"] in WARN),
                       "dangerous": prop([before[k] for k in ks], lambda r: r["verdict"] == "dangerous")},
            "after": {"warned": prop([after[k] for k in ks], lambda r: r["verdict"] in WARN),
                      "dangerous": prop([after[k] for k in ks], lambda r: r["verdict"] == "dangerous")},
            "diff_warned": paired_diff([(before[k]["verdict"] in WARN, after[k]["verdict"] in WARN) for k in ks]),
        }  # fmt: skip
    s, lg = res["scam"], res["legitimate"]
    res["gate"] = {
        "checks": {
            "scam_warned_up": s["after"]["warned"]["k"] > s["before"]["warned"]["k"],
            "legit_warned_not_up": lg["after"]["warned"]["k"] <= lg["before"]["warned"]["k"],
            "legit_dangerous_zero": lg["after"]["dangerous"]["k"] == 0,
        }
    }
    res["gate"]["pass"] = all(res["gate"]["checks"].values())
    return res


def main() -> int:
    meta = json.loads((PRIV / "build_meta.json").read_text())
    before = load("raw_before.jsonl")
    variants = {
        "all_changes": load("raw_after.jsonl"),
        "brands_only": load("raw_brandsonly.jsonl"),
        "h7_only": load("raw_h7only.jsonl"),
    }
    urls = {name: url_compare(before, rows) for name, rows in variants.items() if rows}
    for v in urls.values():
        v["gate"] = gate(v)
    msgs = {}
    for name, (b, a) in {
        "uae_lures_heldout": ("msg_heldout_before.jsonl", "msg_heldout_after.jsonl"),
        "existing_hand_and_hard_neg": ("msg_existing_before.jsonl", "msg_existing_after.jsonl"),
    }.items():
        mb, ma = load(b), load(a)
        if mb and ma:
            msgs[name] = msg_compare(mb, ma)
        else:
            msgs[name] = {
                "status": "not_evaluated",
                "reason": "the local-model generation of the held-out message set (spec evals/specs/"
                "uae_lures_heldout_v1.json) did not finish (model timeouts); no held-out message number exists",
            }
    sha = git_sha()
    now = datetime.now(UTC)
    art = {
        "kind": "uae_coverage_heldout",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": sha,
        "provenance": f"real URLs (held-out, built {meta['built_at']}); messages synthetic (local model, held-out spec)",
        "set": {
            "counts": meta["counts"],
            "seed": meta["seed"],
            "phish_first_seen": meta["phish_first_seen"],
            "uae_pattern_pool": meta["uae_pattern_pool"],
        },  # fmt: skip
        "method": {
            "target": "isolated sandbox + egress proxy (compose project fluae), worker image of origin/main 56b5004 with "
            "this branch's code mounted; NOT the live stack",
            "pairing": "one sandbox visit per URL; the second variant replays the stored page features and the stored "
            "RDAP/crt.sh answers, so before and after judge identical inputs",
            "before": "origin/main data/brands.yaml, H7 off, FL_UAE_LURES=0",
            "variants": {
                "all_changes": "brands.yaml + brands_uae_candidates.yaml (8 UAE brands) + H7 on",
                "brands_only": "brands.yaml + brands_uae_candidates.yaml, H7 off",
                "h7_only": "brands.yaml (origin/main) + H7 on",
            },  # fmt: skip
            "feeds": "feed mirror empty and LLM tiers off in every variant: each phishing row is judged as not on a feed",
            "gate": "dangerous recall on phishing up AND UAE-targeted warned up AND legit warned not up AND legit dangerous 0",
            "ci": "Wilson 95% per proportion; paired percentile bootstrap 95% (2000 resamples, seed 7) for after-before",
        },
        "url": urls,
        "messages": msgs,
        "caveats": [
            "No OpenPhish row newer than the fresh-200 collection existed (the collector's last poll returned 0 rows); "
            "the phishing rows are the unused rows of the same poll, never scored before.",
            "UAE-targeted rows were picked from the Phishing.Database ACTIVE list by a host-name pattern; many such "
            "hosts no longer serve a page, so sandbox page evidence is rare for them.",
            "Legit labels are not hand-audited (Tranco draw; brand official domains from data/brands.yaml).",
            "Message held-out set is synthetic (local model, spec evals/specs/uae_lures_heldout_v1.json), not "
            "supervisor-audited yet; read as indicative.",
            "LLM tiers off: the shipped product also runs T3 for the uncertain band; it cannot change the score.",
            "Single run, one day; intervals are wide for subsets.",
        ],
    }
    out = ROOT / "evals" / "results" / "published" / "uae_coverage"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"uae_coverage_{sha[:12]}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    text = json.dumps(art, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if "http://" in text or "https://" in text:
        raise SystemExit("refusing to publish: artifact contains a URL")
    path.write_text(text)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
