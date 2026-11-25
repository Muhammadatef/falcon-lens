#!/usr/bin/env python3
# ruff: noqa: E501  (script copy reads better unwrapped)
"""Generate submission/DEMO_SCRIPT.md: the pitch run-sheet (three-minute pitch and demo, then questions).

    uv run --with-requirements scripts/submission/requirements.txt python submission/build/demo_script.py [--check]

The spoken results line is filled from the newest published evaluation artifact, so the numbers in
the script are never typed. The text is scanned by scripts/submission/check_numbers.py in
`make submission`. The copy lives in demo_template.md; this file fills the numbers and the merged-or-planned beats.
"""

from __future__ import annotations

import argparse
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from submission import artifact as artifact_mod  # noqa: E402
from submission import capabilities as caps_mod  # noqa: E402
from submission import descriptions  # noqa: E402
from submission import evidence as evidence_mod  # noqa: E402

OUT = ROOT / "submission" / "DEMO_SCRIPT.md"


def pct(value: Any) -> str:
    return f"{(Decimal(str(value)) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def values(art: artifact_mod.Artifact | None) -> dict[str, str]:
    if art is None:
        return {
            "RESULTS_EN": "Our evaluation numbers come only from the evaluation run, and we show them only from that run.",
            "RESULTS_AR": "أرقام التقييم يولّدها تشغيل التقييم، ولا نعرضها إلا منه.",
            "ARTIFACT": "none published yet",
            "ASKED": "No live end-to-end figure is published yet. Say that evaluation is in progress.",
            "FP_SHORT": fp_short(None),
            **evidence_values(ROOT / "evals" / "results" / "published"),
        }
    m = dict(art.metrics)
    recall, fpr, official = pct(m["test.recall"]), pct(m["test.fpr"]), m["test.official_false_dangerous"]
    fp = artifact_mod.load_fp_regress(art.path.parent)
    asked = (
        f"The live end-to-end run on {fp['n']} held-out legitimate sites flagged {pct(fp['false_positive_rate']['value'])} of them as Suspicious or Dangerous, against our target of {pct(fp['target'])}. Say it plainly: it is above target, many of those runs could not complete every check, and fixing it is our top item. Do not hide it and do not round it."
        if fp
        else "No live end-to-end figure is published yet. Say that evaluation is in progress."
    )
    return {
        "FP_SHORT": fp_short(fp),
        "ASKED": asked,
        "RESULTS_EN": f"On our frozen test split: {recall} of phishing links caught, {fpr} of legitimate links wrongly flagged, and {official} official sites marked Dangerous.",
        "RESULTS_AR": f"على مجموعة الاختبار المجمّدة: كُشف {recall} من روابط الاحتيال، وأُنذر خطأً على {fpr} من الروابط السليمة، و{official} من المواقع الرسمية صُنّفت خطِرة.",
        "ARTIFACT": art.path.name,
        **evidence_values(art.path.parent),
    }


def fp_short(fp: dict[str, Any] | None) -> str:
    if not fp:
        return "no live figure is published yet; say that evaluation is in progress"
    return f"{pct(fp['false_positive_rate']['value'])} on {fp['n']} held-out sites, against a target of {pct(fp['target'])}"


def shipped(cap_id: str) -> bool:
    cap = next(c for c in caps_mod.CAPABILITIES if c.id == cap_id)
    return all(caps_mod.probe(ROOT, spec) for spec in cap.probes)


GATED = (
    (
        "evidence_pack",
        "Police evidence pack download (screenshot, WHOIS and RDAP, hosting, timestamps, hash manifest, takedown draft, STIX)",
    ),
    ("batch_check", "Batch URL checker (`make batch FILE=...`)"),
    ("hunter", "Proactive hunter (new look-alike domains from certificate logs)"),
    ("helpline_registry", "Official-number registry and fake-helpline flag"),
    ("voice_findings", "Voice and Check page speak the real per-check findings"),
    ("llm_route_selector", "Operator route selector on /ops"),
)


