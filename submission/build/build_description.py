# ruff: noqa: E501
"""Build submission/FalconLens_Project_Description.docx and its PDF export from the same content blocks.

    uv run --no-project --with-requirements submission/build/requirements.txt python submission/build/build_description.py

The .docx uses real heading styles, a table of contents field, page numbers and alt text on every picture.
The PDF is rendered from the same blocks through Chromium (no Word or LibreOffice is needed), with a table of
contents whose page numbers come from a first render of the same file (two passes).
"""

from __future__ import annotations

import datetime as dt
import html
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import description_content as dc  # noqa: E402
import diagrams  # noqa: E402
from common import (  # noqa: E402
    ASSETS,
    FONT_CSS,
    ROOT,
    SHOTS,
    SUBMISSION,
    TEAM,
    WORK,
    heading_pages,
    html_to_pdf,
    inline_html,
    inline_parts,
    load_artifacts,
    repo_url,
    svg_to_png,
)
from docx import Document  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Inches, Pt, RGBColor  # noqa: E402

DOCX = SUBMISSION / "FalconLens_Project_Description.docx"
PDF = SUBMISSION / "FalconLens_Project_Description.pdf"
TITLE = "Falcon Lens | عدسة الصقر: Project description"
ACCENT = RGBColor(0x0B, 0x6E, 0x69)
AR_FONT = "Geeza Pro"


def images() -> dict[str, Path]:
    imgs = diagrams.build_all()
    # The repository diagram quotes the forbidden word in a rule statement. The document never prints that word,
    # so the render comes from a temporary copy with that one phrase removed (the source SVG is not touched).
    inv = (ASSETS / "investigator.svg").read_text(encoding="utf-8")
    inv = inv.replace(' Never the word "safe".', "")
    inv_copy = WORK / "investigator-clean.svg"
    inv_copy.write_text(inv, encoding="utf-8")
    imgs["investigator-detailed"] = svg_to_png(inv_copy, WORK / "investigator-detailed.png")
    imgs["sentinel-detailed"] = svg_to_png(ASSETS / "sentinel.svg", WORK / "sentinel-detailed.png")
    committee = SHOTS / "committee"
    imgs["screenshot-dangerous-en"] = committee / "check-dangerous-1440-en.jpg"
    imgs["screenshot-mobile-ar"] = SHOTS / "03-check-dangerous-390-ar-night.png"
    imgs["screenshot-campaigns-ar"] = SHOTS / "08-campaigns-live-1440-ar-night.png"
    for k, v in imgs.items():
        if not v.is_file():
            raise SystemExit(f"missing image {k}: {v}")
    return imgs


def split_caption(caption: str, n: int) -> str:
    return f"Figure {n}. " + re.sub(r"^Figure \d+\.\s*", "", caption)


# ── DOCX ─────────────────────────────────────────────────────────────────────────────────────────
def _field(paragraph, instr: str, placeholder: str = "") -> None:  # type: ignore[no-untyped-def]
    def fc(kind: str):  # type: ignore[no-untyped-def]
        r = OxmlElement("w:r")
        f = OxmlElement("w:fldChar")
        f.set(qn("w:fldCharType"), kind)
        if kind == "begin":
            f.set(qn("w:dirty"), "true")
        r.append(f)
        return r

    paragraph._p.append(fc("begin"))
    r = OxmlElement("w:r")
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = f" {instr} "
    r.append(it)
    paragraph._p.append(r)
    paragraph._p.append(fc("separate"))
    t = OxmlElement("w:r")
    tt = OxmlElement("w:t")
    tt.text = placeholder
    t.append(tt)
    paragraph._p.append(t)
    paragraph._p.append(fc("end"))


def _shade(cell, hex_fill: str) -> None:  # type: ignore[no-untyped-def]
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _rtl(paragraph) -> None:  # type: ignore[no-untyped-def]
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    pPr.append(bidi)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _runs(paragraph, text: str, size: float | None = None, rtl: bool = False, color: RGBColor | None = None) -> None:  # type: ignore[no-untyped-def]
    for kind, chunk in inline_parts(text):
        run = paragraph.add_run(chunk)
        run.bold = kind == "b" or None
        if kind == "c":
            run.font.name = "Menlo"
            run.font.size = Pt((size or 10.5) - 1)
        elif size:
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color
        if rtl:
            rPr = run._r.get_or_add_rPr()
            rPr.append(OxmlElement("w:rtl"))
            fonts = rPr.find(qn("w:rFonts"))
            if fonts is None:
                fonts = OxmlElement("w:rFonts")
                rPr.insert(0, fonts)
            fonts.set(qn("w:cs"), AR_FONT)
            szcs = OxmlElement("w:szCs")
            szcs.set(qn("w:val"), str(int((size or 10.5) * 2)))
            rPr.append(szcs)
            if kind == "b":
                rPr.append(OxmlElement("w:bCs"))


