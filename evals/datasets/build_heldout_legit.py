#!/usr/bin/env python3
"""Build the HELD-OUT legitimate sample (never used for tuning): seeded random domains from a Tranco list.

Usage: uv run python evals/datasets/build_heldout_legit.py [--list 46YLX] [--top 5000] [--n 200] [--seed 20261123]

Draws uniformly at random (no hand picking, no curation) from the top ``--top`` ranks of Tranco list ``--list``,
excluding every registrable domain already in evals/datasets/legit_urls.csv and the domains inspected while
developing the false-positive fix (EXCLUDE_EXTRA). Writes bare domains (no scheme) to heldout_legit.csv;
the evaluators build ``https://<domain>/`` at run time. Label noise is possible (the list is not curated).
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import httpx
import tldextract

HERE = Path(__file__).resolve().parent
PSL = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
EXCLUDE_EXTRA = {"x.com", "tripadvisor.com", "google.com", "wikipedia.org", "github.com"}


def registrable(host: str) -> str:
    e = PSL(host)
    return f"{e.domain}.{e.suffix}" if e.suffix else host


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="46YLX")
    ap.add_argument("--top", type=int, default=5000)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261123)
    a = ap.parse_args()
    with (HERE / "legit_urls.csv").open(newline="", encoding="utf-8") as f:
        used = {r["url"].split("//", 1)[-1].split("/", 1)[0] for r in csv.DictReader(f)}
    used = {registrable(h) for h in used} | EXCLUDE_EXTRA
    text = httpx.get(
        f"hxxps://tranco-list.eu/download/{a.list}/{a.top}".replace("hxxp", "http", 1),
        follow_redirects=True,
        timeout=60,
    ).text
    rows = [ln.split(",", 1) for ln in text.splitlines() if "," in ln]
    pool = [(int(r), d.strip().lower()) for r, d in rows if registrable(d.strip().lower()) not in used]
    pick = sorted(random.Random(a.seed).sample(pool, a.n))
    with (HERE / "heldout_legit.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["domain", "rank", "tranco_list", "seed"])
        for rank, dom in pick:
            w.writerow([dom, rank, a.list, a.seed])
    print(f"wrote {len(pick)} of pool {len(pool)} (list {a.list}, top {a.top}, seed {a.seed})")


if __name__ == "__main__":
    main()
