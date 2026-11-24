#!/usr/bin/env python3
# ruff: noqa: E501  (copy and tables read better unwrapped)
"""Fail if a number in the deck, the description document, the README or DEMO.md cannot be traced.

Truthfulness rule (CLAUDE.md): every metric shown anywhere comes from a generated eval
artifact. This script reads the text of

    submission/FalconLens_ScamShield.pptx  (slide and notes XML, standard library zipfile)
    submission/DEMO_SCRIPT.md
    submission/description.pdf     (pypdf when installed; `make submission` installs it)
    submission/description.html    (the exact source the PDF was rendered from)
    docs/assets/architecture.svg   (its <text> nodes: the image is embedded in the deck and the PDF)
    README.md, docs/DEMO.md        (when they exist)

and requires every number in them to be one of:

1. **A metric value of the newest published artifact**: a numeric leaf under the top-level
   `metrics` key of the newest `evals/results/published/*.json`. A document number written with
   d decimals matches a value v when round(v, d) equals it. A percentage also matches
   round(100 * v, d) for 0 <= v <= 1. Digits that merely occur inside a git SHA, a timestamp,
   a hash or a key do NOT make a number traceable.
2. **Part of an identifier**: the digits directly follow an ASCII letter or underscore, as in
   `T0`, `H1`, `R5`, `G6`, `v1`, `MV3`, `p95`. Or the whole word equals a string value of the
   artifact (a model id, a timestamp), or is a hexadecimal prefix (7+ characters) of one (a
   short git SHA).
3. **Covered by a context pattern** in `ALLOWED_CONTEXTS`: a short, reviewed list of exact
   non-metric phrases, each with its reason. The patterns are anchored to the phrase they
   cover. There is no generic "limit", "duration" or "time" pattern, because a speed claim is
   a metric: latency must come from the artifact, or be a design budget that the text itself
   labels "design budget". **A percentage is never allowed this way.**

Percent markers: `%`, `٪`, `％`, "percent", "per cent", «بالمئة», «في المئة», «بالمائة».
Text is NFKC-normalised first, so full-width and superscript digits and Arabic-Indic digits are
read as digits. An Arabic letter attached to a number («و٩٨٪») does not hide it.

**Number words** in English and Arabic ("ninety-eight", «ثمانية وتسعون») are flagged when they
stand next to a percent marker or a metric word (recall, precision, accuracy, detection,
latency, «دقة», «كشف», «نسبة», ...). Plain counts in words ("six scenarios") are not flagged.

Before scanning Markdown: fenced code blocks, link targets, HTML tags and comments, and
ordered-list markers are removed. Inline code is removed too unless it contains a percent
marker, in which case it is scanned like prose.

With no published artifact, rule 1 matches nothing, so any statistic fails. That is intended.

Exit status: 0 traceable, 1 untraceable numbers found, 2 a required file is missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: make `submission` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from submission import artifact as artifact_mod  # noqa: E402
from submission import evidence as evidence_mod  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_SVG = "docs/assets/architecture.svg"
DECK_NAMES = ("FalconLens_ScamShield.pptx", "deck.pptx")  # the committed deck; the old name is kept for older checkouts

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_DUR = r"\d+(?:\.\d+)? ?m?s"

# (regex, reason). Every number inside a match is exempt unless it carries a percent marker.
# Keep each pattern anchored to the exact phrase it is for. Never add a generic unit pattern.
ALLOWED_CONTEXTS: tuple[tuple[str, str], ...] = (
    (r"STIX\s+2\s*\.\s*1", "version of the STIX standard (PDF text extraction may space the dot)"),
    (r"Abu Dhabi Police (?:x|×) 42\b(?! (?:incidents|scams|cases|reports|campaigns|checks))", "organiser name"),
    (r"\bRFC ?\d{3,5}\b", "RFC reference"),
    (r"\bPython 3\.\d+\b", "language version from .python-version"),
    (r"\bManifest V3\b", "Chrome extension platform name"),
    (r"\bFable 5\.2\b|\bInkling-2-Mini\b", "model names as recorded in DECISIONS.md"),
    (
        rf"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,? \d{{1,2}} {_MONTH}(?: \d{{4}})?(?: \d{{2}}:\d{{2}})?",
        "calendar date, with an optional clock time",
    ),
    (rf"\b\d{{1,2}} {_MONTH} \d{{4}}\b", "calendar date"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "ISO date"),
    (r"\b\d:\d{2} to \d:\d{2}\b|من \d:\d{2} إلى \d:\d{2}", "shot-list or pitch timestamp range in docs/DEMO.md"),
    (
        r"\b60-second (?:video|shot list)\b|\b3-minute pitch\b",
        "length of the video and of the pitch, set by the organiser format",
    ),
    (r"(?i:≤|at most) ?600 characters\b|\b600 code points\b", "description field limit of the submission form"),
    (r"(?i:≤|at most|limit:?|under) ?20 MB\b|\b20 MB limit\b", "file size limit of the submission form"),
    (r"#\d+\b", "pull request or issue reference"),
    (r"\b[A-Z]{1,5}-\d+\b", "document, task or review identifier such as ADR-001 or T-012"),
    (r"\bPhase \d(?: (?:to|→) \d)?\b", "project phase from STATUS.md"),
    (rf"{_DUR} \(design budget\)", "tier budget from ADR-001, labelled as a design budget in the text"),
    (
        rf"design budgets?(?::| ·)? {_DUR}(?:(?: ·|,| and) {_DUR})*",
        "tier budgets from ADR-001, labelled as design budgets in the text",
    ),
    (
        r"(?i:≤|at most) ?6 tool calls\b",
        "investigator bound enforced by code (contracts/tools.schema.json), not a measurement",
    ),
    (r"\bports 80 and 443\b", "egress proxy port allow-list (configuration)"),
    (r"\b[A-Z]\d\s?(?:to|–|-|→)\s?[A-Z]?\d\b", "identifier range such as T0 to T3 or R1-R5"),
    (r"\b[Ss]cenarios? [1-6](?:(?:,| to| and) [1-6])*\b(?! ?(?:%|percent))", "scenario label in docs/DEMO.md"),
    (r"\bstep [1-9]\b", "step label in docs/DEMO.md"),
    (r"(?m)^\| ?[1-9] ?\|", "step or scenario number in the first cell of a docs/DEMO.md table row"),
)
_ALLOWED = tuple((re.compile(pattern), reason) for pattern, reason in ALLOWED_CONTEXTS)

_PERCENT = r"(?:%|٪|per\s?cent\b|بالمئة|في المئة|بالمائة|في المائة)"
_PERCENT_RE = re.compile(_PERCENT, re.IGNORECASE)
# Identifier rule: digits glued to an ASCII letter or underscore are not numbers (T0, v1, p95).
# The lookbehind is ASCII-only on purpose: an attached Arabic letter must not hide a number.
_NUMBER = re.compile(
    rf"(?:(?<![A-Za-z_0-9.])\d+(?:[.,]\d+)*|(?<![A-Za-z_0-9])\.\d+)(?:\s?{_PERCENT})?",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z0-9_.:+-]+")

_EN_UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_EN_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_EN_WORD = "(?:(?!zero[- ]day)(?:" + "|".join(_EN_UNITS + _EN_TENS + ["hundred", "thousand"]) + "))"
_AR_WORD = (
    "(?:و?(?:ال)?(?:صفر|واحد|واحدة|اثنان|اثنين|اثنتان|ثلاثة|ثلاث|أربعة|أربع|خمسة|خمس|ستة|ست|سبعة|سبع|ثمانية|ثمان|ثماني|تسعة|تسع"
    "|عشرة|عشر|عشرون|عشرين|ثلاثون|ثلاثين|أربعون|أربعين|خمسون|خمسين|ستون|ستين|سبعون|سبعين|ثمانون|ثمانين|تسعون|تسعين"
    "|مئة|مائة|مئتان|مئتين|ألف|آلاف))"
)
_NUMBER_WORDS = re.compile(
    rf"\b{_EN_WORD}(?:[\s-]+(?:and[\s-]+)?{_EN_WORD})*\b|(?<![\u0600-\u06FF]){_AR_WORD}(?:\s+{_AR_WORD})*(?![\u0600-\u06FF])",
    re.IGNORECASE,
)
_METRIC_WORD = re.compile(
    r"\b(?:recall|precision|accuracy|accurate|f1|fpr|false[- ]positives?|false[- ]negatives?|detection|detects?|catch(?:es)?|caught|latency|faster|slower)\b"
    r"|دقة|الدقة|كشف|الكشف|نسبة|النسبة|معدل|المعدل|استدعاء|إنذارات",
    re.IGNORECASE,
)
_NEAR = 30  # characters either side of a number word that count as "next to"


@dataclass(frozen=True)
class Finding:
    source: str
    token: str
    context: str

    def __str__(self) -> str:
        return f"{self.source}: {self.token!r} in “…{self.context}…”"


# ── text extraction ──────────────────────────────────────────────────────────
def normalise(text: str) -> str:
    """NFKC (full-width and superscript forms), then every Unicode decimal digit to ASCII."""
    text = unicodedata.normalize("NFKC", text)
    out = []
    for char in text:
        if char.isdigit() and not char.isascii():
            try:
                out.append(str(unicodedata.digit(char)))
                continue
            except ValueError:
                pass
        out.append(char)
    return "".join(out).replace("٫", ".").replace("٬", ",")


def _inline_code(match: re.Match[str]) -> str:
    body = match.group(1)
    return f" {body} " if _PERCENT_RE.search(unicodedata.normalize("NFKC", body)) else " "


def strip_markdown(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$", " ", text)
    text = re.sub(r"`([^`\n]*)`", _inline_code, text)  # kept when it holds a percentage
    text = re.sub(r"\]\([^)\s]*\)", "]", text)  # link targets
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", text)  # ordered-list markers
    return re.sub(r"<[^>\n]+>", " ", text)  # HTML tags, with their attributes


def strip_html(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"(?is)<(style|script|svg)\b.*?</\1>", " ", text)
    text = re.sub(r"(?is)<code\b[^>]*>(.*?)</code>", _inline_code, text)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#37;", "%")):
        text = text.replace(entity, char)
    return text


def _unescape(text: str) -> str:
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(entity, char)
    return text


def _natural(name: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def pptx_text(path: Path) -> str:
    """All text runs of every slide and notes page in deck order, one paragraph per line."""
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            (n for n in archive.namelist() if re.match(r"ppt/(slides|notesSlides)/[^/]+\.xml$", n)), key=_natural
        )
        for name in names:
            xml = archive.read(name).decode("utf-8")
            for paragraph in re.findall(r"<a:p\b.*?</a:p>", xml, flags=re.DOTALL):
                runs = re.findall(r"<a:t>([^<]*)</a:t>", paragraph)
                if runs:
                    parts.append("".join(runs))
    return _unescape("\n".join(parts))


def svg_text(text: str) -> str:
    """The <title>, <desc> and <text> content of an SVG. Text nodes on one source line are joined with ' · '."""
    lines = []
    for line in text.splitlines():
        nodes = re.findall(r"<(?:text|title|desc)\b[^>]*>(.*?)</(?:text|title|desc)>", line)
        if nodes:
            lines.append(" · ".join(re.sub(r"<[^>]+>", "", node).strip() for node in nodes))
    return _unescape("\n".join(lines))


def pdf_text(path: Path) -> str | None:
    """Text of the PDF, or None when pypdf is not installed."""
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        return None
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    # Text extraction can put spaces around a decimal point ("0 . 98"); rejoin so the number is read whole.
    return re.sub(r"(?<=\d) ?\. ?(?=\d)", ".", text)


# ── tracing ──────────────────────────────────────────────────────────────────
def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


class Traceable:
    """What the newest published artifact can vouch for: its metric values and its whole strings."""

    def __init__(
        self,
        data: dict[str, Any] | None,
        names: tuple[str, ...] = (),
        extra: dict[str, Any] | None = None,
        claimed: tuple[float, ...] = (),
    ) -> None:
        """`names`: the artifact's own file name and stem, which a "Source:" line may quote.

        `extra`: the newest `fp_regress` run (artifact.load_fp_regress). Its numeric leaves count as metrics too,
        except the per-item rows.
        """
        self.values: list[Decimal] = []
        self.strings: set[str] = {name.lower() for name in names if name}
        for leaf in claimed:  # only the values evidence.py reads (evidence.Evidence.claimed_values), not whole artifacts
            value = _decimal(json.dumps(leaf))
            if value is not None and value.is_finite():
                self.values.append(value)
        for source in [extra] if extra is not None else []:
            for _key, leaf in artifact_mod.flatten({k: v for k, v in source.items() if k not in ("items", "_file")}):
                if isinstance(leaf, int | float) and not isinstance(leaf, bool):
                    value = _decimal(json.dumps(leaf))
                    if value is not None and value.is_finite():
                        self.values.append(value)
                elif isinstance(leaf, str) and leaf.strip():
                    self.strings.add(leaf.strip().lower())
        if data is None:
            return
        for _key, leaf in artifact_mod.flatten(data.get("metrics") if isinstance(data.get("metrics"), dict) else {}):
            if isinstance(leaf, int | float) and not isinstance(leaf, bool):
                value = _decimal(json.dumps(leaf))
                if value is not None and value.is_finite():
                    self.values.append(value)
        for _key, leaf in artifact_mod.flatten(data):
            if isinstance(leaf, str) and leaf.strip():
                self.strings.add(leaf.strip().lower())

    def has_number(self, token: str) -> bool:
        percent = bool(_PERCENT_RE.search(token))
        body = _PERCENT_RE.sub("", token).strip().lstrip("+")
        candidates = {body.replace(",", "")}  # 1,234 as a thousands separator
        if body.count(",") == 1 and "." not in body:
            candidates.add(body.replace(",", "."))  # 0,97 as a decimal comma
        for text in candidates:
            number = _decimal("0" + text if text.startswith(".") else text)
            if number is None:
                continue
            exponent = number.as_tuple().exponent
            places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
            quantum = Decimal(1).scaleb(-places)
            for value in self.values:
                for rounding in (ROUND_HALF_EVEN, ROUND_HALF_UP):  # either convention a formatter may use
                    if value.quantize(quantum, rounding=rounding) == number:
                        return True
                    if percent and 0 <= value <= 1 and (value * 100).quantize(quantum, rounding=rounding) == number:
                        return True
        return False

    def has_word(self, word: str) -> bool:
        """The whole word is an artifact string, or a hex prefix (7+ chars) of one: a short git SHA."""
        word = word.strip(".:,").lower()
        if not word:
            return False
        if word in self.strings:
            return True
        if len(word) >= 7 and re.fullmatch(r"[0-9a-f]+", word):
            # a prefix of a hash value; a suffix such as "-dirty" after the hash is ignored
            heads = (re.match(r"[0-9a-f]+", s) for s in self.strings)
            return any(len(m.group()) >= 7 and m.group().startswith(word) for m in heads if m)
        return False


def traceable_for(loaded: artifact_mod.Artifact | None, published: Path | None = None) -> Traceable:
    root = published or artifact_mod.PUBLISHED
    extra = artifact_mod.load_fp_regress(root)
    more = tuple(evidence_mod.load(root).claimed_values())  # only the figures the documents quote from the other families
    if loaded is None:
        return Traceable(None, extra=extra, claimed=more)
    return Traceable(loaded.data, names=(loaded.path.name, loaded.path.stem), extra=extra, claimed=more)


def find_untraceable(text: str, traceable: Traceable, source: str) -> list[Finding]:
    """Numbers in already-stripped text that no rule accounts for."""
    text = normalise(text)
    exempt: list[tuple[int, int]] = []
    for pattern, _reason in _ALLOWED:
        exempt.extend(match.span() for match in pattern.finditer(text))
    word_spans = [m.span() for m in _WORD.finditer(text) if traceable.has_word(m.group())]

    def context(start: int, end: int) -> str:
        return " ".join(text[max(0, start - 40) : end + 40].split())

    found: list[tuple[int, Finding]] = []
    for match in _NUMBER.finditer(text):
        token = match.group()
        start, end = match.span()
        percent = bool(_PERCENT_RE.search(token))
        if traceable.has_number(token):
            continue
        if not percent and any(a <= start and end <= b for a, b in word_spans):
            continue
        if not percent and any(a <= start < b for a, b in exempt):
            continue
        found.append((start, Finding(source, token.strip(), context(start, end))))

    for match in _NUMBER_WORDS.finditer(text):
        start, end = match.span()
        after = text[end : end + _NEAR]
        around = text[max(0, start - _NEAR) : end + _NEAR]
        if _PERCENT_RE.match(after.lstrip()) or _METRIC_WORD.search(around):
            found.append((start, Finding(source, match.group().strip(), context(start, end))))
    return [finding for _, finding in sorted(found, key=lambda item: item[0])]


# ── CLI ──────────────────────────────────────────────────────────────────────
def collect_sources(root: Path, submission: Path, require_package: bool) -> tuple[list[tuple[str, str]], list[str]]:
    """(source name, stripped text) pairs, and the list of problems (missing files)."""
    sources: list[tuple[str, str]] = []
    problems: list[str] = []

    deck = next((submission / n for n in DECK_NAMES if (submission / n).is_file()), submission / DECK_NAMES[0])
    if deck.is_file():
        sources.append((deck.name, pptx_text(deck)))
    elif require_package:
        problems.append(f"missing {deck} (run `make submission`)")

    script = submission / "DEMO_SCRIPT.md"
    if script.is_file():
        sources.append((script.name, strip_markdown(script.read_text(encoding="utf-8"))))

    html = submission / "description.html"
    if html.is_file():
        sources.append((html.name, strip_html(html.read_text(encoding="utf-8"))))
    elif require_package:
        problems.append(f"missing {html} (run `make submission`)")

    pdf = submission / "description.pdf"
    if pdf.is_file():
        text = pdf_text(pdf)
        if text is None:
            print(
                "note: pypdf is not installed, so description.pdf is checked through description.html only",
                file=sys.stderr,
            )
        else:
            sources.append((pdf.name, text))
    elif require_package:
        problems.append(f"missing {pdf} (run `make submission`)")

    svg = root / ARCHITECTURE_SVG
    if svg.is_file():
        sources.append((ARCHITECTURE_SVG, svg_text(svg.read_text(encoding="utf-8"))))

    for name in ("README.md", "docs/DEMO.md"):
        path = root / name
        if path.is_file():
            sources.append((name, strip_markdown(path.read_text(encoding="utf-8"))))
        else:
            print(f"note: {name} does not exist in this checkout; nothing to check there", file=sys.stderr)
    return sources, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trace every number in the deck, the PDF, the README and DEMO.md.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--submission", type=Path, default=None, help="default: <root>/submission")
    parser.add_argument("--published", type=Path, default=None, help="default: <root>/evals/results/published")
    parser.add_argument(
        "--allow-missing", action="store_true", help="do not fail when the deck or the PDF is not built yet"
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    submission = (args.submission or root / "submission").resolve()
    published = (args.published or root / "evals" / "results" / "published").resolve()

    loaded = artifact_mod.load(published)
    traceable = traceable_for(loaded, published)
    if loaded:
        print(f"artifact: {loaded.path}")
    else:
        print(f"artifact: none in {published} (every statistic will fail)")

    sources, problems = collect_sources(root, submission, require_package=not args.allow_missing)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 2

    findings: list[Finding] = []
    for name, text in sources:
        found = find_untraceable(text, traceable, name)
        print(f"[{'FAIL' if found else 'ok':4}] {name}: {len(found)} untraceable number(s)")
        findings.extend(found)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    if findings:
        print(
            "\nEach number above must be a metric value of the published eval artifact, or be removed. "
            "An exact non-metric phrase can be added to ALLOWED_CONTEXTS with its reason (never a percentage, "
            "never a generic unit pattern).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
