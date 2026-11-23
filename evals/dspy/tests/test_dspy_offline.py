"""Metric, dataset-determinism and loader tests. None of them needs dspy (the loader test asserts that)."""

from __future__ import annotations

import subprocess
import sys

import fl_data
import fl_messages
import fl_metrics as M
import pytest

VIEW = {
    "incident_id": "inc_X",
    "type": "campaign",
    "severity": "high",
    "brand_id": "falcon_demo_bank",
    "rule_ids": ["R1", "R2"],
    "indicators": [
        {"kind": "domain", "value_defanged": "a-login[.]test", "id": "ind:1"},
        {"kind": "domain", "value_defanged": "b-secure[.]test", "id": "ind:2"},
        {"kind": "domain", "value_defanged": "c-verify[.]test", "id": "ind:3"},
    ],
    "evidence_ids": ["rule:R1", "rule:R2", "evt_01M7YRRT80M6KX2YK04P2T5SCB", "key:dom_simhash"],
}
GOOD = {
    "summary_en": "A campaign for falcon_demo_bank: 3 lookalike domains matched R1 and R2.",
    "summary_ar": "حملة ضد العلامة falcon_demo_bank: ثلاثة نطاقات مشابهة تطابقت مع R1 وR2.",
    "claims": [
        {"text_en": "Rule R1 fired.", "evidence_ids": ["rule:R1"]},
        {"text_en": "3 domains share a hash.", "evidence_ids": ["key:dom_simhash"]},
    ],
    "severity": "high",
    "severity_reason": "R1 and R2 fired on a brand campaign.",
}


def test_good_summary_scores_one() -> None:
    assert M.summary_score(GOOD, VIEW) == 1.0
    c = M.summary_components(GOOD, VIEW)
    assert c["all_claims_faithful"] == 1.0 and c["hygiene_ok"] == 1.0


def test_claim_with_unknown_id_or_no_id_is_unfaithful() -> None:
    assert not M.claim_supported({"text_en": "x", "evidence_ids": ["rule:R9"]}, VIEW)
    assert not M.claim_supported({"text_en": "x", "evidence_ids": []}, VIEW)
    assert M.faithfulness([], VIEW) == 0.0


def test_claim_naming_rule_must_cite_it() -> None:
    assert not M.claim_supported({"text_en": "Rule R2 fired.", "evidence_ids": ["rule:R1"]}, VIEW)
    assert not M.claim_supported({"text_en": "Rule R4 fired.", "evidence_ids": ["rule:R1"]}, VIEW)


def test_claim_naming_unknown_domain_is_unfaithful() -> None:
    assert M.claim_supported({"text_en": "a-login[.]test was seen.", "evidence_ids": ["rule:R1"]}, VIEW)
    assert not M.claim_supported({"text_en": "evil[.]test was seen.", "evidence_ids": ["rule:R1"]}, VIEW)
    assert not M.claim_supported({"text_en": "evil.test was seen.", "evidence_ids": ["rule:R1"]}, VIEW)


@pytest.mark.parametrize(
    ("patch", "flag"),
    [
        ({"summary_ar": ""}, "arabic_missing"),
        ({"summary_ar": "english only"}, "arabic_missing"),
        ({"summary_en": "This domain is safe."}, "says_safe"),
        ({"summary_ar": "الموقع آمن"}, "says_safe"),
        ({"summary_en": "x" * 1501}, "summary_too_long"),
        ({"claims": [{"text_en": "y" * 501, "evidence_ids": ["rule:R1"]}]}, "claim_too_long"),
    ],
)
def test_hygiene(patch: dict[str, object], flag: str) -> None:
    pred = {**GOOD, **patch}
    assert flag in M.hygiene_violations(pred)
    assert M.summary_score(pred, VIEW) == 0.0


def test_coverage_counts_key_facts() -> None:
    assert M.coverage(GOOD, VIEW) == 1.0
    empty = {"summary_en": "Something happened.", "claims": []}
    assert M.coverage(empty, VIEW) < 0.5


def test_severity_echo_only_affects_its_weight() -> None:
    wrong = {**GOOD, "severity": "low"}
    assert M.summary_score(wrong, VIEW) == pytest.approx(1.0 - M.WEIGHTS["severity"])


def test_classifier_metrics() -> None:
    assert M.classifier_score("prize", True, "prize") == 1.0
    assert M.classifier_score("job", True, "prize") == 0.5
    assert M.classifier_score("none", False, "prize") == 0.0
    gold = ["prize", "prize", "none", "job"]
    pred = ["prize", "none", "none", "job"]
    r = M.per_class_f1(gold, pred)
    assert r["prize"]["recall"] == 0.5 and r["prize"]["precision"] == 1.0
    assert r["_accuracy"] == 0.75
    assert r["_is_scam"]["recall"] == pytest.approx(0.6667, abs=1e-3)


def test_messages_deterministic_and_safe() -> None:
    a, b = fl_messages.build_messages(11), fl_messages.build_messages(11)
    assert a == b and a != fl_messages.build_messages(12)
    assert all(m["synthetic"] for m in a)
    assert {m["category"] for m in a} == set(M.SCRIPT_CATEGORIES)
    blob = " ".join(m["text"] for m in a)
    assert "http://" not in blob and "https://" not in blob  # only defanged example[.]test links


def test_message_dataset_split_has_no_template_overlap_and_is_deterministic() -> None:
    d1, d2 = fl_data.build_message_dataset(), fl_data.build_message_dataset()
    assert fl_data.dataset_hash(d1["train"] + d1["val"]) == fl_data.dataset_hash(d2["train"] + d2["val"])
    ids_t, ids_v = {i["id"] for i in d1["train"]}, {i["id"] for i in d1["val"]}
    assert not ids_t & ids_v
    assert all(i["id"].split("-")[-2] == "2" for i in d1["val"])  # val = third template of each cell only
    assert all(i["id"].split("-")[-2] != "2" for i in d1["train"])
    assert all("<URL>" in i["message"] or i["gold_category"] == "none" for i in d1["train"] + d1["val"])
    assert {i["gold_category"] for i in d1["val"]} == set(M.SCRIPT_CATEGORIES)


def test_incident_dataset_deterministic_and_split_by_seed() -> None:
    a = fl_data.build_incident_dataset(range(1, 4), range(101, 103))
    b = fl_data.build_incident_dataset(range(1, 4), range(101, 103))
    assert a == b
    assert {i["seed"] for i in a["train"]}.isdisjoint({i["seed"] for i in a["val"]})
    assert {i["gold"]["type"] for i in a["train"]} <= {"campaign", "kit_reuse", "reputation_flip"}
    for it in a["train"] + a["val"]:
        assert it["gold"]["severity"] == it["view"]["severity"]
    with pytest.raises(ValueError):
        fl_data.build_incident_dataset(range(1, 3), range(2, 4))


def test_loader_does_not_import_dspy() -> None:
    code = "import sys, falcon_core.prompts.compiled as c; assert 'dspy' not in sys.modules"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert r.returncode == 0, r.stderr