def _alt(inline_shape, alt: str, title: str) -> None:  # type: ignore[no-untyped-def]
    docPr = inline_shape._inline.docPr
    docPr.set("descr", alt)
    docPr.set("title", title)


def build_docx(blocks: list[dc.Block], imgs: dict[str, Path], date: str) -> None:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.27), Inches(11.69)
    sec.left_margin = sec.right_margin = Inches(0.8)
    sec.top_margin = sec.bottom_margin = Inches(0.8)
    cp = doc.core_properties
    cp.title = TITLE
    cp.author = ", ".join(TEAM)
    cp.subject = "Project description for the judges"
    cp.language = "en-GB"

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for name, size in (("Heading 1", 20), ("Heading 2", 14), ("Heading 3", 11.5)):
        st = doc.styles[name]
        st.font.name = "Calibri"
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = ACCENT
        st.paragraph_format.space_before = Pt(14 if name != "Heading 1" else 6)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.keep_with_next = True

    # footer: page x of y
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = fp.add_run("Falcon Lens | عدسة الصقر  |  Page ")
    fr.font.size = Pt(8)
    _field(fp, "PAGE", "1")
    fp.add_run(" of ").font.size = Pt(8)
    _field(fp, "NUMPAGES", "1")

    # cover
    cover = doc.add_paragraph(style="Title")
    cover.add_run("Falcon Lens")
    ar = doc.add_paragraph()
    _rtl(ar)
    _runs(ar, "**عدسة الصقر**", size=28, rtl=True, color=ACCENT)
    sub = doc.add_paragraph(style="Subtitle")
    sub.add_run("Project description for the judges")
    doc.add_paragraph(
        "An Arabic-first AI agent that protects UAE residents from scam links, fake websites, scam messages and phishing emails, with an evidence-backed verdict in seconds."
    )
    doc.add_paragraph(
        "Entry for Abu Dhabi Police x 42 ScamShield AI. Independent project: not affiliated with or endorsed by Abu Dhabi Police; ready to connect, not connected."
    )
    doc.add_paragraph("Team: " + "; ".join(TEAM))
    doc.add_paragraph(f"Prepared {date}. Repository: {repo_url()}")
    p = doc.add_paragraph()
    r = p.add_run(
        "Reading guide: the Arabic summary comes first, then the English body. Every number is generated from published evaluation artifacts. Where something is not measured or not built, the text says so."
    )
    r.italic = True
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # contents
    heads = [b for b in blocks if b[0] in ("h1", "h2", "ar_h1")]
    doc.add_paragraph("Contents", style="Heading 1")
    toc = doc.add_paragraph()
    _field(
        toc,
        'TOC \\o "1-2" \\h \\z \\u',
        "Open in Word and press F9 (or right-click, Update field) to fill the page numbers.",
    )
    for hb in heads:
        doc.add_paragraph(("Arabic summary: " if hb[0] == "ar_h1" else "") + hb[1])
    settings = doc.settings.element
    upd = OxmlElement("w:updateFields")
    upd.set(qn("w:val"), "true")
    settings.append(upd)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    fig = 0
    for blk in blocks:
        kind = blk[0]
        if kind in ("h1", "h2", "h3"):
            doc.add_paragraph(blk[1], style={"h1": "Heading 1", "h2": "Heading 2", "h3": "Heading 3"}[kind])
        elif kind == "ar_h1":
            h = doc.add_paragraph(style="Heading 1")
            _rtl(h)
            run = h.add_run(blk[1] + "  (Arabic summary)")
            run.font.name = AR_FONT
        elif kind == "p":
            _runs(doc.add_paragraph(), blk[1])
        elif kind == "ar_p":
            p = doc.add_paragraph()
            _rtl(p)
            _runs(p, blk[1], size=11.5, rtl=True)
        elif kind == "ul":
            for item in blk[1]:
                _runs(doc.add_paragraph(style="List Bullet"), item)
        elif kind == "table":
            _, header, rows, widths = blk
            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            total = sum(widths)
            usable = 6.67
            for i, h in enumerate(header):
                c = table.rows[0].cells[i]
                c.text = ""
                _runs(c.paragraphs[0], f"**{h}**", size=9, color=RGBColor(255, 255, 255))
                _shade(c, "0B6E69")
            trPr = table.rows[0]._tr.get_or_add_trPr()
            hdr = OxmlElement("w:tblHeader")
            hdr.set(qn("w:val"), "true")
            trPr.append(hdr)
            for row in rows:
                cells = table.add_row().cells
                for i, text in enumerate(row):
                    cells[i].text = ""
                    is_ar = bool(re.search(r"[؀-ۿ]", text))
                    par = cells[i].paragraphs[0]
                    if is_ar:
                        _rtl(par)
                    _runs(par, text, size=9, rtl=is_ar)
            for row in table.rows:
                cant = OxmlElement("w:cantSplit")
                row._tr.get_or_add_trPr().append(cant)
                for i, w in enumerate(widths):
                    row.cells[i].width = Inches(usable * w / total)
            doc.add_paragraph()
        elif kind == "img":
            _, key, alt, caption, width = blk
            fig += 1
            par = doc.add_paragraph()
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            par.paragraph_format.keep_with_next = True
            shape = par.add_run().add_picture(str(imgs[key]), width=Inches(width))
            _alt(shape, alt, f"Figure {fig}")
            cap = doc.add_paragraph(style="Caption")
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap.add_run(split_caption(caption, fig))
        elif kind == "note":
            t = doc.add_table(rows=1, cols=1)
            t.style = "Table Grid"
            c = t.rows[0].cells[0]
            _shade(c, "E3F4F2")
            c.text = ""
            _runs(c.paragraphs[0], f"**{blk[1]}.** {blk[2]}", size=10)
            doc.add_paragraph()
        elif kind == "pb":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.save(DOCX)


