#!/usr/bin/env python3
"""Add the ``serves_web`` column to a held-out set: does the registrable domain serve a web page at all?

Usage: uv run python evals/datasets/probe_heldout_web.py heldout_legit_2.csv

Defined BEFORE any verdict is looked at and independent of the verdict pipeline: one plain GET of
``https://<domain>/`` (then ``http://<domain>/`` if the first fails), honest user agent, redirects NOT followed,
no forms, no JS. ``serves_web=1`` if either answers 2xx/3xx, else 0 (DNS failure, refused, timeout, 4xx/5xx).
Users check websites, so FPR is reported for both rows (serves a web page / no web host); neither replaces the
other and no item is dropped or re-sampled.
"""

from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
UA = "FalconLens-research/0.1"


def serves_web(domain: str) -> int:
    for scheme in ("https", "http"):
        try:
            r = httpx.get(f"{scheme}://{domain}/", headers={"User-Agent": UA}, timeout=8, follow_redirects=False)
        except httpx.HTTPError:
            continue
        if 200 <= r.status_code < 400:
            return 1
    return 0


def main(name: str) -> None:
    path = HERE / name
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r.pop("serves_web", None)
        r.pop("probed_at", None)

    def one(row: dict[str, str]) -> int:
        time.sleep(0.2)  # at most a few requests per second overall
        return serves_web(row["domain"])

    with ThreadPoolExecutor(max_workers=4) as ex:
        flags = list(ex.map(one, rows))
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    fields = [*rows[0].keys(), "serves_web", "probed_at"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, flag in zip(rows, flags, strict=True):
            w.writerow({**r, "serves_web": flag, "probed_at": stamp})
    print(f"{name}: n={len(rows)} serves_web={sum(flags)} no_web_host={len(rows) - sum(flags)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "heldout_legit_2.csv")
