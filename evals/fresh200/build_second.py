#!/usr/bin/env python3
"""Second-source phishing set for the fresh-200 run: 100 hosts the product's reputation feeds do not list.

Why: every URL of the main set came from the OpenPhish community feed, which the live stack also ingests, so a
reputation lookup alone catches them. This set draws seeded-random hosts from the keyless Phishing.Database ACTIVE
domain list (MIT; fetched once to data/private/evals/fresh200/), excluding everything the main build excluded, the
main set itself, every OpenPhish row held and the verdict store. Hosts are submitted as ``http://<host>/``.

Usage: uv run python -m evals.fresh200.build_second [--seed N] [--n 100]
"""

from __future__ import annotations

import argparse
import json
import random

from evals.common import private_dir
from evals.fresh200.build import exclusions, reg

SEED = 20261124


def main() -> int:
    d = private_dir() / "evals" / "fresh200"
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--n", type=int, default=100)
    a = ap.parse_args()
    urls_ex, doms_ex = exclusions(d / "verdict_cache_urls.txt")
    main_rows = [json.loads(ln) for ln in (d / "set.jsonl").read_text().splitlines()]
    doms_ex |= {r["domain"] for r in main_rows}
    for f in (private_dir() / "feeds" / "openphish").glob("2*.jsonl"):
        for ln in f.read_text().splitlines():
            if ln.strip():
                doms_ex.add(reg(json.loads(ln)["url"]))
    pool: list[str] = []
    seen: set[str] = set()
    for ln in (d / "phishdb_domains_active.txt").read_text().splitlines():
        h = ln.strip().lower()
        if not h or "/" in h or ":" in h or "." not in h:
            continue
        r = reg(h)
        if r in doms_ex or r in seen:
            continue
        seen.add(r)
        pool.append(h)
    pick = random.Random(a.seed).sample(pool, a.n)  # noqa: S311 - seeded draw, not security
    rows = [{"url": f"http://{h}/", "label": 1, "group": "phishing_db", "domain": reg(h)} for h in pick]
    (d / "set2.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"set2: {len(rows)} of pool {len(pool)} (seed {a.seed}); excluded urls={len(urls_ex)} domains={len(doms_ex)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
