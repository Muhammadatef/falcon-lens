"""Offline pipeline tests for scripts/qwen_task.py: validators and an end-to-end run with a fake model.

Run: uv run --no-project --with httpx --with jsonschema --with pytest pytest scripts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qwen_task as q

SPEC_PATH = Path(__file__).resolve().parents[2] / "evals" / "specs" / "synthetic_messages_v2.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
LINK = SPEC["allowed_link_regex"]
LANG = SPEC["language_rules"]


def test_language_checked_on_text_not_declared_field() -> None:
    en = "Your parcel is held. Pay the fee today."
    msa = "تم تعليق حسابك المصرفي، يرجى تحديث بياناتك الآن."
    gulf = "حسابك وايد مهم، شلون تبي نوقفه؟ زين سوي التحديث."
    arabizi = "marhaba habibi, 3indak mokhalafa ya sadiqi"
    assert q.check_language(en, "english", LANG) is None
    assert q.check_language(en, "msa", LANG) == "language_script"
    assert q.check_language(msa, "msa", LANG) is None
    assert q.check_language(gulf, "msa", LANG) == "language_marker_forbidden"
    assert q.check_language(gulf, "gulf_arabic", LANG) is None
    assert q.check_language(msa, "gulf_arabic", LANG) == "language_marker_missing"
    assert q.check_language(arabizi, "arabizi", LANG) is None
    assert q.check_language(en, "arabizi", LANG) == "language_no_arabizi_digits"
    assert q.check_language(msa, "english", LANG) == "language_script"


def test_link_allowlist_rejects_malformed_placeholders() -> None:
    assert q.check_links("Pay now hxxps://example[.]test/p-1_a today", LINK) is None
    assert q.check_links("no link here", LINK) is None
    for bad in (
        "هxxps://example[.]test/p1",
        "Hxxps://example[.]test/p1",
        "hxxps://example.test/p1",
        "https://example.test/p1",
        "hxxps://example[.]test/p1?code=XXX",
        "hxxps://example[.]test/",
        "visit www.example.com now",
        "hxxps://other[.]test/p1",
    ):
        assert q.check_links(bad, LINK) == "link_malformed", bad


def test_phone_allowlist() -> None:
    ph = SPEC["allowed_phone"]
    assert q.check_phones(f"Call {ph} today", ph) is None
    for bad in ("call 971 50 123 4567", "call +971501234567", "call 0501234567", "call ٠٥٠١٢٣٤٥٦٧"):
        assert q.check_phones(bad, ph) == "phone_real_or_malformed", bad


def _item(text: str, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "text": text,
        "label": "scam",
        "language": "english",
        "subtype": "delivery_fee",
        "channel": "sms",
    }
    base.update(over)
    return base


def test_run_end_to_end_with_fake_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(q, "ROOT", tmp_path)
    spec = dict(SPEC)
    spec.update(
        count=2,
        batch_size=20,
        strata=[
            {
                "share": 1.0,
                "constraints": {"label": "scam", "language": "english"},
                "variant_field": "subtype",
                "variants": ["delivery_fee"],
            }
        ],
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    items = [
        {"text": "missing channel field here", "label": "scam", "language": "english", "subtype": "delivery_fee"},
        _item("Your parcel is held, pay the fee: hxxps://example[.]test/a1", label="legitimate"),
        _item("Your parcel is held, pay the fee: hxxps://example[.]test/a2", subtype="prize"),
        _item("طردك محجوز، يرجى دفع الرسوم الآن hxxps://example[.]test/a3"),
        _item("Your parcel is held, pay the fee: hxxps://example.test/a4"),
        _item("Your parcel is held, call 971 50 123 4567 to pay the fee"),
        _item("Your UAE Pass parcel is held, pay the fee: hxxps://example[.]test/a5"),
        _item("Your parcel is held. Pay AED 12 redelivery fee today to avoid return: hxxps://example[.]test/p1"),
        _item(
            "Dear customer, the courier could not reach you; the redelivery fee is AED 15: hxxps://example[.]test/ok1"
        ),
        _item("Hello, your shipment was stopped at the depot. Settle AED 9 here: hxxps://example[.]test/ok2"),
        _item("Hello, your shipment was stopped at the depot. Settle AED 9 here: hxxps://example[.]test/ok2"),
    ]

    def fake(*_a: object) -> str:
        return json.dumps({"items": items})

    args = argparse.Namespace(task="t-e2e", kind="synthetic_messages", spec=str(spec_path), seed=1, timeout=1.0)
    assert q.run(args, model_fn=fake) == 0

    out = tmp_path / "work" / "qwen" / "t-e2e"
    assert sorted(p.name for p in out.iterdir()) == ["manifest.json", "output.jsonl"]
    rows = [json.loads(line) for line in (out / "output.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert all(r["synthetic"] is True and r["task_id"] == "t-e2e" and r["kind"] == "synthetic_messages" for r in rows)
    assert not any("redelivery fee today to avoid return" in r["text"] for r in rows)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    c = m["counts"]
    assert m["audit"].startswith("PENDING") and m["synthetic"] is True and m["accepted"] == 2
    for reason in (
        "rejected_schema",
        "rejected_constraint",
        "rejected_subtype",
        "rejected_language_script",
        "rejected_link_malformed",
        "rejected_phone_real_or_malformed",
        "rejected_entity_not_allowed",
        "rejected_example_copy",
        "dedup_removed",
    ):
        assert c[reason] == 1, (reason, c)
    assert c["generated"] == len(items)


def test_parse_items_strips_prose_and_fences() -> None:
    assert q.parse_items('Sure!\n```json\n{"items": [{"a": 1}]}\n```') == [{"a": 1}]
