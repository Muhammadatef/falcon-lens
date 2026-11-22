# ruff: noqa: E501  (copy and tables read better unwrapped)
"""Build submission/description.html and render it to description.pdf with Playwright.

Playwright (Python 1.65.2, Chromium) is used because Chromium shapes Arabic and renders the
animated architecture SVG correctly; `page.pdf(print_background=True)` keeps the Night theme.
The HTML is kept beside the PDF: it is the exact source of the PDF and check_numbers.py reads
both.
"""

from __future__ import annotations

import html
from pathlib import Path

from submission import content as content_mod

MIN_PAGES, MAX_PAGES = 2, 4
FONT_FILES = {
    "latin": "web/public/fonts/readex-pro-latin-wght-normal.woff2",
    "arabic": "web/public/fonts/readex-pro-arabic-wght-normal.woff2",
}

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: #070b14; color: #f2eee6; font: 9.4pt/1.42 "Readex Pro", "Noto Sans Arabic", "Geeza Pro", "Segoe UI", Tahoma, system-ui, sans-serif; }
main { padding: 11mm 14mm 9mm; }
header { display: flex; align-items: center; gap: 4mm; border-bottom: 1px solid #2a3757; padding-bottom: 5mm; margin-bottom: 5mm; }
.lens { width: 12mm; height: 12mm; border: 0.8mm solid #3fe0c5; border-radius: 50%; display: grid; place-items: center; flex: none; }
.lens i { width: 4.2mm; height: 4.2mm; border-radius: 50%; background: #3fe0c5; display: block; }
h1 { font-size: 21pt; margin: 0; color: #e7d7b6; font-weight: 650; }
.tag { color: #aeb8cc; margin: 0; }
h2 { font-size: 12pt; color: #3fe0c5; margin: 4mm 0 1.5mm; font-weight: 650; break-after: avoid; }
p { margin: 0 0 2.2mm; }
.lead { color: #f2eee6; font-weight: 500; }
.ar { direction: rtl; text-align: right; line-height: 1.75; }
.card { background: #0e1626; border: 1px solid #2a3757; border-radius: 3mm; padding: 4mm 5mm; margin-bottom: 3mm; break-inside: avoid; }
ul { margin: 0 0 2mm; padding-inline-start: 5mm; }
li { margin-bottom: 0.6mm; }
li.planned { color: #aeb8cc; }
.chip { display: inline-block; font-size: 7.5pt; font-weight: 650; color: #ffc55c; background: #2a1d07; border: 1px solid #8a6416; border-radius: 99px; padding: 0 2mm; margin-inline-start: 1.5mm; vertical-align: middle; }
.banner { color: #ffc55c; background: #2a1d07; border: 1px solid #8a6416; border-radius: 3mm; padding: 3mm 5mm; margin-bottom: 4mm; }
.note { color: #8794ae; font-size: 9pt; }
table { width: 100%; border-collapse: collapse; margin-bottom: 2mm; }
td { border-bottom: 1px solid #2a3757; padding: 1.4mm 2mm; }
td.v { text-align: right; color: #3fe0c5; font-weight: 650; }
img.arch { width: 100%; border-radius: 3mm; border: 1px solid #2a3757; margin: 1mm 0 3mm; }
section { break-inside: avoid-page; }
.big { font-size: 16pt; color: #e7d7b6; font-weight: 650; }
"""


def _font_face(root: Path) -> str:
    rules = []
    for path in FONT_FILES.values():
        file = root / path
        if file.is_file():
            rules.append(
                f'@font-face {{ font-family: "Readex Pro"; src: url("{file.as_uri()}") format("woff2"); font-weight: 200 700; }}'
            )
    return "\n".join(rules)


def _esc(text: str) -> str:
    """Escape, then show `code` spans as <code> (check_numbers ignores code)."""
    parts = html.escape(text, quote=False).split("`")
    return "".join(f"<code>{part}</code>" if index % 2 else part for index, part in enumerate(parts))


def _section(section: content_mod.Section) -> str:
    out = [f"<section><h2>{_esc(section.title)}</h2>"]
    if section.lead:
        out.append(f'<p class="lead">{_esc(section.lead)}</p>')
    if section.table:
        out.append(
            "<table>"
            + "".join(f'<tr><td>{_esc(k)}</td><td class="v">{_esc(v)}</td></tr>' for k, v in section.table)
            + "</table>"
        )
        if section.extra.get("provenance"):
            out.append(f'<p class="note">{_esc(section.extra["provenance"])}</p>')
        if section.extra.get("not_evaluated"):
            out.append(f'<p class="note">{_esc(section.extra["not_evaluated"])}</p>')
    if section.lines:
        items = []
        for line in section.lines:
            chip = f'<span class="chip">{content_mod.PLANNED}</span>' if line.planned else ""
            items.append(f'<li class="{"planned" if line.planned else ""}">{_esc(line.text)}{chip}</li>')
        out.append("<ul>" + "".join(items) + "</ul>")
    if section.note:
        out.append(f'<p class="note">{_esc(section.note)}</p>')
    out.append("</section>")
    return "".join(out)


def build_html(
    sections: list[content_mod.Section],
    description_en: str,
    description_ar: str,
    tools: list[tuple[str, list[str]]],
    architecture_png: Path | None,
    mvp: bool,
    root: Path,
) -> str:
    by_key = {s.key: s for s in sections}
    body = [
        '<header><div class="lens"><i></i></div><div>'
        f"<h1>{_esc(content_mod.TITLE)}</h1>"
        f'<p class="tag">{_esc(content_mod.TAGLINE_EN)} · <span dir="rtl">{_esc(content_mod.TAGLINE_AR)}</span></p>'
        "</div></header>"
    ]
    if not mvp:
        body.append(f'<div class="banner">{_esc(content_mod.PRE_MVP_BANNER)}</div>')
    body.append(f'<div class="card"><p>{_esc(description_en)}</p><p class="ar">{_esc(description_ar)}</p></div>')
    for key in ("problem", "solution"):
        body.append(_section(by_key[key]))
    body.append(_section(by_key["architecture"]))
    if architecture_png and architecture_png.is_file():
        body.append(f'<img class="arch" alt="System architecture diagram" src="{architecture_png.as_uri()}">')
    for key in ("agent", "results", "security", "integration", "deployment", "roadmap"):
        body.append(_section(by_key[key]))
    if tools:
        rows = "".join(f"<li><strong>{_esc(title)}:</strong> {_esc(', '.join(items))}</li>" for title, items in tools)
        body.append(
            f'<section><h2>Tools used</h2><p class="note">Generated from the lockfiles and the compose file. Only what the shipped code uses.</p><ul>{rows}</ul></section>'
        )
    team = by_key["team"]
    body.append(
        f'<section><h2>Independence</h2><p>{_esc(content_mod.DISCLAIMER_EN)}</p><p class="ar">{_esc(content_mod.DISCLAIMER_AR)}</p>'
        f'<p class="note">Repository: {_esc(team.extra["repo_url"])}</p></section>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{_esc(content_mod.TITLE)}</title><style>{_font_face(root)}{CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>"
    )


def render_svg_png(svg: Path, png: Path, scale: float = 2) -> Path:
    """Static PNG of an animated SVG. Reduced motion is emulated so the still frame is the readable one."""
    import re  # noqa: PLC0415

    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    match = re.search(r'viewBox="\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)', svg.read_text(encoding="utf-8"))
    width, height = (round(float(match.group(1))), round(float(match.group(2)))) if match else (1600, 900)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
        page.emulate_media(reduced_motion="reduce")
        page.goto(svg.as_uri())
        page.wait_for_timeout(300)
        page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": width, "height": height})
        browser.close()
    return png


def render_pdf(html_path: Path, pdf_path: Path) -> Path:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri())
        page.evaluate("document.fonts.ready")
        page.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    return pdf_path


def page_count(pdf_path: Path) -> int:
    from pypdf import PdfReader  # noqa: PLC0415

    return len(PdfReader(str(pdf_path)).pages)
