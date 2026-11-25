#!/usr/bin/env python3
"""Build the HELD-OUT URL set for the UAE-coverage / H7 adoption gate (feat/uae-coverage-escalation).

Usage: uv run python -m evals.uae_coverage.build [--seed N]

Writes data/private/evals/uae_heldout/set.jsonl (raw URLs: private, gitignored) and build_meta.json. Groups:

* ``phishing``      OpenPhish rows never used before: not in the fresh-200 set (now the DEV set), not in the dataset
                    items, not on a registered domain the repo or the verdict store already knows. No row newer than the
                    fresh-200 collection exists (the collector's last poll returned 0 new rows), so these are the
                    unused rows of the same and the previous poll.
* ``phishing_uae``  UAE-targeted hosts from the Phishing.Database ACTIVE list (MIT): a UAE brand/service token in the
                    host name. Picked by host-name pattern only, before any check was run.
* ``legit_global``  Tranco ranks 2000-50000, seeded draw, excluding every domain of the DEV set.
* ``legit_official`` every verified official domain in data/brands.yaml (the false-alarm test: brand domains are
                    legit by design), as ``https://www.<domain>/``.

Nothing here is tuned on: the set is built once and only scored.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from evals.common import ROOT, private_dir
from evals.fresh200.build import canon_url, exclusions, reg

N_PHISH = 120
N_UAE = 40
N_GLOBAL = 80
UAE_HOST_RX = re.compile(
    r"salik|uaepass|uae-pass|emiratespost|emirates-post|aramex|etisalat|adcb|emiratesnbd|mashreq|rakbank|"
    r"dubaipolice|adpolice|mawaqif|adnoc|dewa-|-dewa|icp-uae|uae-icp|rta-dubai|dubai-rta|tamm-|bankfab|"
    r"(^|[.-])uae([.-]|$)|(^|[.-])dubai([.-]|$)|abudhabi|abu-dhabi"
)


def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []


def build(seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    priv = private_dir()
    dev = priv / "evals" / "fresh200"
    urls_ex, doms_ex = exclusions(dev / "verdict_cache_urls.txt")
    dev_rows = _jsonl(dev / "set.jsonl") + _jsonl(dev / "set2.jsonl")
    urls_ex |= {canon_url(r["url"]) for r in dev_rows}
    doms_ex |= {reg(r["url"]) for r in dev_rows}
    rng = random.Random(seed)  # noqa: S311 - reproducible draw, not security
    out: list[dict[str, Any]] = []

    feed: list[dict[str, Any]] = []
    for f in sorted((priv / "feeds" / "openphish").glob("2*.jsonl")):
        feed += _jsonl(f)
    feed.sort(key=lambda r: r["first_seen"], reverse=True)
    taken: set[str] = set()
    for r in feed:
        u = r["url"]
        d = reg(u)
        if not u.startswith(("http://", "https://")) or canon_url(u) in urls_ex or d in doms_ex or d in taken:
            continue
        taken.add(d)
        out.append({"url": u, "label": 1, "group": "phishing", "first_seen": r["first_seen"], "domain": d})
        if len(out) == N_PHISH:
            break

    pdb = [ln.strip().lower() for ln in (dev / "phishdb_domains_active.txt").read_text().splitlines() if ln.strip()]
    uae = sorted({h for h in pdb if UAE_HOST_RX.search(h) and reg(f"http://{h}/") not in doms_ex})
    rng.shuffle(uae)
    for h in uae:
        d = reg(f"http://{h}/")
        if d in taken:
            continue
        taken.add(d)
        out.append({"url": f"http://{h}/", "label": 1, "group": "phishing_uae", "domain": d})
        if sum(1 for r in out if r["group"] == "phishing_uae") == N_UAE:
            break

    ranked = []
    for ln in (dev / "tranco_Q2464_top50000.csv").read_text().splitlines():
        rk, _, d = ln.partition(",")
        if 2000 <= int(rk) <= 50000 and d not in doms_ex and d not in taken:
            ranked.append((int(rk), d))
    for rk, d in rng.sample(ranked, N_GLOBAL):
        out.append({"url": f"https://{d}/", "label": 0, "group": "legit_global", "rank": rk, "domain": d})

    brands = yaml.safe_load((ROOT / "data" / "brands.yaml").read_text())["brands"]
    for b in brands:
        if b.get("category") == "demo":
            continue
        for d in b["verified_domains"]:
            out.append({"url": f"https://www.{d}/", "label": 0, "group": "legit_official", "domain": d,
                        "brand_id": b["brand_id"]})  # fmt: skip
    meta = {
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": seed,
        "counts": {g: sum(1 for r in out if r["group"] == g) for g in sorted({r["group"] for r in out})},
        "uae_pattern_pool": len(uae),
        "phish_first_seen": sorted({r["first_seen"] for r in out if r["group"] == "phishing"}),
        "excluded_registered_domains": len(doms_ex),
    }
    return out, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261125)
    a = ap.parse_args()
    rows, meta = build(a.seed)
    d = private_dir() / "evals" / "uae_heldout"
    d.mkdir(parents=True, exist_ok=True)
    (d / "set.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (d / "build_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
