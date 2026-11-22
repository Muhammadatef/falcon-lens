#!/usr/bin/env python3
# ruff: noqa: E501  (copy and tables read better unwrapped)
"""Fail if a number in the deck, the description document or the README cannot be traced.

Truthfulness rule (CLAUDE.md): every metric shown anywhere comes from a generated eval
artifact. This script reads the text of

    submission/deck.pptx         (slide XML, standard library zipfile)
    submission/description.pdf   (pypdf when installed; `make submission` installs it)
    submission/description.html  (the exact source the PDF was rendered from)
    README.md                    (when it exists)

and requires every number in them to be one of:

1. **A value of the newest published artifact** (`evals/results/published/*.json`). A document
   number written with d decimals matches an artifact number v when round(v, d) equals it. A
   number followed by `%` also matches round(100 * v, d) for 0 <= v <= 1. Numbers inside the
   artifact's keys and string values (dates, model ids, a git SHA) count as traceable too.
2. **Part of an identifier**: the digits directly follow an ASCII letter or underscore, as in
   `T0`, `H1`, `R5`, `G6`, `v1`, `MV3`, `p95`. An identifier names a thing; it is not a measurement.
3. **Covered by a context pattern** in `ALLOWED_CONTEXTS` below: a short, reviewed list of
   non-metric phrases (a standard's version, a date, a design limit quoted from an ADR), each
   with the reason it is not a measurement. **A percentage is never allowed this way**: a
   number followed by `%` must come from the artifact.

Before scanning, Markdown code (fenced and inline), link targets, HTML tags and comments are
and ordered-list markers are
removed, because commands, ports and file names are not claims. Number WORDS ("six scenarios")
are not checked: keep statistics as digits or leave them out.

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

ROOT = Path(__file__).resolve().parents[2]

# (regex, reason). Every number inside a match is exempt unless it carries a percent sign.
ALLOWED_CONTEXTS: tuple[tuple[str, str], ...] = (
    (r"STIX\s+2\s*\.\s*1", "version of the STIX standard (PDF text extraction may space the dot)"),
    (r"\b(?:x|×)\s?42\b", "organiser name: Abu Dhabi Police x 42"),
    (r"\b42 Abu Dhabi\b", "organiser name"),
    (r"\bRFC ?\d{3,5}\b", "RFC reference"),
    (r"\bPython 3\.\d+\b", "language version from .python-version"),
    (r"\bManifest V3\b", "Chrome extension platform name"),
    (r"\bFable 5\.2\b|\bInkling-2-Mini\b", "model names as recorded in DECISIONS.md"),
    (
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,? \d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?: \d{4})?",
        "calendar date",
    ),
    (r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}\b", "calendar date"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "ISO date"),
    (r"\b\d{1,2}:\d{2}(?::\d{2})?\b(?! ?%)", "clock time or video timestamp"),
    (r"#\d+\b", "pull request or issue reference"),
    (r"\b[A-Z]{1,5}-\d+\b", "document, task or review identifier such as ADR-001 or T-012"),
    (r"\bPhase \d(?: (?:to|→) \d)?\b", "project phase from STATUS.md"),
    (r"\| ?T[0-3] ?\| ?\d+ m?s ?\|", "tier budget: a design limit from ADR-001, labelled as not measured"),
    (
        r"\b(?:≤|at most|up to|max(?:imum)?|limit(?:ed to)?|within|under) ?\d+(?:[.,]\d+)? ?(?:MB|KB|GB|characters|chars|pages|slides|seconds|s|min(?:utes)?)\b",
        "stated limit, not a measurement",
    ),
    (r"\b\d+(?:-| )(?:second|minute)s?\b", "duration of the video or pitch"),
    (r"\b999\b|\b800\d{4}\b", "official reporting numbers from config/reporting_channels.yaml"),
    (r"\b24/7\b", "idiom"),
    (r"\b[A-Z]\d\s?(?:to|–|-|→)\s?[A-Z]?\d\b", "identifier range such as T0 to T3 or R1-R5"),
    (r"©\s?\d{4}|\b20\d{2}\b(?=\s*(?:Falcon Lens|hackathon|ScamShield))", "year"),
)
_ALLOWED = tuple((re.compile(pattern), reason) for pattern, reason in ALLOWED_CONTEXTS)

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:\s?[%٪])?")
_HEXWORD = re.compile(r"\b[0-9a-f]{7,64}\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    source: str
    token: str
    context: str

    def __str__(self) -> str:
        return f"{self.source}: {self.token!r} in “…{self.context}…”"


# ── text extraction ──────────────────────────────────────────────────────────
def normalise_digits(text: str) -> str:
    """Arabic-Indic and other Unicode decimal digits become ASCII digits."""
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


def strip_markdown(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"(?ms)^(```|~~~).*?^\1\s*$", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"\]\([^)\s]*\)", "]", text)  # link targets
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", text)  # ordered-list markers
    return re.sub(r"<[^>\n]+>", " ", text)  # HTML tags, with their attributes


def strip_html(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"(?is)<(style|script|svg)\b.*?</\1>", " ", text)
    text = re.sub(r"(?is)<code\b.*?</code>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#37;", "%")):
        text = text.replace(entity, char)
    return text


def pptx_text(path: Path) -> str:
    """All text runs of every slide and notes page, one paragraph per line."""
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(n for n in archive.namelist() if re.match(r"ppt/(slides|notesSlides)/[^/]+\.xml$", n))
        for name in names:
            xml = archive.read(name).decode("utf-8")
            for paragraph in re.findall(r"<a:p\b.*?</a:p>", xml, flags=re.DOTALL):
                runs = re.findall(r"<a:t>([^<]*)</a:t>", paragraph)
                if runs:
                    parts.append("".join(runs))
    text = "\n".join(parts)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(entity, char)
    return text


def pdf_text(path: Path) -> str | None:
    """Text of the PDF, or None when pypdf is not installed."""
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        return None
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ── tracing ──────────────────────────────────────────────────────────────────
def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


class Traceable:
    """The numbers the newest published artifact contains."""

    def __init__(self, data: dict[str, Any] | None) -> None:
        self.values: list[Decimal] = []
        self.strings: list[str] = []
        self.loose: set[Decimal] = set()  # digits inside keys and string values
        if data is None:
            return
        for key, leaf in artifact_mod.flatten(data):
            self._text(key)
            if isinstance(leaf, bool) or leaf is None:
                continue
            if isinstance(leaf, int | float):
                value = _decimal(json.dumps(leaf))
                if value is not None and value.is_finite():
                    self.values.append(value)
            elif isinstance(leaf, str):
                self.strings.append(leaf.lower())
                self._text(leaf)

    def _text(self, text: str) -> None:
        for match in re.finditer(r"\d+(?:\.\d+)?", text):
            value = _decimal(match.group())
            if value is not None:
                self.loose.add(value)

    def has_number(self, token: str) -> bool:
        percent = token.rstrip().endswith(("%", "٪"))
        body = token.rstrip("%٪ ").lstrip("+")
        candidates = {body.replace(",", "")}  # 1,234 as a thousands separator
        if body.count(",") == 1 and "." not in body:
            candidates.add(body.replace(",", "."))  # 0,97 as a decimal comma
        for text in candidates:
            number = _decimal(text)
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
            if not percent and number in self.loose:
                return True
        return False

    def has_hex(self, word: str) -> bool:
        word = word.lower()
        return any(word in text for text in self.strings)


def find_untraceable(text: str, traceable: Traceable, source: str) -> list[Finding]:
    """Numbers in already-stripped text that no rule accounts for."""
    text = normalise_digits(text)
    exempt: list[tuple[int, int]] = []
    for pattern, _reason in _ALLOWED:
        exempt.extend(match.span() for match in pattern.finditer(text))
    hex_spans = [
        m.span()
        for m in _HEXWORD.finditer(text)
        if re.search(r"[a-f]", m.group(), re.I) and traceable.has_hex(m.group())
    ]

    findings = []
    for match in _NUMBER.finditer(text):
        token = match.group()
        start, end = match.span()
        percent = token.rstrip().endswith(("%", "٪"))
        if traceable.has_number(token):
            continue
        if any(a <= start and end <= b for a, b in hex_spans):
            continue
        if not percent and any(a <= start and start < b for a, b in exempt):
            continue
        context = " ".join(text[max(0, start - 40) : end + 40].split())
        findings.append(Finding(source, token.strip(), context))
    return findings


# ── CLI ──────────────────────────────────────────────────────────────────────
def collect_sources(root: Path, submission: Path, require_package: bool) -> tuple[list[tuple[str, str]], list[str]]:
    """(source name, stripped text) pairs, and the list of problems (missing files)."""
    sources: list[tuple[str, str]] = []
    problems: list[str] = []

    deck = submission / "deck.pptx"
    if deck.is_file():
        sources.append((str(deck.relative_to(root)) if deck.is_relative_to(root) else deck.name, pptx_text(deck)))
    elif require_package:
        problems.append(f"missing {deck} (run `make submission`)")

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

    readme = root / "README.md"
    if readme.is_file():
        sources.append(("README.md", strip_markdown(readme.read_text(encoding="utf-8"))))
    else:
        print("note: README.md does not exist on this branch; nothing to check there", file=sys.stderr)
    return sources, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trace every number in the deck, the PDF and the README.")
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
    traceable = Traceable(loaded.data if loaded else None)
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
            "\nEach number above must come from the published eval artifact, or be removed. "
            "A non-metric phrase can be added to ALLOWED_CONTEXTS with its reason (never a percentage).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
