# ruff: noqa: E501, S101, S603, S607
"""Shared helpers for the submission document builders (description .docx/.pdf, cookbook .pdf).

Truthfulness rules (CLAUDE.md): every number is read from `evals/results/published/**` at build time and
formatted here; nothing is typed into prose. The tools list comes from `scripts/submission/tools_used.py`
(the same source `scripts/readme_stack.py` uses). Standard library plus the build-time packages in
`submission/build/requirements.txt` (not shipped, not in uv.lock).
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = ROOT / "submission"
PUBLISHED = ROOT / "evals" / "results" / "published"
ASSETS = ROOT / "docs" / "assets"
SHOTS = ROOT / "web" / "design" / "app-shots"
WORK = ROOT / "work" / "submission-build"  # gitignored scratch (PNG renders)

sys.path.insert(0, str(ROOT / "scripts"))

TEAM = ["Mohamed Atef (Team leader)", "Abdulrahman Alseiari", "MokhmadSalakh Salamov"]


def repo_url() -> str:
    """Public repository URL from the git remote (same source as submission/repo_url.txt)."""
    raw = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    return re.sub(r"\.git$", "", re.sub(r"^git@github\.com:", "https://github.com/", raw))


# ── numbers: read from artifacts, format here ────────────────────────────────────────────────────
def fmt_pct(value: float, places: int = 1) -> str:
    """A fraction as a percentage, rounded half-up on the decimal string (matches the tracer's rounding)."""
    q = Decimal(1).scaleb(-places)
    return f"{(Decimal(str(value)) * 100).quantize(q, rounding=ROUND_HALF_UP)}%"


@dataclass(frozen=True)
class Artifacts:
    main: dict[str, Any]
    main_name: str
    fp: dict[str, Any] | None
    fp_name: str

    def m(self, key: str) -> Any:
        return self.main["metrics"][key]

    def pct(self, key: str, places: int = 1) -> str:
        """A fraction metric as a percentage string, e.g. 0.983333 -> '98.3%'."""
        return fmt_pct(self.m(key), places)

    def ci(self, key: str, places: int = 1) -> str:
        lo, hi = self.m(key + "_ci95")
        return f"{fmt_pct(lo, places)} to {fmt_pct(hi, places)}"

    def raw(self, key: str) -> str:
        return f"{self.m(key)}"

    @property
    def not_evaluated(self) -> list[str]:
        return list(self.main.get("not_evaluated", []))

    def fp_pct(self) -> str:
        assert self.fp is not None
        return fmt_pct(self.fp["false_positive_rate"]["value"])

    def fp_ci(self) -> str:
        assert self.fp is not None
        lo, hi = self.fp["false_positive_rate"]["ci95"]
        return f"{fmt_pct(lo)} to {fmt_pct(hi)}"

    def fp_n(self) -> int:
        assert self.fp is not None
        return int(self.fp["n"])


def _newest(paths: Iterable[Path]) -> Path | None:
    items = sorted(paths, key=lambda p: (_created(p), p.name))
    return items[-1] if items else None


def _created(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("created_at", ""))
    except (OSError, ValueError):
        return ""


def load_artifacts() -> Artifacts:
    main_path = _newest(p for p in PUBLISHED.glob("*.json"))
    if main_path is None:
        raise SystemExit("no published eval artifact: refusing to build (every number must come from one)")
    fp_path = _newest((PUBLISHED / "fp_regress").glob("*.json")) if (PUBLISHED / "fp_regress").is_dir() else None
    return Artifacts(
        main=json.loads(main_path.read_text(encoding="utf-8")),
        main_name=main_path.name,
        fp=json.loads(fp_path.read_text(encoding="utf-8")) if fp_path else None,
        fp_name=fp_path.name if fp_path else "",
    )


# ── tools used (shipped code only) ───────────────────────────────────────────────────────────────
def tools_by_category() -> list[tuple[str, list[str]]]:
    from submission import tools_used  # noqa: PLC0415  (scripts/ is on sys.path)

    return tools_used.names()


# ── inline markup: **bold**, `code`, plain ───────────────────────────────────────────────────────
_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def inline_parts(text: str) -> list[tuple[str, str]]:
    """Split text into (kind, text) with kind in {'t','b','c'}."""
    out: list[tuple[str, str]] = []
    for chunk in _INLINE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**"):
            out.append(("b", chunk[2:-2]))
        elif chunk.startswith("`"):
            out.append(("c", chunk[1:-1]))
        else:
            out.append(("t", chunk))
    return out


def inline_html(text: str) -> str:
    parts = []
    for kind, chunk in inline_parts(text):
        esc = html.escape(chunk)
        parts.append({"t": esc, "b": f"<strong>{esc}</strong>", "c": f"<code>{esc}</code>"}[kind])
    return "".join(parts)


# ── PNG rendering (Chromium through Playwright) ──────────────────────────────────────────────────
def svg_to_png(svg: Path, out: Path, scale: float = 2.0) -> Path:
    """Static render of an animated SVG (reduced motion = the final, readable state)."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=scale)
        page.emulate_media(reduced_motion="reduce")
        page.goto(svg.resolve().as_uri())
        w, h = page.evaluate("()=>{const v=document.documentElement.viewBox.baseVal;return [v.width,v.height]}")
        page.set_viewport_size({"width": int(w), "height": int(h)})
        page.screenshot(path=str(out))
        browser.close()
    return out


def html_to_pdf(html_path: Path, pdf_path: Path, footer_label: str, lang_dir: str = "ltr") -> None:
    """Print an HTML file to A4 PDF with outline, tags and 'label | page X of Y' footer."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    footer = (
        '<div style="font-size:8px;width:100%;text-align:center;color:#555;font-family:Helvetica,Arial,sans-serif">'
        f'{html.escape(footer_label)} &nbsp;|&nbsp; <span class="pageNumber"></span> / <span class="totalPages"></span></div>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=footer,
            margin={"top": "18mm", "bottom": "18mm", "left": "17mm", "right": "17mm"},
            outline=True,
            tagged=True,
        )
        browser.close()


