# ruff: noqa: E501
"""Checks for the three submission documents. Exit 1 on any failure.

    uv run --no-project --with-requirements submission/build/requirements.txt --with pyyaml python submission/build/check.py

1. Numbers: every number in the description (docx text, PDF text, HTML source) and in the cookbook prose must be
   traceable. Uses the repository's own tracer (scripts/submission/check_numbers.py), extended with the values of the
   newest `evals/results/published/fp_regress/*.json` (the live false-alarm run) so those can be quoted too.
2. Words: the product word for "harmless" (English and Arabic) never appears; no email addresses; no ADP logo files.
3. Structure: the docx has real heading styles and alt text on every picture; PDFs have an outline; every file is
   at most 20 MB.
4. Cookbook commands exist (verify_cookbook.py).
"""

from __future__ import annotations

import re
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_cookbook  # noqa: E402
from common import ROOT, SUBMISSION, WORK, load_artifacts  # noqa: E402
from common import evidence as common_evidence  # noqa: E402
from docx import Document  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from submission import artifact as artifact_mod  # noqa: E402
from submission import check_numbers as cn  # noqa: E402

DESC_DOCX = SUBMISSION / "FalconLens_Project_Description.docx"
DESC_PDF = SUBMISSION / "FalconLens_Project_Description.pdf"
COOK_PDF = SUBMISSION / "FalconLens_Cookbook.pdf"
MAX_BYTES = 20 * 1024 * 1024
HARMLESS = re.compile(r"safe|آمن", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


# Structural numbers of a document (not data): chapter and figure numbers, "section 8" references, "step 1".
STRUCTURAL = (
    (r"(?m)^\s*\d{1,2}(?:\.\d{1,2})?\.? (?=[A-Z])", "heading number"),
    (r"\b[Ss]ections? \d{1,2}(?:\.\d{1,2})?\b(?! ?(?:%|percent))", "cross-reference to a chapter of this document"),
    (r"\bFigure \d{1,2}\b", "figure number"),
)
for _pat, _why in STRUCTURAL:
    cn._ALLOWED = (*cn._ALLOWED, (re.compile(_pat), _why))
PERCENT = re.compile(
    r"\d\s?(?:%|٪|percent|per cent)|\b(?:recall|precision|f1|fpr|accuracy|latency)\b\W{0,12}\d", re.IGNORECASE
)


def traceable() -> cn.Traceable:
    a = load_artifacts()
    tr = cn.Traceable(a.main, names=(a.main_name, Path(a.main_name).stem, a.fp_name, Path(a.fp_name).stem))
    if a.fp:
        for _k, leaf in artifact_mod.flatten(
            {k: v for k, v in a.fp.items() if k not in ("items", "git_sha", "created_at", "set", "kind")}
        ):
            if isinstance(leaf, int | float) and not isinstance(leaf, bool):
                tr.values.append(Decimal(str(leaf)))
        tr.strings.add(str(a.fp.get("set", "")).lower())
    for leaf in common_evidence().claimed_values():  # only the figures the documents quote from the other families
        tr.values.append(Decimal(str(leaf)))
    return tr


def docx_text(path: Path) -> str:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def pdf_text(path: Path, skip_pages: int = 0) -> str:
    """PDF text without the running footer (page x / y) and the contents pages (their numbers are page numbers)."""
    pages = PdfReader(str(path)).pages[skip_pages:]
    text = "\n".join(re.sub(r"Falcon Lens[^\n]{0,45}?\d+ / \d+", "", p.extract_text() or "") for p in pages)
    return re.sub(r"(?<=\d) ?\. ?(?=\d)", ".", text)


def main() -> int:
    errors: list[str] = []
    tr = traceable()

    # presence and size
    for f in (DESC_DOCX, DESC_PDF, COOK_PDF):
        if not f.is_file():
            errors.append(f"missing {f.relative_to(ROOT)}")
        elif f.stat().st_size > MAX_BYTES:
            errors.append(f"{f.name} is larger than 20 MB")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    # sources
    desc_html = (WORK / "description.final.html").read_text(encoding="utf-8")
    cook_md = (ROOT / "submission" / "build" / "cookbook.rendered.md").read_text(encoding="utf-8")
    sources = {
        "description.docx": docx_text(DESC_DOCX),
        "description.pdf": pdf_text(DESC_PDF, skip_pages=3),
        "description.html": cn.strip_html(
            re.sub(r"</(?:h\d|p|li|tr|figcaption|div)>", "\n", re.sub(r"(?s)<ul class=\"toc\">.*?</ul>", "", desc_html))
        ),
    }
    cookbook = {"cookbook.pdf": pdf_text(COOK_PDF), "cookbook.md (prose)": cn.strip_markdown(cook_md)}
    for name, text in cookbook.items():  # a how-to guide: ports and chapter numbers are fine, statistics are not
        hits = [m.group() for m in PERCENT.finditer(cn.normalise(text))]
        print(f"[{'FAIL' if hits else 'ok':4}] statistics: {name}")
        errors.extend(f"{name}: statistic-like text {h!r}" for h in hits)
        for m in HARMLESS.finditer(text):
            errors.append(f"{name}: forbidden word {m.group()!r}")
        errors.extend(f"{name}: email-like text {m.group()!r}" for m in EMAIL.finditer(text))
    for name, text in sources.items():
        found = cn.find_untraceable(cn.strip_markdown(text) if name.endswith("docx") else text, tr, name)
        print(f"[{'FAIL' if found else 'ok':4}] numbers: {name}")
        errors.extend(str(f) for f in found)
        for m in HARMLESS.finditer(text):
            errors.append(
                f"{name}: forbidden word {m.group()!r} near “…{text[max(0, m.start() - 30) : m.end() + 30]!r}…”"
            )
        for m in EMAIL.finditer(text):
            errors.append(f"{name}: email-like text {m.group()!r}")

    # docx structure
    doc = Document(str(DESC_DOCX))
    heads = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
    h1 = [p for p in heads if p.style.name == "Heading 1"]
    if len(h1) < 13:
        errors.append(f"docx has only {len(h1)} Heading 1 paragraphs")
    shapes = doc.inline_shapes
    for i, s in enumerate(shapes):
        if not s._inline.docPr.get("descr"):
            errors.append(f"docx picture {i + 1} has no alt text")
    with zipfile.ZipFile(DESC_DOCX) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        if "TOC" not in xml or "PAGE" not in z.read("word/footer1.xml").decode("utf-8"):
            errors.append("docx lacks a TOC field or a page-number footer")
    print(f"docx: {len(h1)} chapters, {len(heads)} headings, {len(shapes)} pictures with alt text")

    # PDFs: outline
    for f in (DESC_PDF, COOK_PDF):
        r = PdfReader(str(f))
        print(f"{f.name}: {len(r.pages)} pages, {f.stat().st_size / 1024:.0f} KB, outline entries: {len(r.outline)}")
        if not r.outline:
            errors.append(f"{f.name} has no outline")

    # no ADP imagery in the build inputs
    for p in (ROOT / "submission").rglob("*"):
        if p.suffix.lower() in {".png", ".jpg", ".svg"} and "adp" in p.name.lower():
            errors.append(f"possible ADP imagery: {p}")

    errors.extend(verify_cookbook.check(cook_md))
    print(f"docx {DESC_DOCX.stat().st_size / 1024:.0f} KB")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    print("check: FAIL" if errors else "check: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