# ── HTML / PDF ───────────────────────────────────────────────────────────────────────────────────
CSS = (
    FONT_CSS
    + """
body{margin:0}
.cover{height:250mm;display:flex;flex-direction:column;justify-content:center;page-break-after:always}
.cover h1{font-size:44pt;margin:0;color:var(--accent);border:0}
.cover .ar{font-size:34pt;color:var(--accent);margin:0 0 8mm 0;text-align:left;direction:rtl}
.cover .sub{font-size:16pt;margin:0 0 8mm 0}
.cover p{margin:2mm 0}
h1{font-size:19pt;color:var(--accent);border-bottom:2px solid var(--accent);padding-bottom:2mm;margin:0 0 4mm 0;break-after:avoid}
h2{font-size:13.5pt;color:var(--accent);margin:6mm 0 2mm 0;break-after:avoid}
h3{font-size:11.5pt;margin:4mm 0 1mm 0;break-after:avoid}
p{margin:0 0 2.6mm 0;orphans:3;widows:3}
ul{margin:0 0 3mm 0;padding-left:5mm}li{margin-bottom:1.2mm}
.ar ul{padding-left:0;padding-right:5mm}
table{border-collapse:collapse;width:100%;margin:2mm 0 4mm 0;font-size:9pt;break-inside:auto}
tr{break-inside:avoid}
th{background:var(--accent);color:#fff;text-align:left;padding:1.6mm 2mm}
td{border:1px solid var(--line);padding:1.5mm 2mm;vertical-align:top}
td[lang=ar]{text-align:right}
tbody tr:nth-child(even) td{background:var(--bg2)}
code{font-size:8.6pt;background:#eef1f4;padding:0 1mm;border-radius:1mm}
figure{margin:3mm 0;text-align:center;break-inside:avoid}
figure img{max-width:100%;height:auto}
figcaption{font-size:8.6pt;color:var(--muted);margin-top:1mm}
.note{background:#e3f4f2;border-left:4px solid var(--accent);padding:2.5mm 3.5mm;margin:3mm 0;border-radius:2mm;break-inside:avoid}
.pb{break-after:page}
.toc{margin:0;padding:0;list-style:none}
.toc li{display:flex;gap:2mm;margin:0.9mm 0;align-items:baseline}
.toc li.l2{padding-left:7mm;font-size:9.5pt}
.toc a{color:inherit;text-decoration:none}
.toc .dots{flex:1;border-bottom:1px dotted #9aa7b2;transform:translateY(-1px)}
.toc .t{font-weight:600}.toc li.l2 .t{font-weight:400}
.arsec{background:#f7fafb;border:1px solid var(--line);border-radius:3mm;padding:4mm 6mm}
.arsec h1{text-align:right}
"""
)