def heading_pages(pdf_path: Path) -> dict[str, int]:
    """Map outline title -> 1-based page number (used to fill the table of contents on the second pass)."""
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(str(pdf_path))
    pages: dict[str, int] = {}

    def walk(items: list[Any]) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
            else:
                pages[re.sub(r"\s+", "", str(item.title))] = reader.get_destination_page_number(item) + 1

    walk(reader.outline)
    return pages


def pdf_to_pngs(pdf: Path, out_dir: Path, scale: float = 1.2) -> list[Path]:
    """Render every PDF page to PNG for visual QA, through Chromium's PDF viewer-free path (pypdfium-less):
    each page is rasterised by loading the PDF into Playwright is not supported, so use pdfium via pypdfium2."""
    import pypdfium2 as pdfium  # noqa: PLC0415

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    paths = []
    for i in range(len(doc)):
        img = doc[i].render(scale=scale).to_pil()
        path = out_dir / f"{pdf.stem}-p{i + 1:02d}.png"
        img.save(path)
        paths.append(path)
    return paths


FONT_CSS = """
:root{--ink:#14202b;--muted:#51606e;--accent:#0b6e69;--line:#d5dde3;--bg2:#f3f7f8}
@page{size:A4}
html{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:var(--ink);font-size:10.5pt;line-height:1.5}
*[lang=ar],.ar{font-family:"Geeza Pro","SF Arabic","Noto Naskh Arabic","Noto Sans Arabic","Al Bayan",Arial,sans-serif;direction:rtl;text-align:right;line-height:1.85}
code,pre{font-family:Menlo,"SF Mono",Consolas,monospace}
"""
