# ruff: noqa: E501  (copy and tables read better unwrapped)
"""Build submission/deck.pptx with python-pptx (1.0.2, see scripts/submission/requirements.txt).

Night theme from web/design/tokens.css (the product's default theme). The palette is copied
here as constants because the deck must build on a checkout where the web design tokens are
not merged yet; `TOKENS` names the token each colour mirrors.

No logos or marks of any police or government body. The lens mark is drawn from shapes.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from submission import content as content_mod

TOKENS = {
    "bg": "070b14",  # --fl-bg
    "surface1": "0e1626",  # --fl-surface-1
    "surface2": "16203a",  # --fl-surface-2
    "border": "2a3757",  # --fl-border
    "text": "f2eee6",  # --fl-text
    "muted": "aeb8cc",  # --fl-text-muted
    "faint": "8794ae",  # --fl-text-faint
    "brand": "3fe0c5",  # --fl-brand
    "brand_ink": "04211d",  # --fl-brand-ink
    "sand": "e7d7b6",  # --fl-sand
    "warn": "ffc55c",  # --fl-suspicious-fg
    "warn_tint": "2a1d07",  # --fl-suspicious-tint
}
FONT = "Arial"  # present on Windows, macOS and in PowerPoint Online; carries Arabic glyphs
W, H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.6)


def _rgb(name: str) -> RGBColor:
    return RGBColor.from_string(TOKENS[name].upper())


def _is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def _style_run(run, size: float, color: str, bold: bool = False) -> None:  # type: ignore[no-untyped-def]
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = _rgb(color)
    run.font.name = FONT
    r_pr = run._r.get_or_add_rPr()
    for tag in ("a:cs", "a:ea"):
        element = r_pr.find(qn(tag))
        if element is None:
            element = r_pr.makeelement(qn(tag), {})
            r_pr.append(element)
        element.set("typeface", FONT)


def _text(
    slide,
    x,
    y,
    w,
    h,
    text: str,
    size: float,
    color: str = "text",
    bold: bool = False,
    align=None,
    anchor=MSO_ANCHOR.TOP,
):  # type: ignore[no-untyped-def]
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    _paragraph(frame.paragraphs[0], text, size, color, bold, align)
    return box


def _paragraph(paragraph, text: str, size: float, color: str, bold: bool = False, align=None) -> None:  # type: ignore[no-untyped-def]
    rtl = _is_arabic(text) and not any("a" <= ch.lower() <= "z" for ch in text.split("|")[0][:12])
    if rtl:
        paragraph._p.get_or_add_pPr().set("rtl", "1")
        paragraph.alignment = align or PP_ALIGN.RIGHT
    elif align is not None:
        paragraph.alignment = align
    text = text.replace("`", "")  # code marks are for the HTML document only
    _style_run(paragraph.add_run(), size, color, bold)
    paragraph.runs[-1].text = text


def _box(slide, x, y, w, h, fill: str, line: str | None = None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):  # type: ignore[no-untyped-def]
    item = slide.shapes.add_shape(shape, x, y, w, h)
    item.fill.solid()
    item.fill.fore_color.rgb = _rgb(fill)
    if line:
        item.line.color.rgb = _rgb(line)
        item.line.width = Pt(1)
    else:
        item.line.fill.background()
    item.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        item.adjustments[0] = 0.08
    return item


def _lens(slide, x, y, size) -> None:  # type: ignore[no-untyped-def]
    """The lens mark: a ring and a pupil. Drawn, not an image."""
    ring = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, size, size)
    ring.fill.background()
    ring.line.color.rgb = _rgb("brand")
    ring.line.width = Pt(2.25)
    ring.shadow.inherit = False
    inner = int(size * 0.36)
    offset = int((size - inner) / 2)
    _box(slide, x + offset, y + offset, inner, inner, "brand", shape=MSO_SHAPE.OVAL)


def _chrome(slide, section: content_mod.Section, banner: bool) -> int:
    """Background, header and footer. Returns the y where the body starts."""
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = _rgb("bg")
    _box(slide, 0, 0, W, Inches(0.07), "brand", shape=MSO_SHAPE.RECTANGLE)
    _lens(slide, MARGIN, Inches(0.42), Inches(0.42))
    _text(
        slide,
        MARGIN + Inches(0.6),
        Inches(0.42),
        Inches(6),
        Inches(0.42),
        content_mod.TITLE,
        14,
        "sand",
        bold=True,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    _text(
        slide,
        W - MARGIN - Inches(5),
        Inches(0.42),
        Inches(5),
        Inches(0.42),
        "Independent project. Not affiliated with Abu Dhabi Police.",
        10.5,
        "faint",
        align=PP_ALIGN.RIGHT,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    _text(slide, MARGIN, Inches(1.05), W - 2 * MARGIN, Inches(0.7), section.title, 32, "text", bold=True)
    y = Inches(1.8)
    if section.lead:
        _text(slide, MARGIN, y, W - 2 * MARGIN, Inches(0.75), section.lead, 17, "brand")
        y += Inches(0.8)
    if banner:
        strip = _box(slide, MARGIN, H - Inches(0.62), W - 2 * MARGIN, Inches(0.4), "warn_tint", "warn")
        frame = strip.text_frame
        frame.margin_left = Inches(0.15)
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        _paragraph(frame.paragraphs[0], content_mod.PRE_MVP_BANNER, 10.5, "warn")
    return y


def _lines(slide, lines, x, y, w, bottom, size: float = 15) -> None:  # type: ignore[no-untyped-def]
    if not lines:
        return
    count = len(lines)
    gap = Inches(0.1)
    row = min(Inches(0.72), int((bottom - y - gap * (count - 1)) / count))
    if row < Inches(0.5):
        size = min(size, 12.5)
    for index, line in enumerate(lines):
        top = y + index * (row + gap)
        card = _box(slide, x, top, w, row, "surface1", "border")
        card.adjustments[0] = 0.18
        _box(
            slide,
            x + Inches(0.18),
            top + int(row / 2) - Inches(0.05),
            Inches(0.1),
            Inches(0.1),
            "faint" if line.planned else "brand",
            shape=MSO_SHAPE.OVAL,
        )
        chip = Inches(1.05) if line.planned else 0
        _text(
            slide,
            x + Inches(0.42),
            top,
            w - Inches(0.6) - chip,
            row,
            line.text,
            size,
            "muted" if line.planned else "text",
            anchor=MSO_ANCHOR.MIDDLE,
        )
        if line.planned:
            tag = _box(
                slide,
                x + w - Inches(1.1),
                top + int(row / 2) - Inches(0.13),
                Inches(0.95),
                Inches(0.26),
                "warn_tint",
                "warn",
            )
            tag.adjustments[0] = 0.5
            frame = tag.text_frame
            frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
            frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            _paragraph(frame.paragraphs[0], content_mod.PLANNED, 9, "warn", bold=True, align=PP_ALIGN.CENTER)


def _note(slide, text: str, bottom) -> None:  # type: ignore[no-untyped-def]
    if text:
        _text(
            slide,
            MARGIN,
            bottom - Inches(0.5),
            W - 2 * MARGIN,
            Inches(0.5),
            text,
            11,
            "faint",
            anchor=MSO_ANCHOR.BOTTOM,
        )


def _fallback_diagram(slide, x, y, w, h) -> None:  # type: ignore[no-untyped-def]
    """Native block diagram used when docs/assets/architecture.svg is not in the checkout."""
    rows = (
        ("Web app (PWA)", "Chrome extension", "Police app or agent"),
        ("Gateway (TLS, CSP)",),
        ("API", "Worker cascade", "MCP server", "Sentinel"),
        ("PostgreSQL + pgvector", "Redis streams", "Egress proxy", "Sandbox browser"),
        ("Metrics, logs, traces, dashboards, alerts",),
    )
    gap = Inches(0.12)
    row_h = int((h - gap * (len(rows) - 1)) / len(rows))
    for r, row in enumerate(rows):
        cell_w = int((w - gap * (len(row) - 1)) / len(row))
        for c, label in enumerate(row):
            cell = _box(
                slide,
                x + c * (cell_w + gap),
                y + r * (row_h + gap),
                cell_w,
                row_h,
                "surface2" if r % 2 else "surface1",
                "border",
            )
            frame = cell.text_frame
            frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            _paragraph(frame.paragraphs[0], label, 12.5, "text", align=PP_ALIGN.CENTER)


def build(sections: list[content_mod.Section], out: Path, architecture_png: Path | None, mvp: bool) -> Path:
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = W, H
    presentation.core_properties.title = content_mod.TITLE
    presentation.core_properties.author = "Falcon Lens team"
    blank = presentation.slide_layouts[6]
    banner = not mvp
    floor = H - Inches(0.75) if banner else H - Inches(0.4)

    for section in sections:
        slide = presentation.slides.add_slide(blank)
        y = _chrome(slide, section, banner)
        note_room = Inches(0.55) if section.note else 0
        bottom = floor - note_room
        full = W - 2 * MARGIN

        if section.key == "problem":
            _text(slide, MARGIN, y, full, Inches(0.5), content_mod.PROMISE_AR, 17, "sand")
            _lines(slide, section.lines, MARGIN, y + Inches(0.65), full, bottom)
        elif section.key == "solution":
            _text(slide, MARGIN, y - Inches(0.1), full, Inches(0.45), section.extra["verdicts_ar"], 16, "sand")
            _lines(slide, section.lines, MARGIN, y + Inches(0.45), full, bottom, size=13.5)
        elif section.key == "architecture":
            left = Inches(7.6)
            if architecture_png and architecture_png.is_file():
                picture = slide.shapes.add_picture(str(architecture_png), MARGIN, y, width=left)
                limit = bottom - y
                if picture.height > limit:
                    ratio = limit / picture.height
                    picture.height, picture.width = int(limit), int(picture.width * ratio)
            else:
                _fallback_diagram(slide, MARGIN, y, left, bottom - y)
            _lines(slide, section.lines, MARGIN + left + Inches(0.3), y, full - left - Inches(0.3), bottom, size=11.5)
        elif section.key == "results" and section.table:
            row_h = min(Inches(0.42), int((bottom - y - Inches(0.5)) / len(section.table)))
            for index, (label, value) in enumerate(section.table):
                top = y + index * row_h
                _box(
                    slide,
                    MARGIN,
                    top,
                    full,
                    row_h - Emu(20000),
                    "surface1" if index % 2 else "surface2",
                    "border",
                    shape=MSO_SHAPE.RECTANGLE,
                )
                _text(slide, MARGIN + Inches(0.2), top, Inches(8), row_h, label, 13, "muted", anchor=MSO_ANCHOR.MIDDLE)
                _text(
                    slide,
                    MARGIN + Inches(8.4),
                    top,
                    full - Inches(8.6),
                    row_h,
                    value,
                    15,
                    "brand",
                    bold=True,
                    align=PP_ALIGN.RIGHT,
                    anchor=MSO_ANCHOR.MIDDLE,
                )
            if section.extra.get("provenance"):
                _text(
                    slide,
                    MARGIN,
                    y + len(section.table) * row_h + Inches(0.1),
                    full,
                    Inches(0.4),
                    section.extra["provenance"],
                    10.5,
                    "faint",
                )
            if section.extra.get("not_evaluated"):
                _text(
                    slide,
                    MARGIN,
                    y + len(section.table) * row_h + Inches(0.42),
                    full,
                    Inches(0.5),
                    section.extra["not_evaluated"],
                    10.5,
                    "warn",
                )
        elif section.key == "results":
            card = _box(slide, MARGIN, y + Inches(0.4), full, Inches(2.2), "surface1", "border")
            card.adjustments[0] = 0.06
            _text(
                slide,
                MARGIN,
                y + Inches(0.4),
                full,
                Inches(2.2),
                "Evaluation in progress",
                40,
                "sand",
                bold=True,
                align=PP_ALIGN.CENTER,
                anchor=MSO_ANCHOR.MIDDLE,
            )
        elif section.key == "team":
            _lines(slide, section.lines, MARGIN, y, Inches(6.2), y + Inches(2.4))
            _text(slide, MARGIN + Inches(6.6), y, full - Inches(6.6), Inches(0.4), "Repository", 12, "faint")
            _text(
                slide,
                MARGIN + Inches(6.6),
                y + Inches(0.4),
                full - Inches(6.6),
                Inches(0.6),
                section.extra["repo_url"],
                15,
                "brand",
            )
            _text(
                slide,
                MARGIN + Inches(6.6),
                y + Inches(1.3),
                full - Inches(6.6),
                Inches(1.0),
                section.extra["disclaimer_ar"],
                15,
                "sand",
            )
        else:
            _lines(slide, section.lines, MARGIN, y, full, bottom)
        _note(slide, section.note, floor)

    out.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(str(out))
    return out