def gated_values() -> dict[str, str]:
    on = {cid: shipped(cid) for cid, _ in GATED}
    rows = ["| Item | State on main |", "|---|---|"]
    rows += [f"| {label} | {'on main' if on[cid] else 'PLANNED, not on main'} |" for cid, label in GATED]
    return {
        "STATUS_TABLE": "\n".join(rows),
        "FINDINGS_NOTE": "The falcon speaks the real findings of this check."
        if on["voice_findings"]
        else "The falcon speaks the result; speaking the real per-check findings is PLANNED, not on main, so do not promise it.",
        "EVIDENCE_BEAT": "Then click the evidence pack download and open its manifest: screenshot, WHOIS and RDAP, hosting and ASN, UTC timestamps, SHA-256 hashes, takedown draft, STIX."
        if on["evidence_pack"]
        else "The evidence pack download is PLANNED, not on main: do not click it; say it once under next thirty days.",
        "EVIDENCE_SAY": "One click gives the evidence pack: screenshot, WHOIS, hosting, UTC times and a hash manifest, with a takedown draft."
        if on["evidence_pack"]
        else "The incident exports as STIX; the one-click evidence pack is next.",
        "EVIDENCE_SAY_AR": "ونقرة واحدة تعطيك حزمة الأدلة: لقطة الشاشة وWHOIS والاستضافة والتوقيت وبصمات الملفات ومسودة الإزالة."
        if on["evidence_pack"]
        else "ويُصدَّر الحادث بصيغة STIX، وحزمة الأدلة بنقرة واحدة هي الخطوة التالية.",
        "RESULTS_NOTE": "If `/results` does not show the fresh two-hundred-site block, go back to the detection slide and read its not-on-feed row.",
        "HUNTER_BEAT": "Then one line on the proactive hunter: new look-alike domains found from certificate logs appear on `/campaigns`."
        if on["hunter"]
        else "The proactive hunter is PLANNED (its core code is on main, its runtime is not): do not demo it; say it once under next thirty days.",
        "HUNTER_QA": "A scheduled hunter also finds new look-alike domains from certificate logs."
        if on["hunter"]
        else "The hunter that goes looking for them ourselves is next-thirty-days work, not shipped.",
        "BATCH_ANSWER": "`make batch FILE=urls.txt` runs it live in two modes, strict (Suspicious counts as flagged) and lenient (only Dangerous), and prints a results table."
        if on["batch_check"]
        else "the batch checker is PLANNED, not on main; today we would submit them through the API one at a time.",
    }


def evidence_values(published: Path) -> dict[str, str]:
    ev = evidence_mod.load(published)
    fresh2 = ev.fresh_second_line()
    return {
        "FRESH_MAIN": ev.fresh_main_line() or "no fresh-test run is published",
        "FRESH_SECOND": fresh2 or "no fresh-test run is published",
        "FRESH_SECOND_SHORT": f"on hosts from a feed our stack does not query, {fresh2.split(': ', 1)[1]}"
        if fresh2
        else "no fresh-test run is published",
        "DEAD_PAGES": ev.fresh_dead_line() or "many listed pages were already offline",
        "VOICE": ev.voice_line() or "no voice benchmark is published",
        "VOICE_SPEED": ev.voice_speed() or "not published",
        "SOVEREIGN": ev.sovereign_line() or "no sovereign proof is published",
        "SOVEREIGN_SHORT": (ev.sovereign_line() or "no sovereign proof is published") + ".",
        "BRAND_SHORT": (ev.brand_new_line() or "no brand-new-page run is published").split(";")[0] + ", synthetic",
        "REDTEAM": ev.redteam_both() or "no red-team run is published",
        "MSG": ev.message_line() or "no message-text run is published",
        "BRAND": ev.brand_new_line() or "no brand-new-page run is published",
    }


TEMPLATE = (Path(__file__).with_name("demo_template.md")).read_text(encoding="utf-8")


def build(root: Path = ROOT) -> tuple[str, list[str]]:
    art = artifact_mod.load(root / "evals" / "results" / "published")
    text = TEMPLATE
    vals = {**gated_values(), **values(art)}
    for key, value in vals.items():
        text = text.replace("{" + key + "}", value)
    return text, [f"DEMO_SCRIPT: {e}" for e in descriptions.wording_errors(strip_rules(text))]


def strip_rules(text: str) -> str:
    """The do-not section has to mention the forbidden word to forbid it: drop that one line before the wording check."""
    return "\n".join(line for line in text.splitlines() if "Say the word" not in line)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text, problems = build(args.root.resolve())
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    if problems:
        return 1
    if args.check:
        if not args.out.is_file() or args.out.read_text(encoding="utf-8") != text:
            print(f"ERROR: {args.out} is out of date: run `make submission`", file=sys.stderr)
            return 1
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
