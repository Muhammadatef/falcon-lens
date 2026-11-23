"""Tests for the gap-closing evals: checker sensitivity, corpus safety, statistics helpers, artifact guards."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest
import yaml

from evals.common import ROOT
from evals.gaps import arabic, corpus
from evals.gaps.common import PUBLISHED, mean_ci, pctl, rate, wilson, write_artifact
from evals.gaps.faithfulness import check_doc, mutants
from evals.gaps.reports import PRICES, call_cost
from falcon_core.i18n import load_catalog


def _doc() -> dict:
    en, ar = load_catalog("en"), load_catalog("ar")
    return {
        "verdict": "suspicious",
        "degraded": False,
        "evidence": [
            {
                "id": "ev_aaaaaaaa",
                "signal": "url.typosquat",
                "family": "url",
                "observed": {"brand_id": "falcon_demo_bank"},
                "weight": 20.0,
                "polarity": "risk",
                "hard_rule": None,
                "source": "computed",
                "tier": "T1",
                "confidence": 1.0,
                "error": None,
            },
            {
                "id": "ev_bbbbbbbb",
                "signal": "page.cred_form",
                "family": "page",
                "observed": {"present": True},
                "weight": 15.0,
                "polarity": "risk",
                "hard_rule": None,
                "source": "computed",
                "tier": "T2",
                "confidence": 1.0,
                "error": None,
            },
        ],
        "reasons": [
            {
                "en": en.reasons["url.typosquat"],
                "ar": ar.reasons["url.typosquat"],
                "evidence_ids": ["ev_aaaaaaaa"],
                "generated_by": "template",
            },
            {
                "en": en.reasons["page.cred_form"],
                "ar": ar.reasons["page.cred_form"],
                "evidence_ids": ["ev_bbbbbbbb"],
                "generated_by": "template",
            },
        ],
    }


def test_faithful_document_passes() -> None:
    assert check_doc(_doc()) == []


def test_every_mutant_is_rejected() -> None:
    d = _doc()
    ms = mutants(d)
    assert len(ms) >= 6
    for name, m in ms:
        assert check_doc(m), f"mutant {name} was accepted"


def test_claim_must_match_the_cited_evidence() -> None:
    d = _doc()
    d["reasons"][0]["evidence_ids"] = ["ev_bbbbbbbb"]  # typosquat text citing the credential-form evidence
    assert any(v.startswith("R3") for v in check_doc(d))


def test_absent_or_wrong_polarity_evidence_is_rejected() -> None:
    d = copy.deepcopy(_doc())
    d["evidence"][1]["observed"] = {"present": False}
    assert any("evidence_not_present" in v for v in check_doc(d))
    d = copy.deepcopy(_doc())
    d["verdict"] = "no_warning_signs"  # risk evidence cannot explain a no-warning verdict
    assert any("polarity_vs_verdict" in v for v in check_doc(d))


def test_hard_rule_reason_needs_tagged_evidence() -> None:
    d = _doc()
    d["reasons"][0] = {
        "en": load_catalog("en").hard_rules["H1"],
        "ar": load_catalog("ar").hard_rules["H1"],
        "evidence_ids": ["ev_aaaaaaaa"],
        "generated_by": "template",
    }
    assert any("evidence_not_tagged_H1" in v for v in check_doc(d))
    d["evidence"][0]["hard_rule"] = "H1"
    assert not any("tagged" in v for v in check_doc(d))


def test_wilson_and_rate() -> None:
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and 0.69 < lo < 0.73
    r = rate(3, 4)
    assert r["value"] == 0.75 and r["k"] == 3 and r["ci95"][0] < 0.75 < r["ci95"][1]
    assert mean_ci([])["mean"] is None
    assert pctl([1.0, 2.0, 3.0, 4.0], 50) == 2.5 and pctl([], 50) is None


def test_cost_arithmetic_uses_the_recorded_prices() -> None:
    c = {
        "model": "claude-haiku-5-5",
        "route": "cloud",
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_write_tokens": 0,
        "cache_read_tokens": 0,
    }
    assert call_cost(c) == pytest.approx(PRICES["claude-haiku-5-5"]["input"] + PRICES["claude-haiku-5-5"]["output"])
    assert call_cost({**c, "route": "local"}) is None
    assert call_cost({**c, "model": "unknown-model"}) is None


def test_corpus_is_safe_and_labelled() -> None:
    items = [*corpus.ITEMS, *corpus.new_lookalike_set()]
    assert len({i.item_id for i in items}) == len(items)
    brands = yaml.safe_load((ROOT / "data" / "brands.yaml").read_text(encoding="utf-8"))["brands"]
    real = [b["name_en"].lower() for b in brands if b["brand_id"] != "falcon_demo_bank"]
    for i in items:
        blob = ((i.html or "") + (i.text or "")).lower()
        assert not any(name in blob for name in real), f"{i.item_id} names a real brand"
        if i.url:
            host = i.url.split("/")[2]
            assert host.endswith(".test"), i.url
            assert i.html and "TEST FIXTURE, not a real site" in i.html
            assert 'action="#"' in i.html or "<form" not in i.html  # forms post nowhere
        if i.text:
            assert "synthetic" in i.text.lower() or "اصطناعية" in i.text
    # the brand-new hosts must not be in any list the system already knows
    known = set(corpus.hosts(corpus.ITEMS)) | set(corpus.hosts(()))
    assert all(h not in known for h, _ in corpus.NEW_LOOKALIKE_HOSTS)


def test_arabic_sheet_has_thirty_items_and_passes_the_automated_checks() -> None:
    items = arabic.build_items(30)
    assert len(items) == 30 and len({i["item_id"] for i in items}) == 30
    c = arabic.auto_checks(items)
    assert c["forbidden_words_present"] == [] and not c["digits_present"] and not c["links_present"]
    assert c["reason_within_budget"]["value"] == 1.0


def test_arabic_ingest_reports_partial_then_rated(tmp_path: Path) -> None:
    p = tmp_path / "sheet.csv"
    cols = ["item_id", "clarity_1_to_5", "would_know_what_to_do_yes_no", "comment", "rater"]
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerow(
            {"item_id": "a", "clarity_1_to_5": "5", "would_know_what_to_do_yes_no": "yes", "comment": "", "rater": "r1"}
        )
        w.writerow(
            {"item_id": "b", "clarity_1_to_5": "", "would_know_what_to_do_yes_no": "", "comment": "", "rater": ""}
        )
    assert arabic.ingest(p)["status"] == "partially_rated"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for k in "ab":
            w.writerow(
                {
                    "item_id": k,
                    "clarity_1_to_5": "4",
                    "would_know_what_to_do_yes_no": "yes",
                    "comment": "",
                    "rater": "r1",
                }
            )
    out = arabic.ingest(p)
    assert out["status"] == "rated" and out["clarity_1_to_5"]["mean"] == 4.0


def test_write_artifact_refuses_a_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("evals.gaps.common.PUBLISHED", tmp_path)
    with pytest.raises(ValueError):
        write_artifact("x", {"git_sha": "abc", "leak": "see https://example.com/"})
    p = write_artifact("x", {"git_sha": "abc", "ok": 1})
    assert p.parent == tmp_path / "x" and json.loads(p.read_text())["ok"] == 1


REQUIRED = {
    "system_under_test",
    "scope",
    "n",
    "ci_method",
    "provenance",
    "model_route",
    "model_ids",
    "git_sha",
    "created_at",
    "area",
}


def test_published_gap_artifacts_state_scope_n_ci_provenance_route_model_and_sha() -> None:
    files = [f for d in PUBLISHED.iterdir() if d.is_dir() for f in d.glob("*.json")]
    gap = [f for f in files if "area" in json.loads(f.read_text())]
    for f in gap:
        doc = json.loads(f.read_text())
        assert set(doc) >= REQUIRED, f"{f.name} lacks {REQUIRED - set(doc)}"
        assert f.parent.parent == PUBLISHED  # never top-level
        assert "http" not in f.read_text().lower().replace("hxxp", ""), f"{f.name} carries a URL"
