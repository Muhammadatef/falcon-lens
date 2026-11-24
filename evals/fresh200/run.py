#!/usr/bin/env python3
"""Submit the fresh-200 set to the LIVE API and publish an aggregate-only artifact.

Usage:
  uv run python -m evals.fresh200.run submit [--base https://localhost:8443] [--workers 4] [--budget-min 45]
  uv run python -m evals.fresh200.run publish

``submit`` posts every URL of data/private/evals/fresh200/set.jsonl to POST /v1/check/url (the product's own sandbox
does the single passive visit), polls until the verdict is final and appends one raw row per URL to
data/private/evals/fresh200/raw.jsonl (resumable). Concurrency is capped at 4, 429 answers are retried after the
server's Retry-After. The API key comes from FL_API_KEY or the main checkout's .env (the low-rate judge sandbox key,
scope ``check``); it is never printed. ``publish`` aggregates raw.jsonl through evals.fresh200.metrics and writes
evals/results/published/fresh200/fresh200_<sha>_<ts>.json: aggregates and defanged error examples only.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from evals.common import ROOT, git_sha, private_dir
from evals.fresh200.metrics import defang, is_live, summarise

KEY_NAME = "FL_SANDBOX_API_KEY"
POLL_TIMEOUT_S = 240
MAX_429_RETRIES = 12
PRIV = private_dir() / "evals" / "fresh200"
_lock = threading.Lock()
HTTP_429 = [0]


def ca_bundle() -> str:
    """The gateway's local root CA (Caddy ``tls internal``), so the API key is never sent over an unverified TLS link.

    Export it once: ``docker exec falcon-gateway-1 cat /data/caddy/pki/authorities/local/root.crt > data/private/falcon-local-ca.crt``.
    """
    p = Path(os.environ.get("FL_CA_BUNDLE", str(private_dir() / "falcon-local-ca.crt")))
    if not p.exists():
        raise SystemExit(f"local CA bundle {p} is missing: export the gateway root CA (see ca_bundle docstring)")
    return str(p)


def api_key() -> str:
    if os.environ.get("FL_API_KEY"):
        return os.environ["FL_API_KEY"]
    env = private_dir().parents[1] / ".env"
    for ln in env.read_text().splitlines() if env.exists() else []:
        k, _, v = ln.partition("=")
        if k.strip() == KEY_NAME:
            return v.strip().strip("\"'")
    raise SystemExit(f"no API key: set FL_API_KEY or {KEY_NAME} in .env")


def _req(c: httpx.Client, method: str, path: str, **kw: Any) -> httpx.Response:
    for _ in range(MAX_429_RETRIES):
        r = c.request(method, path, **kw)
        if r.status_code != 429:
            return r
        with _lock:
            HTTP_429[0] += 1
        time.sleep(min(30.0, float(r.headers.get("retry-after", "5"))))
    return r


def check_one(base: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
    base_row: dict[str, Any] = {k: row[k] for k in ("url", "label", "group", "domain") if k in row}
    t0 = time.monotonic()
    try:
        with httpx.Client(base_url=base, verify=ca_bundle(), timeout=20, headers={"X-API-Key": key}) as c:
            r = _req(c, "POST", "/v1/check/url", json={"url": row["url"]})
            r.raise_for_status()
            vid = r.json()["verdict_id"]
            while time.monotonic() - t0 < POLL_TIMEOUT_S:
                g = _req(c, "GET", f"/v1/verdicts/{vid}")
                if g.status_code == 200 and g.json().get("final"):
                    d = g.json()
                    return {
                        **base_row,
                        "verdict": d["verdict"],
                        "risk_score": d.get("risk_score"),
                        "degraded": bool(d.get("degraded")),
                        "degraded_reasons": d.get("degraded_reasons") or [],
                        "tier": d.get("tier_reached"),
                        "model_route": d.get("model_route"),
                        "server_latency_ms": d.get("latency_ms"),
                        "latency_s": round(time.monotonic() - t0, 2),
                        "verdict_id": vid,
                        "signals": sorted({e["signal"] for e in d.get("evidence", [])}),
                        "risk_signals": sorted({e["signal"] for e in d.get("evidence", []) if e.get("weight", 0) > 0}),
                        # a reputation feed (openphish / gsb / urlhaus) already listed this URL: a lookup, not a model call
                        "rep_hit": any(
                            e["signal"].startswith("rep.") and e.get("weight", 0) > 0 for e in d.get("evidence", [])
                        ),
                    }
                time.sleep(1.0)
        return {**base_row, "error": "timeout_no_final", "latency_s": round(time.monotonic() - t0, 2)}
    except Exception as exc:  # noqa: BLE001
        return {**base_row, "error": type(exc).__name__, "latency_s": round(time.monotonic() - t0, 2)}


def submit(a: argparse.Namespace) -> int:
    rows = [json.loads(ln) for ln in (PRIV / a.set).read_text().splitlines()]
    raw = PRIV / a.raw
    done = {json.loads(ln)["url"] for ln in raw.read_text().splitlines()} if raw.exists() else set()
    todo = [r for r in rows if r["url"] not in done]
    # interleave classes so a budget cut still leaves both classes covered
    random.Random(20261124).shuffle(todo)  # noqa: S311 - reproducible order, not security
    key = api_key()
    deadline = time.monotonic() + a.budget_min * 60
    print(f"fresh200 submit: base={a.base} todo={len(todo)} workers={a.workers} budget_min={a.budget_min}", flush=True)

    def one(r: dict[str, Any]) -> None:
        if time.monotonic() > deadline:
            return
        res = check_one(a.base, key, r)
        with _lock, raw.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            n = sum(1 for _ in raw.open())
        print(f"  {n}/{len(rows)} {r['group']} -> {res.get('verdict', res.get('error'))}", flush=True)

    with ThreadPoolExecutor(max_workers=min(a.workers, 4)) as ex:
        list(ex.map(one, todo))
    print(f"http_429={HTTP_429[0]}")
    stats_path = PRIV / "run_stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    stats[a.raw] = {"http_429": stats.get(a.raw, {}).get("http_429", 0) + HTTP_429[0]}
    stats_path.write_text(json.dumps(stats, indent=2) + "\n")
    return 0


def publish(_: argparse.Namespace) -> int:
    raw_rows = [json.loads(ln) for ln in (PRIV / "raw.jsonl").read_text().splitlines()]
    meta = json.loads((PRIV / "build_meta.json").read_text())
    run_stats = json.loads((PRIV / "run_stats.json").read_text())
    ok = [r for r in raw_rows if "error" not in r]
    errs = [r for r in raw_rows if "error" in r]
    summary = summarise(ok)
    raw2 = PRIV / "raw2.jsonl"
    rows2 = [json.loads(ln) for ln in raw2.read_text().splitlines()] if raw2.exists() else []
    ok2 = [r for r in rows2 if "error" not in r]
    legit_main = [r for r in ok if r["label"] == 0]
    summary2 = summarise(ok2 + legit_main) if ok2 else None
    examples: dict[str, list[dict[str, Any]]] = {
        "missed_phishing": [],
        "false_alarms_on_legit": [],
        "dangerous_on_legit": [],
    }
    for r in ok + ok2:
        if r["label"] == 1 and r["verdict"] == "no_warning_signs":
            examples["missed_phishing"].append(
                {"url": defang(r["url"], host_only=True), "verdict": r["verdict"], "tier": r["tier"],
                 "degraded": r["degraded"], "page_live_in_sandbox": is_live(r), "risk_score": r["risk_score"]}
            )  # fmt: skip
        if r["label"] == 0 and r["verdict"] in ("suspicious", "dangerous"):
            ex = {"url": defang(r["url"]), "group": r["group"], "verdict": r["verdict"], "tier": r["tier"],
                  "degraded": r["degraded"], "degraded_reasons": r["degraded_reasons"], "risk_score": r["risk_score"]}  # fmt: skip
            examples["false_alarms_on_legit"].append(ex)
            if r["verdict"] == "dangerous":
                examples["dangerous_on_legit"].append(ex)
    for k in examples:
        examples[k] = examples[k][:15]
    sha = git_sha()
    now = datetime.now(UTC)
    artifact = {
        "kind": "fresh200_live",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": sha,
        "provenance": f"real, collected {meta['built_at'][:10]}",
        "target": "live stack (gateway on this host; same deployment as the public site), judge sandbox key, scope check",
        "n_submitted": len(raw_rows),
        "n_errors": len(errs),
        "errors": [{"group": e["group"], "error": e["error"]} for e in errs],
        "composition": {"phishing": 100, "legit_global": 80, "legit_uae": 20},
        "sources": {
            "phishing": "OpenPhish community feed (keyless mirror), newest rows; first_seen "
            f"{meta['oldest_phish_first_seen']}..{meta['newest_phish_first_seen']}; raw URLs kept private (feed bars redistribution)",
            "legit_global": f"Tranco list {meta['tranco_list']} ({meta['tranco_date']}), ranks {meta['rank_range'][0]}-{meta['rank_range'][1]}, "
            f"seeded random draw (seed {meta['seed']})",
            "legit_uae": "hand-listed official UAE/Gulf domains (government, banks, telcos, retail, news)",
        },
        "exclusion_method": {
            "excluded_canonical_urls": meta["excluded_urls"],
            "excluded_registered_domains": meta["excluded_registered_domains"],
            "against": "dataset items (train/val/test), every held-out legit set, legit_urls.csv, fp_regress artifacts, "
            "message_text, red-team, fixtures, brands.yaml, every text file of the repo, and the verdict store",
            "dedupe": "canonical URL and registered domain (public-suffix list incl. private suffixes)",
            "build_stats": {k: meta[k] for k in ("phishing", "legit_global", "legit_uae")},
        },
        "definitions": {
            "caught": "verdict suspicious or dangerous (any_warning); dangerous_only counts dangerous alone",
            "live_in_sandbox": "no sandbox.not_rendered evidence and no render-failure degraded reason (timeout, dns_failure, "
            "tls_error, http_403_empty, empty_response)",
            "reached_ai_step": "tier_reached T3 (the investigator, used only for the uncertain band); llm_evidence_present is any llm.* evidence",
            "ci": "Wilson 95% for proportions; percentile bootstrap 95% (2000 resamples, seed 7) for precision, F1, accuracy and recall/FPR",
        },
        "http_429": {k: v["http_429"] for k, v in run_stats.items()},
        "results": summary,
        "results_second_source": summary2,
        "second_source": {
            "what": "100 seeded-random hosts from the Phishing.Database ACTIVE domain list (MIT), not in the OpenPhish rows "
            "the live stack ingests; submitted as http://<host>/; legit rows are the same 100 as the main run",
            "n_submitted": len(rows2),
            "n_errors": len(rows2) - len(ok2),
        },
        "error_examples_defanged": examples,
        "caveats": [
            "Legit labels are not hand-audited: a Tranco site is labelled legit when it served a page and was on no keyless "
            "public blocklist (Phishing.Database ACTIVE list, OpenPhish feed); Google Safe Browsing was not used (no key configured).",
            "Phishing labels are the feed's own: a listed URL may already be dead or taken down; those are reported separately.",
            "Main-set phishing came from the OpenPhish feed that the live stack also ingests: a reputation lookup (T0) can "
            "catch these without any model. Read the main-set recall as feed-coverage plus pipeline, and use "
            "results_second_source (hosts from a feed the stack does not query) and the no_reputation_hit groups for the model's own detection.",
            "The same feed supplied the earlier training data, so the main phishing sample is not independent of it.",
            "23 URLs of the main set were submitted once in a discarded pilot of this same run before two extra fields were "
            "recorded; the raw rows were thrown away and all 200 were resubmitted, so those 23 may have been served from the verdict cache (latency).",
            "A request that hits the per-key rate limit waits for Retry-After and retries; latency_s includes that wait, http_429 counts the retries.",
            "Single run on one day, n=200; intervals are wide for subsets. Not a test-split result and not tuned on.",
        ],
    }
    out = ROOT / "evals" / "results" / "published" / "fresh200"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"fresh200_{sha[:12]}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"artifact {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--base", default=os.environ.get("FL_GATEWAY_URL", "https://localhost:8443"))
    s.add_argument("--set", default="set.jsonl")
    s.add_argument("--raw", default="raw.jsonl")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--budget-min", type=float, default=45.0)
    sub.add_parser("publish")
    a = ap.parse_args()
    return submit(a) if a.cmd == "submit" else publish(a)


if __name__ == "__main__":
    sys.exit(main())
