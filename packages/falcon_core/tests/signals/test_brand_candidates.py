"""data/brands_uae_candidates.yaml: sourced like brands.yaml, merged only behind FL_BRANDS_CANDIDATES."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from falcon_core.signals.brands.registry import CANDIDATES_FILE, BrandRegistry, candidates_enabled

DATA = Path(__file__).resolve().parents[4] / "data"
MAIN = DATA / "brands.yaml"
CAND = DATA / CANDIDATES_FILE


def entries(p: Path) -> list[dict[str, object]]:
    return list(yaml.safe_load(p.read_text(encoding="utf-8"))["brands"])


def test_every_candidate_is_sourced_and_logo_free() -> None:
    for e in entries(CAND):
        assert str(e["source_url"]).startswith("https://"), e["brand_id"]
        assert str(e["retrieved_at"]) == "2026-11-25", e["brand_id"]
        assert e["verified_domains"], e["brand_id"]
        assert e.get("logo_ref") is None and e.get("favicon_hash") is None
        for ev in e.get("verification_evidence", []):  # type: ignore[attr-defined]
            assert ev["source_url"].startswith("https://") and ev["shows"]


def test_candidates_do_not_collide_with_main_registry() -> None:
    main_ids = {e["brand_id"] for e in entries(MAIN)}
    main_doms = {d for e in entries(MAIN) for d in e["verified_domains"]}  # type: ignore[attr-defined]
    for e in entries(CAND):
        assert e["brand_id"] not in main_ids
        assert not set(e["verified_domains"]) & main_doms  # type: ignore[arg-type]


def test_off_by_default_and_merged_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FL_BRANDS_CANDIDATES", raising=False)
    assert candidates_enabled() is False
    off = BrandRegistry.from_file(MAIN)
    on = BrandRegistry.from_file(MAIN, candidates=True)
    cand_ids = {str(e["brand_id"]) for e in entries(CAND)}
    assert not cand_ids & {b.brand_id for b in off.brands}
    assert cand_ids <= {b.brand_id for b in on.brands}
    assert on.is_official("aramex.com") and not off.is_official("aramex.com")
    monkeypatch.setenv("FL_BRANDS_CANDIDATES", "1")
    assert {b.brand_id for b in BrandRegistry.from_file(MAIN).brands} == {b.brand_id for b in on.brands}