def build_html(blocks: list[dc.Block], imgs: dict[str, Path], date: str, pages: dict[str, int]) -> str:
    out: list[str] = []
    heads: list[tuple[str, str, str, str]] = []  # (level, id, title, outline title)
    fig = 0
    in_ar = False

    def close_ar() -> None:
        nonlocal in_ar
        if in_ar:
            out.append("</section>")
            in_ar = False

    for i, blk in enumerate(blocks):
        kind = blk[0]
        if kind in ("h1", "h2", "ar_h1"):
            close_ar()
            hid = f"h{i}"
            title = blk[1] + ("  (Arabic summary)" if kind == "ar_h1" else "")
            heads.append((("l2" if kind == "h2" else "l1"), hid, title, blk[1]))
            if kind == "ar_h1":
                out.append('<section class="arsec" lang="ar" dir="rtl">')
                in_ar = True
                out.append(f'<h1 id="{hid}" lang="ar" dir="rtl">{html.escape(blk[1])}</h1>')
            else:
                out.append(f'<{kind} id="{hid}">{html.escape(blk[1])}</{kind}>')
        elif kind == "h3":
            out.append(f"<h3>{html.escape(blk[1])}</h3>")
        elif kind == "p":
            out.append(f"<p>{inline_html(blk[1])}</p>")
        elif kind == "ar_p":
            out.append(f'<p lang="ar" dir="rtl" class="ar">{inline_html(blk[1])}</p>')
        elif kind == "ul":
            out.append("<ul>" + "".join(f"<li>{inline_html(x)}</li>" for x in blk[1]) + "</ul>")
        elif kind == "table":
            _, header, rows, widths = blk
            total = sum(widths)
            cols = "".join(f'<col style="width:{100 * w / total:.1f}%">' for w in widths)
            head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
            body = ""
            for row in rows:
                body += (
                    "<tr>"
                    + "".join(
                        f"<td{' lang=ar dir=rtl' if re.search(r'[؀-ۿ]', c) else ''}>{inline_html(c)}</td>" for c in row
                    )
                    + "</tr>"
                )
            out.append(f"<table><colgroup>{cols}</colgroup><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif kind == "img":
            _, key, alt, caption, width = blk
            fig += 1
            wmm = min(width, 6.5) * 25.4
            out.append(
                f'<figure><img src="{imgs[key].resolve().as_uri()}" alt="{html.escape(alt)}" style="width:{wmm:.0f}mm"><figcaption>{html.escape(split_caption(caption, fig))}</figcaption></figure>'
            )
        elif kind == "note":
            out.append(f'<div class="note"><strong>{html.escape(blk[1])}.</strong> {inline_html(blk[2])}</div>')
        elif kind == "pb":
            close_ar()
            out.append('<div class="pb"></div>')
    close_ar()

    toc = "".join(
        f'<li class="{lvl}"><a class="t" href="#{hid}">{html.escape(t)}</a><span class="dots"></span><span>{pages.get(re.sub(r"\s+", "", raw), "")}</span></li>'
        for lvl, hid, t, raw in heads
    )
    cover = f"""<div class="cover"><h1>Falcon Lens</h1><div class="ar" lang="ar" dir="rtl">عدسة الصقر</div>
<div class="sub">Project description for the judges</div>
<p>An Arabic-first AI agent that protects UAE residents from scam links, fake websites, scam messages and phishing emails, with an evidence-backed verdict in seconds.</p>
<p>Entry for Abu Dhabi Police x 42 ScamShield AI. Independent project: not affiliated with or endorsed by Abu Dhabi Police; ready to connect, not connected.</p>
<p><strong>Team:</strong> {html.escape("; ".join(TEAM))}</p>
<p>Prepared {date}. Repository: {html.escape(repo_url())}</p>
<p><em>Reading guide: the Arabic summary comes first, then the English body. Every number is generated from published evaluation artifacts. Where something is not measured or not built, the text says so.</em></p></div>"""
    toc_page = f'<h1 id="toc">Contents</h1><ul class="toc">{toc}</ul><div class="pb"></div>'
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(TITLE)}</title><style>{CSS}</style></head><body>{cover}{toc_page}{"".join(out)}</body></html>'


def main() -> int:
    a = load_artifacts()
    blocks = dc.build(a)
    imgs = images()
    date = dt.date.today().strftime("%d %B %Y")
    WORK.mkdir(parents=True, exist_ok=True)
    html_path = WORK / "description.html"
    html_path.write_text(build_html(blocks, imgs, date, {}), encoding="utf-8")
    html_to_pdf(html_path, PDF, "Falcon Lens | Project description")
    pages = heading_pages(PDF)
    html_path.write_text(build_html(blocks, imgs, date, pages), encoding="utf-8")
    html_to_pdf(html_path, PDF, "Falcon Lens | Project description")
    build_docx(blocks, imgs, date)
    shutil.copy(html_path, WORK / "description.final.html")
    print(f"wrote {DOCX.relative_to(ROOT)} and {PDF.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
