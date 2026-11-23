"""Arabic clarity of the verdict text: a 30-item rating sheet for a native speaker plus automated checks.

Clarity cannot be fully automated. This module (1) assembles 30 verdict screens exactly as the shipped catalog
renders them (verdict label, one reason, the 'what to do now' actions), (2) runs deterministic checks (length against a
phone-screen budget, reading-level proxies, forbidden words, digits, Latin letters, links), and (3) writes a CSV for a
native speaker to fill in. Until a filled sheet is ingested the human result is ``pending_human_rating``.

The pairing of a verdict label with a reason is illustrative: it follows the hard-rule or signal polarity of the reason
(a hard rule's effect; trust reasons go with 'no warning signs', risk reasons with 'suspicious').
It shows wording; it is not a measurement of detection.

Ingest: ``python -m evals.gaps arabic --ingest filled.csv`` computes mean clarity (bootstrap 95% CI) and the share who
'would know what to do'.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from evals.common import ROOT
from evals.gaps.common import PUBLISHED, envelope, mean_ci, not_evaluated, rate
from falcon_core.i18n import load_catalog

# Phone budget: about 45 Arabic characters fit on one line of a 360 px wide phone at body size; the sheet allows a
# reason of at most two lines (90 characters) and a single action of at most two lines. Assumption recorded in DECISIONS.md.  # noqa: E501
CHARS_PER_LINE = 45
MAX_LINES = 2
MAX_CHARS = CHARS_PER_LINE * MAX_LINES
FORBIDDEN = ("آمن", "أمان", "سليم", "مضمون", "موثوق")
HARD_VERDICT = {
    "H1": "dangerous",
    "H2": "dangerous",
    "H3": "no_warning_signs",
    "H4": "dangerous",
    "H5": "dangerous",
    "H5s": "suspicious",
    "H6": "suspicious",
}
TRUST_REASONS = {"domain.age.old", "registry.verified_official"}
SHEET = PUBLISHED / "arabic_clarity" / "rating_sheet.csv"
AR_WORD = re.compile(r"[ء-ي]+")
SENT = re.compile(r"[.!؟?؛]+")


def _verdict_for(section: str, key: str) -> str:
    if section == "hard_rules":
        return HARD_VERDICT.get(key, "suspicious")
    return "no_warning_signs" if key in TRUST_REASONS else "suspicious"


def build_items(n: int = 30) -> list[dict[str, str]]:
    cat = load_catalog("ar")
    pool: list[tuple[str, str, str]] = [("hard_rules", k, t) for k, t in cat.hard_rules.items()]
    # reasons ordered by how often the shipped scoring can emit them: message/page/url signals first
    order = [
        "page.",
        "url.",
        "brand.",
        "message.rule.",
        "message.",
        "domain.",
        "visual.",
        "registry.",
        "rep.",
        "email.",
        "injection.",
    ]
    rs = sorted(
        cat.reasons.items(), key=lambda kv: min((i for i, p in enumerate(order) if kv[0].startswith(p)), default=99)
    )
    pool += [("reasons", k, t) for k, t in rs]
    out: list[dict[str, str]] = []
    for section, key, text in pool[:n]:
        v = _verdict_for(section, key)
        now = " ".join(cat.actions[v]["now"])  # type: ignore[index]
        out.append(
            {
                "item_id": f"ar-{len(out) + 1:02d}",
                "template_key": f"{section}.{key}",
                "verdict_label_ar": cat.verdict[v],  # type: ignore[index]
                "reason_ar": text,
                "what_to_do_now_ar": now,
            }
        )
    return out


def auto_checks(items: list[dict[str, str]]) -> dict[str, Any]:
    reason_len = [len(i["reason_ar"]) for i in items]
    action_each = [len(a) for i in items for a in [x.strip() for x in SENT.split(i["what_to_do_now_ar"]) if x.strip()]]
    words = [w for i in items for w in AR_WORD.findall(i["reason_ar"])]
    sents = [s for i in items for s in SENT.split(i["reason_ar"]) if s.strip()]
    long_words = [w for w in words if len(w) >= 7]
    all_text = " ".join(i["reason_ar"] + " " + i["what_to_do_now_ar"] + " " + i["verdict_label_ar"] for i in items)
    return {
        "phone_budget": {
            "chars_per_line": CHARS_PER_LINE,
            "max_lines": MAX_LINES,
            "max_chars": MAX_CHARS,
            "basis": "assumption, see DECISIONS.md",
        },
        "reason_within_budget": rate(sum(1 for x in reason_len if x <= MAX_CHARS), len(reason_len)),
        "each_action_sentence_within_budget": rate(sum(1 for x in action_each if x <= MAX_CHARS), len(action_each)),
        "reason_chars": {
            "min": min(reason_len),
            "max": max(reason_len),
            "mean": mean_ci([float(x) for x in reason_len]),
        },
        "reading_level_proxy": {
            "words_per_sentence": mean_ci([float(len(AR_WORD.findall(s))) for s in sents]),
            "letters_per_word": mean_ci([float(len(w)) for w in words]),
            "share_long_words_7plus_letters": round(len(long_words) / max(1, len(words)), 4),
            "note": "proxies only: shorter sentences and shorter words usually read easier; they do not measure comprehension",  # noqa: E501
        },
        "forbidden_words_present": [w for w in FORBIDDEN if w in all_text],
        "digits_present": bool(re.search(r"\d", all_text)),
        "latin_letters_present": sorted(set(re.findall(r"[A-Za-z]+", all_text))),
        "links_present": bool(re.search(r"https?://|www\.", all_text, re.I)),
    }


def write_sheet(items: list[dict[str, str]], path: Path = SHEET) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "item_id",
        "template_key",
        "verdict_label_ar",
        "reason_ar",
        "what_to_do_now_ar",
        "clarity_1_to_5",
        "would_know_what_to_do_yes_no",
        "comment",
        "rater",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i in items:
            w.writerow({**i, "clarity_1_to_5": "", "would_know_what_to_do_yes_no": "", "comment": "", "rater": ""})
    return path


def ingest(path: Path) -> dict[str, Any]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    clar = [float(r["clarity_1_to_5"]) for r in rows if r.get("clarity_1_to_5", "").strip()]
    know = [
        r["would_know_what_to_do_yes_no"].strip().lower()
        for r in rows
        if r.get("would_know_what_to_do_yes_no", "").strip()
    ]
    raters = sorted({r["rater"].strip() for r in rows if r.get("rater", "").strip()})
    if len(clar) < len(rows) or len(know) < len(rows):
        return {"status": "partially_rated", "rated": min(len(clar), len(know)), "of": len(rows)}
    return {
        "status": "rated",
        "raters": len(raters),
        "items": len(rows),
        "clarity_1_to_5": mean_ci(clar),
        "share_rating_4_or_5": rate(sum(1 for c in clar if c >= 4), len(clar)),
        "would_know_what_to_do": rate(sum(1 for k in know if k in ("yes", "y", "نعم")), len(know)),
    }


def report(filled: Path | None = None) -> dict[str, Any]:
    items = build_items(30)
    sheet = write_sheet(items)
    human: dict[str, Any] = (
        ingest(filled)
        if filled
        else {
            "status": "pending_human_rating",
            "sheet": str(sheet.relative_to(ROOT)),
            "rating_scale": "clarity 1 (unclear) to 5 (very clear); would you know what to do: yes/no",
        }
    )
    body = {
        "items": len(items),
        "human_rating": human,
        "automated_checks": auto_checks(items),
        "what_is_rated": "verdict label + one reason + the 'what to do now' actions, as the shipped catalog renders them (template-only text)",  # noqa: E501
        "pairing_note": "label/reason pairing is illustrative (by rule effect or signal polarity), not an observed verdict",  # noqa: E501
        "not_evaluated_yet": not_evaluated(
            "comprehension and clarity need a native-speaker rating; none is recorded in this artifact"
        )
        if not filled
        else None,
    }
    return envelope(
        "arabic_clarity",
        scope="Arabic verdict text: 30-item native-speaker rating sheet + automated phone-fit and reading-level checks",
        provenance="shipped Arabic catalog templates (not model output)",
        n={"items": len(items)},
        route="none",
        model_ids={"llm": "none (template-only text, L1 decision D3)"},
        body=body,
    )
