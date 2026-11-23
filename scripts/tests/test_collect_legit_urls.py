"""Offline tests for evals/datasets/collect_legit_urls.py candidate lists (no network).

Run: uv run --no-project --with httpx --with tldextract --with pyyaml --with pytest pytest scripts/tests/test_collect_legit_urls.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals/datasets"))
import collect_legit_urls as c  # noqa: E402

CSV_ROWS = {r["url"]: r for r in csv.DictReader((ROOT / "evals/datasets/legit_urls.csv").open(newline=""))}


def test_c06_lists_have_expected_sizes() -> None:
    assert len(c.NEW_DOMAIN_VERIFIED) == 35
    assert len(c.SHORTENED_C06) == 23
    assert len({d for d, *_ in c.NEW_DOMAIN_VERIFIED}) == 35
    assert len({u for u, _ in c.SHORTENED_C06}) == 23


def test_c06_new_domains_are_pinned_and_defanged() -> None:
    for domain, created, server, linked_from, _note in c.NEW_DOMAIN_VERIFIED:
        assert created >= "2024-01-01", domain
        assert server and "/" not in server, domain
        assert linked_from.startswith("hxxps://"), domain
        assert domain not in c.NEW_DOMAIN_CANDIDATES


def test_c06_short_links_are_named_slugs() -> None:
    for url, owner in c.SHORTENED_C06:
        assert url.startswith("hxxps://")
        assert url.count("/") >= 3 and not url.endswith("/"), url
        assert owner


def test_c06_rows_come_out_of_build_candidates_as_committed() -> None:
    cands = {r["url"]: r for r in c.build_candidates()}
    expected = [f"hxxps://{d}/" for d, *_ in c.NEW_DOMAIN_VERIFIED] + [u for u, _ in c.SHORTENED_C06]
    for url in expected:
        assert url in cands, url
        assert url in CSV_ROWS, url
        assert cands[url]["category"] == CSV_ROWS[url]["category"]
        assert cands[url]["source"] == CSV_ROWS[url]["source"]
        assert c.reg_domain(url) == CSV_ROWS[url]["registrable_domain"]
