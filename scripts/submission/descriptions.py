# ruff: noqa: E501  (copy and tables read better unwrapped)
"""Compose and check the submission descriptions (English and Arabic).

Each sentence is tied to capability ids (scripts/submission/capabilities.py). A sentence is
used only when its capabilities are shipped in this checkout, so the description cannot claim
something that is not built. While the end-to-end check is not shipped the lead sentence says
"in development" instead of describing a working product.

Form limits: 2 to 4 sentences and at most 600 characters, counted as Unicode code points
after NFC normalisation. `check()` enforces them and the wording rules from CLAUDE.md.

Usage:
    python scripts/submission/descriptions.py            # print both descriptions
    python scripts/submission/descriptions.py --check F  # check a description file

Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections.abc import Mapping
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make `submission` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MAX_CHARS = 600
MIN_SENTENCES = 2
MAX_SENTENCES = 4
TITLE = "Falcon Lens | عدسة الصقر"

# Wording rules (CLAUDE.md). "Safe Browsing" is a product name and is exempt.
_SAFE_EN = re.compile(r"\bsafe\b(?!\s+browsing)", re.IGNORECASE)
_SAFE_AR = re.compile(r"(?<![؀-ۿ])(?:ال)?آمن(?:ة|اً)?(?![؀-ۿ])")
# Phrases that would imply a relationship with the police. They are allowed only when the
# same sentence negates them ("not affiliated", "ليس تابعاً", "غير تابع", ...).
_ENDORSE = re.compile(
    r"endorsed by|approved by|partner(?:ed|ship)? with|in cooperation with|integrated with|used by"
    r"|affiliated with|official (?:tool|app|partner)|معتمد|بالتعاون مع|بالشراكة مع|تابع ل",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\bnot\b|\bno\b|\bnever\b|غير|ليس|لا |دون|ولا", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+")

KIND_EN = {"url_check": "link", "message_check": "message", "email_check": "email", "image_check": "image"}
KIND_AR = {"url_check": "رابطاً", "message_check": "رسالة", "email_check": "بريداً إلكترونياً", "image_check": "صورة"}


def count_chars(text: str) -> int:
    return len(unicodedata.normalize("NFC", text))


def sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_END.split(text.strip()) if part]


def wording_errors(text: str) -> list[str]:
    """Wording rules shared by every generated text (descriptions, deck, document)."""
    errors = []
    if _SAFE_EN.search(text):
        errors.append('contains the word "safe" (the lowest verdict is "No warning signs found")')
    if _SAFE_AR.search(text):
        errors.append("contains «آمن» (the lowest verdict is «لم نجد علامات تحذير»)")
    for sentence in re.split(r"(?<=[.!?؟\n])", text):
        if _ENDORSE.search(sentence) and not _NEGATION.search(sentence):
            errors.append(f"implies a relationship with a police or official body: {sentence.strip()[:80]!r}")
    return errors


def check(text: str) -> list[str]:
    """Problems with one description. An empty list means it fits the form field."""
    errors = []
    stripped = text.strip()
    if not stripped:
        return ["description is empty"]
    length = count_chars(stripped)
    if length > MAX_CHARS:
        errors.append(f"too long: {length} characters, limit {MAX_CHARS}")
    count = len(sentences(stripped))
    if not MIN_SENTENCES <= count <= MAX_SENTENCES:
        errors.append(f"{count} sentences, expected {MIN_SENTENCES} to {MAX_SENTENCES}")
    if "\n" in stripped:
        errors.append("contains a line break (the form field is one paragraph)")
    errors.extend(wording_errors(stripped))
    return errors


def _join_en(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def _kinds(caps: Mapping[str, bool], names: Mapping[str, str]) -> list[str]:
    return [name for cap, name in names.items() if caps.get(cap)]


def _candidates_en(caps: Mapping[str, bool]) -> list[tuple[int, list[str]]]:
    """(priority, [long form, shorter forms...]); each candidate is ONE sentence; priority 0 is never dropped."""
    mvp = bool(caps.get("url_check"))
    out: list[tuple[int, list[str]]] = []
    if caps.get("url_check"):
        kinds = _join_en(_kinds(caps, KIND_EN))
        out.append(
            (
                0,
                [
                    f"Falcon Lens is an Arabic-first AI agent for UAE residents: paste a suspicious {kinds} and get "
                    "an evidence-backed verdict with what was found, why, and what to do now.",
                    f"Falcon Lens is an Arabic-first AI agent: paste a suspicious {kinds} and get an "
                    "evidence-backed verdict with what was found, why, and what to do now.",
                ],
            )
        )
    else:
        out.append(
            (
                0,
                [
                    "Falcon Lens is an Arabic-first AI agent, still in development, that will check suspicious "
                    "links, messages and emails for UAE residents and answer with evidence.",
                ],
            )
        )
        out.append((0, ["The end-to-end check is not finished in this build."]))
        if caps.get("sentinel_agent"):
            out.append(
                (
                    2,
                    [
                        "Its second agent, the Sentinel, already links check events (replayed in this build) into "
                        "incidents and drafts takedowns that wait for human approval.",
                        "Its second agent, the Sentinel, already links replayed check events into incidents.",
                    ],
                )
            )
        elif caps.get("sentinel_rules"):
            out.append((2, ["Built so far: Sentinel correlation rules."]))
    if mvp and caps.get("brand_check"):
        out.append(
            (
                1,
                [
                    "A brand check flags pages that imitate a known organisation on a domain it does not own, even "
                    "when no blocklist lists them; code, not a model, sets the score.",
                    "A brand check flags lookalike pages even when no blocklist lists them; code, not a model, "
                    "sets the score.",
                ],
            )
        )
    if mvp and caps.get("sentinel_agent"):
        out.append(
            (
                2,
                [
                    "A second agent, the Sentinel (Dir' | درع), links checks into campaigns, blocks indicators internally and "
                    "drafts takedowns that wait for human approval.",
                    "A second agent, the Sentinel, links checks into campaigns and drafts takedowns for human "
                    "approval.",
                ],
            )
        )
    clauses = []
    if caps.get("sovereign"):
        clauses.append("can keep every model call local")
    interfaces = [name for cap, name in (("rest_api", "REST"), ("mcp", "MCP")) if caps.get(cap)]
    if interfaces:
        if len(interfaces) > 1:
            clauses.append(f"offers {' and '.join(interfaces)} interfaces that are ready to connect to police systems")
        else:
            clauses.append(f"offers a {interfaces[0]} interface that is ready to connect to police systems")
    lead = f"It {' and '.join(clauses)}; it" if clauses else "It"
    disclaimer = "is an independent project, not connected to or affiliated with Abu Dhabi Police."
    out.append((0, [f"{lead} {disclaimer}", f"It {disclaimer}"]))
    return out


def _candidates_ar(caps: Mapping[str, bool]) -> list[tuple[int, list[str]]]:
    mvp = bool(caps.get("url_check"))
    out: list[tuple[int, list[str]]] = []
    if caps.get("url_check"):
        kinds = " أو ".join(_kinds(caps, KIND_AR))
        out.append(
            (
                0,
                [
                    f"«عدسة الصقر» وكيل ذكاء اصطناعي صُمّم بالعربية أولاً لسكان الإمارات: الصق {kinds} تشكّ فيه، "
                    "فيعطيك حكماً مدعوماً بالأدلة يبيّن ماذا وجد، ولماذا، وماذا تفعل الآن.",
                    f"«عدسة الصقر» وكيل ذكاء اصطناعي صُمّم بالعربية أولاً: الصق {kinds} تشكّ فيه، فيعطيك حكماً "
                    "مدعوماً بالأدلة يبيّن ماذا وجد، ولماذا، وماذا تفعل الآن.",
                ],
            )
        )
    else:
        out.append(
            (
                0,
                [
                    "«عدسة الصقر» وكيل ذكاء اصطناعي صُمّم بالعربية أولاً، وما زال قيد التطوير، وسيفحص الروابط والرسائل "
                    "ورسائل البريد المشبوهة لسكان الإمارات ويجيب بالأدلة.",
                ],
            )
        )
        out.append((0, ["الفحص الكامل من البداية إلى النهاية لم يكتمل في هذه النسخة."]))
        if caps.get("sentinel_agent"):
            out.append(
                (
                    2,
                    [
                        "ووكيله الثاني «درع» يربط منذ الآن أحداث الفحص (المُعاد تشغيلها في هذه النسخة) في حوادث، "
                        "ويُعدّ مسودات طلبات الإزالة بانتظار موافقة بشرية.",
                        "ووكيله الثاني «درع» يربط منذ الآن أحداث الفحص المُعاد تشغيلها في حوادث.",
                    ],
                )
            )
        elif caps.get("sentinel_rules"):
            out.append((2, ["أُنجز حتى الآن: قواعد الربط في «درع»."]))
    if mvp and caps.get("brand_check"):
        out.append(
            (
                1,
                [
                    "يكشف فحص الهوية الصفحات التي تنتحل اسم جهة معروفة على نطاق لا تملكه، حتى لو لم تُدرج في أي قائمة "
                    "حظر، والدرجة يحسبها محكّم حتمي لا نموذج لغوي.",
                    "يكشف فحص الهوية الصفحات المنتحِلة حتى لو لم تُدرج في أي قائمة حظر، والدرجة يحسبها محكّم حتمي لا "
                    "نموذج لغوي.",
                ],
            )
        )
    if mvp and caps.get("sentinel_agent"):
        out.append(
            (
                2,
                [
                    "وكيل ثانٍ اسمه «درع» (Dir') يربط الفحوص المتشابهة في حملات، ويحظر المؤشرات داخلياً، ويُعدّ مسودات طلبات "
                    "الإزالة ولا يرسلها قبل موافقة بشرية.",
                    "وكيل ثانٍ اسمه «درع» يربط الفحوص المتشابهة في حملات ويُعدّ مسودات طلبات الإزالة بانتظار موافقة "
                    "بشرية.",
                ],
            )
        )
    clauses = []
    if caps.get("sovereign"):
        clauses.append("يمكن تشغيل نماذجه كلها محلياً")
    interfaces = [name for cap, name in (("rest_api", "REST"), ("mcp", "MCP")) if caps.get(cap)]
    if len(interfaces) == 2:
        clauses.append("يوفّر واجهتي REST و MCP الجاهزتين للربط مع أنظمة الشرطة")
    elif interfaces:
        clauses.append(f"يوفّر واجهة {interfaces[0]} الجاهزة للربط مع أنظمة الشرطة")
    disclaimer = "مشروع مستقل، غير مربوط بشرطة أبوظبي وغير تابع لها."
    if clauses:
        out.append((0, [f"{'، و'.join(clauses)}، وهو {disclaimer}", f"وهو {disclaimer}"]))
    else:
        out.append((0, [f"وهو {disclaimer}"]))
    return out


def _fit(candidates: list[tuple[int, list[str]]]) -> str:
    """Longest combination that fits: shorten optional sentences first, then drop them."""
    choice = [0] * len(candidates)
    keep = [True] * len(candidates)

    def text() -> str:
        return " ".join(
            forms[min(i, len(forms) - 1)] for (_, forms), i, k in zip(candidates, choice, keep, strict=True) if k
        )

    def fits() -> bool:
        current = text()
        return count_chars(current) <= MAX_CHARS and len(sentences(current)) <= MAX_SENTENCES

    order = sorted(range(len(candidates)), key=lambda i: -candidates[i][0])  # least important first
    for index in order:  # 1) shorter forms, least important sentence first
        while not fits() and choice[index] < len(candidates[index][1]) - 1:
            choice[index] += 1
    for index in order:  # 2) drop optional sentences
        if fits():
            break
        if candidates[index][0] > 0:
            keep[index] = False
    return text()


def compose(caps: Mapping[str, bool], lang: str) -> str:
    if lang == "en":
        return _fit(_candidates_en(caps))
    if lang == "ar":
        return _fit(_candidates_ar(caps))
    raise ValueError(f"unknown language {lang!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose or check the submission descriptions.")
    parser.add_argument("--check", type=Path, nargs="+", help="description files to check")
    args = parser.parse_args(argv)
    if args.check:
        failed = False
        for path in args.check:
            text = path.read_text(encoding="utf-8")
            errors = check(text)
            state = "FAIL" if errors else "ok"
            print(f"[{state}] {path}: {count_chars(text.strip())}/{MAX_CHARS} chars, {len(sentences(text))} sentences")
            for error in errors:
                print(f"       {error}", file=sys.stderr)
            failed = failed or bool(errors)
        return 1 if failed else 0

    from submission import capabilities  # noqa: PLC0415

    caps = capabilities.detect()
    for lang in ("en", "ar"):
        text = compose(caps, lang)
        print(f"--- {lang} ({count_chars(text)}/{MAX_CHARS} chars)\n{text}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
