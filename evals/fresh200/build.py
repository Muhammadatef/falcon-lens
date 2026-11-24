#!/usr/bin/env python3
"""Build the fresh-200 live evaluation set (100 phishing + 100 legitimate) that the product has never seen.

Usage: uv run python -m evals.fresh200.build [--seed N] [--tranco-csv PATH] [--verdict-urls PATH]

What it does: draws the 100 newest OpenPhish-community URLs and 100 Tranco/UAE legitimate sites that are NOT in any
earlier dataset (train/val/test items, every held-out legit set, legit_urls.csv, fp_regress artifacts, message_text,
red-team, fixtures, brands.yaml, every other text file of the repo) and not in the verdict cache, deduplicated by
canonical URL and by registered domain. Raw URLs go ONLY to data/private/evals/fresh200/ (gitignored). Prints counts,
never URLs.

Legit rule: a Tranco domain (ranks 2,000-50,000, seeded random draw) is kept only when it serves a page (one plain
GET, redirects followed, final status < 400) and is not on a keyless public blocklist (Phishing.Database ACTIVE list, OpenPhish feed).
The 20 UAE/Gulf sites are hand-listed official domains (government, bank, telco, retail, news), kept only when they
serve, are not flagged, and the served page title names the entity.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from evals.common import ROOT, private_dir, refang, registrable_domain

UA = "FalconLens-research/0.1"
SEED = 20261124
TRANCO_ID = "Q2464"
TRANCO_DATE = "2026-11-23"
RANK_LO, RANK_HI = 2000, 50000
N_PHISH, N_GLOBAL, N_UAE = 100, 80, 20

# (domain, category, words of which one must appear in the served page title, lower case)
UAE_CANDIDATES: list[tuple[str, str, tuple[str, ...]]] = [
    ("mohap.gov.ae", "government", ("health", "الصحة")),
    ("mof.gov.ae", "government", ("finance", "المالية")),
    ("moec.gov.ae", "government", ("education", "التربية", "التعليم")),
    ("mohre.gov.ae", "government", ("human resources", "الموارد البشرية")),
    ("dm.gov.ae", "government", ("municipality", "بلدية")),
    ("tdra.gov.ae", "government", ("telecommunications", "tdra", "الاتصالات")),
    ("dubaiculture.gov.ae", "government", ("culture", "الثقافة")),
    ("moccae.gov.ae", "government", ("climate", "المناخ")),
    ("emiratesnbd.com", "bank", ("emirates nbd", "الإمارات دبي الوطني")),
    ("cbd.ae", "bank", ("cbd", "commercial bank", "التجاري")),
    ("nbf.ae", "bank", ("nbf", "national bank of fujairah", "الفجيرة")),
    ("ajmanbank.ae", "bank", ("ajman bank", "عجمان")),
    ("alhilalbank.ae", "bank", ("hilal", "الهلال")),
    ("sib.ae", "bank", ("sharjah islamic", "الشارقة")),
    ("alrajhibank.com.sa", "bank", ("rajhi", "الراجحي")),
    ("qnb.com", "bank", ("qnb",)),
    ("nbk.com", "bank", ("nbk", "national bank of kuwait")),
    ("bankmuscat.com", "bank", ("muscat", "مسقط")),
    ("uab.ae", "bank", ("united arab bank", "المتحد")),
    ("bankofsharjah.com", "bank", ("bank of sharjah", "الشارقة")),
    ("damacproperties.com", "retail", ("damac", "داماك")),
    ("spinneys.com", "retail", ("spinneys", "سبينس")),
    ("centrepointstores.com", "retail", ("centrepoint", "centre point")),
    ("emaxme.com", "retail", ("emax", "إيماكس")),
    ("dha.gov.ae", "government", ("health", "الصحة")),
    ("fta.gov.ae", "government", ("tax", "الضرائب")),
    ("virginmobile.ae", "telco", ("virgin",)),
    ("stc.com.sa", "telco", ("stc",)),
    ("ooredoo.qa", "telco", ("ooredoo",)),
    ("omantel.om", "telco", ("omantel", "عمانتل")),
    ("carrefouruae.com", "retail", ("carrefour", "كارفور")),
    ("luluhypermarket.com", "retail", ("lulu", "لولو")),
    ("jumbo.ae", "retail", ("jumbo", "جامبو")),
    ("ounass.ae", "retail", ("ounass", "أُناس", "اوناس")),
    ("6thstreet.com", "retail", ("6thstreet", "6th street")),
    ("emaar.com", "retail", ("emaar", "إعمار")),
    ("gulftoday.ae", "news", ("gulftoday", "gulf today")),
    ("alkhaleej.ae", "news", ("الخليج",)),
    ("albayan.ae", "news", ("البيان",)),
    ("emaratalyoum.com", "news", ("الإمارات اليوم", "emarat")),
    ("zawya.com", "news", ("zawya",)),
    ("arabnews.com", "news", ("arab news",)),
]
QUOTA = {"government": 5, "bank": 5, "telco": 3, "retail": 4, "news": 3}

DOMAIN_RE = re.compile(r"(?:[a-z0-9-]+(?:\[\.\]|\.))+[a-z]{2,}")
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".jsonl", ".csv", ".md", ".txt", ".ts", ".tsx", ".html", ".toml"}
SKIP_DIRS = {".git", "node_modules", ".venv", ".next", "__pycache__", "work", ".claude", "dist", "build"}


def canon_url(url: str) -> str:
    u = refang(url.strip()).replace("[.]", ".")
    p = urlsplit(u)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = p.path.rstrip("/")
    return f"{host}{path}" + (f"?{p.query}" if p.query else "")


def reg(host_or_url: str) -> str:
    h = host_or_url.replace("[.]", ".")
    if "//" not in h:
        h = "http://" + h
    return registrable_domain(refang(h))


def scan_repo_domains(root: Path) -> set[str]:
    """Every registered domain mentioned in any text file of the repo (datasets, fixtures, red-team, docs...)."""
    found: set[str] = set()
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            p = Path(dp) / fn
            if p.suffix not in TEXT_SUFFIXES or "fresh200" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for m in set(DOMAIN_RE.findall(text)):
                d = reg(m)
                if "." in d:
                    found.add(d)
    return found


def exclusions(verdict_urls: Path | None) -> tuple[set[str], set[str]]:
    urls: set[str] = set()
    doms: set[str] = set()
    items = private_dir() / "datasets" / "items.jsonl"
    for ln in items.read_text().splitlines():
        u = json.loads(ln).get("url")
        if u:
            urls.add(canon_url(u))
            doms.add(reg(u))
    if verdict_urls and verdict_urls.exists():
        for ln in verdict_urls.read_text().splitlines():
            if ln.strip():
                urls.add(canon_url(ln))
                doms.add(reg(ln))
    doms |= scan_repo_domains(ROOT)
    return urls, doms


def probe(url: str) -> tuple[bool, str]:
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=10, follow_redirects=True)
    except httpx.HTTPError:
        return False, ""
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:200000], re.I | re.S)
    return r.status_code < 400, (m.group(1).strip() if m else "")


def blocklisted(domains: list[str]) -> set[str]:
    """Candidates whose host (or www.host) is on a keyless public blocklist: the Phishing.Database ACTIVE domain list
    (MIT, fetched once, kept in data/private) or any OpenPhish feed row we hold. Google Safe Browsing was NOT
    used (no key is configured on this host)."""
    bl: set[str] = set()
    pdb = private_dir() / "evals" / "fresh200" / "phishdb_domains_active.txt"
    if not pdb.exists():
        raise SystemExit(f"{pdb} is missing: fetch the Phishing.Database ACTIVE domain list once first")
    bl |= {ln.strip().lower() for ln in pdb.read_text().splitlines() if ln.strip()}
    for f in (private_dir() / "feeds" / "openphish").glob("2*.jsonl"):
        for ln in f.read_text().splitlines():
            if ln.strip():
                bl.add((urlsplit(json.loads(ln)["url"]).hostname or "").lower())
    return {d for d in domains if d in bl or f"www.{d}" in bl}


def pick_phishing(urls_ex: set[str], doms_ex: set[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    for f in sorted((private_dir() / "feeds" / "openphish").glob("2*.jsonl")):
        rows += [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    rows.sort(key=lambda r: r["first_seen"], reverse=True)
    stats = {"feed_rows": len(rows), "dropped_seen_url": 0, "dropped_seen_domain": 0, "dropped_dup_domain": 0}
    out: list[dict[str, Any]] = []
    taken: set[str] = set()
    for r in rows:
        u = r["url"]
        if not u.startswith(("http://", "https://")):
            continue
        d = reg(u)
        if canon_url(u) in urls_ex:
            stats["dropped_seen_url"] += 1
        elif d in doms_ex:
            stats["dropped_seen_domain"] += 1
        elif d in taken:
            stats["dropped_dup_domain"] += 1
        else:
            taken.add(d)
            out.append({"url": u, "label": 1, "group": "phishing", "first_seen": r["first_seen"], "domain": d})
            if len(out) == N_PHISH:
                break
    return out, stats


def _probe_all(hosts: list[str]) -> list[tuple[bool, str]]:
    def one(h: str) -> tuple[bool, str]:
        time.sleep(0.2)
        return probe(f"https://{h}/")

    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(one, hosts))


def pick_legit(
    doms_ex: set[str], seed: int, tranco_csv: Path, phish_doms: set[str]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    ranked = []
    for ln in tranco_csv.read_text().splitlines():
        rk_s, _, dom = ln.partition(",")
        if rk_s.isdigit() and RANK_LO <= int(rk_s) <= RANK_HI:
            ranked.append((int(rk_s), dom.strip().lower()))
    stats = {"tranco_in_range": len(ranked), "excluded_seen": 0, "not_serving": 0, "blocklisted": 0}
    pool: list[tuple[int, str]] = []
    seen: set[str] = set()
    for rk, dom in ranked:
        d = reg(dom)
        if d in doms_ex or d in phish_doms:
            stats["excluded_seen"] += 1
        elif d == dom and d not in seen:  # registrable apex only, one per registered domain
            seen.add(d)
            pool.append((rk, dom))
    cand = random.Random(seed).sample(pool, N_GLOBAL * 2)  # noqa: S311 - seeded draw, not security
    served = _probe_all([c[1] for c in cand])
    ok = [c for c, (s, _) in zip(cand, served, strict=True) if s]
    stats["not_serving"] = len(cand) - len(ok)
    bad = blocklisted([d for _, d in ok])
    out: list[dict[str, Any]] = []
    for rk, d in ok:
        if d in bad:
            stats["blocklisted"] += 1
        elif len(out) < N_GLOBAL:
            out.append({"url": f"https://{d}/", "label": 0, "group": "legit_global", "rank": rk, "domain": d})
    return out, stats


def pick_uae(doms_ex: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    left = dict(QUOTA)
    cats: dict[str, int] = {}
    dropped = 0
    cand = [c for c in UAE_CANDIDATES if reg(c[0]) not in doms_ex]
    res = _probe_all([c[0] for c in cand])
    bad = blocklisted([c[0] for c in cand])
    for (d, cat, words), (ok, title) in zip(cand, res, strict=True):
        named = any(w in title.lower() for w in words)
        if not (ok and named) or d in bad:
            dropped += 1
        elif left[cat] > 0:
            left[cat] -= 1
            cats[cat] = cats.get(cat, 0) + 1
            out.append({"url": f"https://{d}/", "label": 0, "group": "legit_uae", "category": cat, "domain": d})
    return out, {
        "uae_candidates_after_exclusion": len(cand),
        "uae_failed_verification": dropped,
        "uae_by_category": cats,
    }


def main() -> int:
    d_priv = private_dir() / "evals" / "fresh200"
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--tranco-csv", default=str(d_priv / f"tranco_{TRANCO_ID}_top50000.csv"))
    ap.add_argument("--verdict-urls", default=str(d_priv / "verdict_cache_urls.txt"))
    a = ap.parse_args()
    urls_ex, doms_ex = exclusions(Path(a.verdict_urls))
    phish, ps = pick_phishing(urls_ex, doms_ex)
    pdoms = {r["domain"] for r in phish}
    glob, ls = pick_legit(doms_ex, a.seed, Path(a.tranco_csv), pdoms)
    uae, us = pick_uae(doms_ex | pdoms | {r["domain"] for r in glob})
    rows = phish + glob + uae
    print(f"phish={len(phish)} global={len(glob)} uae={len(uae)}", file=sys.stderr)
    if (len(phish), len(glob), len(uae)) != (N_PHISH, N_GLOBAL, N_UAE):
        print(json.dumps({"phishing": ps, "legit_global": ls, "legit_uae": us}), file=sys.stderr)
        return 1
    if len({r["domain"] for r in rows}) != len(rows):
        raise SystemExit("duplicate registered domain in the set")
    d_priv.mkdir(parents=True, exist_ok=True)
    (d_priv / "set.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    meta = {
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": a.seed,
        "tranco_list": TRANCO_ID,
        "tranco_date": TRANCO_DATE,
        "rank_range": [RANK_LO, RANK_HI],
        "excluded_urls": len(urls_ex),
        "excluded_registered_domains": len(doms_ex),
        "phishing": ps,
        "legit_global": ls,
        "legit_uae": us,
        "newest_phish_first_seen": max(r["first_seen"] for r in phish),
        "oldest_phish_first_seen": min(r["first_seen"] for r in phish),
    }
    (d_priv / "build_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
