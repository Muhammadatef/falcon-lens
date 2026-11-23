#!/usr/bin/env python3
# ruff: noqa: E501  (slide copy reads better unwrapped)
"""Build the ScamShield AI presentation: submission/FalconLens_ScamShield.pptx and .pdf.

    uv run --with-requirements scripts/submission/requirements.txt python submission/build/build_deck.py

One layout description (the shapes below) is written twice: to a .pptx with python-pptx
(1.0.2) and to an HTML page that Chromium prints to the PDF and screenshots for visual QA
(`--qa-dir`). So the PDF is the same deck, with the same fonts, and every slide can be looked
at without PowerPoint or LibreOffice.

Rules (CLAUDE.md), enforced by construction and by `check_text()`:
- Every number comes from the newest published eval artifact (`evals/results/published/*.json`)
  or the newest `fp_regress` run beside it. No number is typed here: slide text spells counts as
  words, and the build then traces every digit with scripts/submission/check_numbers.py.
- A line tied to a capability that is not shipped in this checkout gets a "Planned" prefix.
- The tools shown are the generated list (scripts/submission/tools_used.py), never a typed one.
- Never the word "safe", never an implied link to Abu Dhabi Police, no police logo or mark.
- Images are PNG. Demo and replay data is labelled on the slide.

Fonts: the .pptx uses Arial (no missing-font prompt in Keynote, PowerPoint or Google Slides); the PDF embeds Readex Pro, the product font.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from submission import artifact as artifact_mod  # noqa: E402
from submission import capabilities as caps_mod  # noqa: E402
from submission import check_numbers, descriptions  # noqa: E402
from submission import content as content_mod  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_card  # noqa: E402

OUT_PPTX = ROOT / "submission" / "FalconLens_ScamShield.pptx"
OUT_PDF = ROOT / "submission" / "FalconLens_ScamShield.pdf"
CACHE = ROOT / "submission" / "build" / ".cache"
MAX_BYTES = 20 * 1024 * 1024
REPO_URL_DEFAULT = "https://github.com/Muhammadatef/falcon-lens"
W, H = 13.333, 7.5
MARGIN = 0.6
FONT = "Readex Pro"
# The .pptx names a font every Mac and Windows machine has: Keynote shows a missing-font sheet for Readex Pro and
# blocks scripted opens. Arial carries Arabic. The PDF and the QA renders keep Readex Pro (embedded).
PPTX_FONT = "Arial"
FONT_FILES = {
    "latin": ("web/public/fonts/readex-pro-latin-wght-normal.woff2", "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"),
    "arabic": ("web/public/fonts/readex-pro-arabic-wght-normal.woff2", "U+0600-06FF,U+0750-077F,U+0870-088E,U+0890-0891,U+0898-08E1,U+08E3-08FF,U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FE74,U+FE76-FEFC"),
}  # fmt: skip

# Night palette: the colours of web/design/tokens.css (see web/design/v2/DESIGN_SPEC.md section 6).
C = {
    "bg": "070b14",
    "s1": "0e1626",
    "s2": "16203a",
    "s3": "1f2c4c",
    "border": "2a3757",
    "text": "f2eee6",
    "muted": "aeb8cc",
    "faint": "8794ae",
    "brand": "3fe0c5",
    "brand_ink": "04211d",
    "sand": "e7d7b6",
    "danger": "ff8589",
    "danger_solid": "d42a38",
    "danger_tint": "2b0f15",
    "danger_line": "8c2630",
    "warn": "ffc55c",
    "warn_tint": "2a1d07",
    "warn_line": "8a6416",
    "nws": "a9c0ff",
    "nws_tint": "111c3d",
    "nws_line": "34488c",
}


# ── drawing model ────────────────────────────────────────────────────────────
@dataclass
class Run:
    text: str
    size: float
    color: str = "text"
    bold: bool = False


@dataclass
class Para:
    runs: list[Run]
    align: str = "l"  # l | r | c
    after: float = 0  # points of space after
    rtl: bool | None = None  # None: decided from the first letter


@dataclass
class TextBox:
    x: float
    y: float
    w: float
    h: float
    paras: list[Para]
    anchor: str = "t"  # t | m | b


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    fill: str | None = None
    line: str | None = None
    shape: str = "rect"  # rect | round | oval
    radius: float = 0.12  # inches, round only
    line_w: float = 1.0
    dash: bool = False


@dataclass
class Pic:
    path: Path
    x: float
    y: float
    w: float
    h: float
    alt: str = ""


Shape = TextBox | Box | Pic


@dataclass
class Slide:
    key: str
    title_en: str
    title_ar: str
    shapes: list[Shape] = field(default_factory=list)
    notes: str = ""

    def add(self, *shapes: Shape) -> None:
        self.shapes.extend(shapes)


def is_arabic(text: str) -> bool:
    for ch in text:
        if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ":
            return True
        if ch.isalpha():
            return False
    return False


def p(text: str, size: float, color: str = "text", bold: bool = False, align: str = "l", after: float = 0) -> Para:
    return Para([Run(text, size, color, bold)], align, after)


def tb(x: float, y: float, w: float, h: float, *paras: Para, anchor: str = "t") -> TextBox:
    return TextBox(x, y, w, h, list(paras), anchor)


def card(
    x: float, y: float, w: float, h: float, fill: str = "s1", line: str | None = "border", dash: bool = False
) -> Box:
    return Box(x, y, w, h, fill, line, "round", 0.14, 1.0, dash)


def chip(
    slide: Slide,
    x: float,
    y: float,
    w: float,
    text: str,
    fg: str = "warn",
    fill: str = "warn_tint",
    line: str = "warn_line",
    size: float = 13,
    h: float = 0.36,
) -> None:
    slide.add(Box(x, y, w, h, fill, line, "round", h / 2), tb(x, y, w, h, p(text, size, fg, True, "c"), anchor="m"))


def lens(slide: Slide, x: float, y: float, size: float, color: str = "brand") -> None:
    inner = size * 0.36
    slide.add(
        Box(x, y, size, size, None, color, "oval", line_w=2.25),
        Box(x + (size - inner) / 2, y + (size - inner) / 2, inner, inner, color, None, "oval"),
    )


def radar(slide: Slide, x: float, y: float, size: float, color: str = "sand") -> None:
    """The Sentinel glyph: two rings and a sweep dot."""
    slide.add(Box(x, y, size, size, None, color, "oval", line_w=2.25))
    mid = size * 0.5
    ring = size * 0.5
    slide.add(Box(x + (size - ring) / 2, y + (size - ring) / 2, ring, ring, None, color, "oval", line_w=1.25))
    dot = size * 0.13
    slide.add(
        Box(x + mid - dot / 2, y + mid - dot / 2, dot, dot, color, None, "oval"),
        Box(x + size * 0.68, y + size * 0.2, dot, dot, color, None, "oval"),
    )


# ── content helpers ──────────────────────────────────────────────────────────
def pct(value: Any) -> str:
    """0.983333 -> '98.3%'. Exact decimal arithmetic on the artifact's own digits."""
    return f"{(Decimal(str(value)) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def humanise(key: str) -> str:
    text = key.replace("_", " ")
    for a, b in (("arabic", "Arabic"), ("llm", "LLM")):
        text = text.replace(a, b)
    return text


def newest_fp_regress(published: Path) -> dict[str, Any] | None:
    return artifact_mod.load_fp_regress(published)


@dataclass
class Facts:
    """Everything the deck quotes from artifacts and from the checkout."""

    artifact: artifact_mod.Artifact | None
    fp: dict[str, Any] | None
    caps: dict[str, bool]
    repo_url: str
    tools: list[tuple[str, list[str]]]
    roadmap: list[str]

    def metric(self, key: str) -> Any:
        if self.artifact is None:
            raise KeyError(key)
        for k, v in self.artifact.metrics:
            if k == key:
                return v
        raise KeyError(f"{key} is not in {self.artifact.path.name}")

    def planned(self, cap: str | None, text: str) -> str:
        return text if cap is None or self.caps.get(cap, False) else f"Planned: {text[0].lower()}{text[1:]}"


def gather(root: Path) -> Facts:
    caps = caps_mod.detect(root)
    published = root / "evals" / "results" / "published"
    art = artifact_mod.load(published)
    fp = artifact_mod.load_fp_regress(published)
    url = REPO_URL_DEFAULT
    sections = content_mod.build(caps, art, url)
    road = next(s for s in sections if s.key == "roadmap")
    roadmap = [line.text for line in road.lines]
    return Facts(art, fp, caps, url, project_card.shipped_tools(root), roadmap)


# ── slides ───────────────────────────────────────────────────────────────────
def frame(slide: Slide, number: int, total: int) -> None:
    """Background chrome: top rule, lens mark, wordmark, independence line, bilingual title."""
    slide.shapes[:0] = [Box(0, 0, W, 0.07, "brand")]
    lens(slide, MARGIN, 0.34, 0.38)
    slide.add(
        tb(MARGIN + 0.55, 0.3, 5.5, 0.46, p("Falcon Lens | عدسة الصقر", 15, "sand", True), anchor="m"),
        tb(
            W - MARGIN - 6.2,
            0.3,
            6.2,
            0.46,
            p("An independent project. Not affiliated with Abu Dhabi Police.", 12, "faint", align="r"),
            anchor="m",
        ),
        tb(MARGIN, 0.9, 7.9, 0.75, p(slide.title_en, 34, "text", True), anchor="m"),
        tb(W - MARGIN - 4.4, 0.9, 4.4, 0.75, p(slide.title_ar, 30, "sand", True, "r"), anchor="m"),
    )


def bullets(
    slide: Slide,
    x: float,
    y: float,
    w: float,
    items: Sequence[tuple[str, str]],
    size: float = 20,
    gap: float = 0.16,
    row_h: float = 0.9,
    accent: str = "brand",
) -> float:
    """Cards with a dot, a bold lead and a muted body. Returns the y below the last card."""
    for lead, body in items:
        slide.add(card(x, y, w, row_h), Box(x + 0.22, y + row_h / 2 - 0.07, 0.14, 0.14, accent, None, "oval"))
        paras = [Para([Run(lead, size, "text", True), Run(("  " + body) if body else "", size - 2, "muted")])]
        slide.add(tb(x + 0.5, y, w - 0.7, row_h, *paras, anchor="m"))
        y += row_h + gap
    return y


def slide_problem(f: Facts) -> Slide:
    s = Slide("problem", "The problem", "المشكلة")
    s.add(
        tb(MARGIN, 1.85, 12.1, 1.0, p("A blocklist lists a scam page only after it is reported.", 30, "text", True)),
        tb(
            MARGIN,
            2.9,
            12.1,
            0.55,
            p("القائمة السوداء لا تُدرج الصفحة إلا بعد أن يبلّغ عنها أحد.", 22, "sand", False, "r"),
        ),
    )
    items = [
        (
            "Scams arrive where you chat",
            "Fake fines, delivery fees, bank one-time codes and UAE Pass links by SMS, WhatsApp and email.",
        ),
        (
            "A new copy is on no list",
            "A page that copies an official site and has not been reported yet is on no blocklist.",
        ),
        (
            "Warnings people cannot use",
            "A warning in English and in security jargon does not help someone who reads neither.",
        ),
    ]
    w, g = 3.8, 0.365
    for i, (head, body) in enumerate(items):
        x = MARGIN + i * (w + g)
        s.add(card(x, 3.7, w, 2.75), Box(x, 3.7, w, 0.08, "brand" if i != 1 else "sand", None, "rect"))
        s.add(
            tb(x + 0.28, 3.95, w - 0.56, 0.75, p(head, 20, "text", True), anchor="t"),
            tb(x + 0.28, 4.75, w - 0.56, 1.6, p(body, 17, "muted")),
        )
    s.add(
        tb(
            MARGIN,
            6.65,
            12.1,
            0.4,
            p(
                "This slide quotes no statistics on purpose: a figure appears in this project only with a public source link.",
                13,
                "faint",
            ),
        )
    )
    s.notes = (
        "Start with the person, not the technology. A resident gets a message about a fine, a delivery fee or a bank code, "
        "with a link. The page behind it copies the real one. A blocklist can only list a page after someone has reported it, "
        "so a page that is new today is on no list today. And a warning written in English and technical language does not "
        "help someone who reads neither. We quote no statistic here, on purpose: we put a figure in this project only when we can show its public source. "
        "Transition: so we built something that answers in clear Arabic, in seconds."
    )
    return s


def verdict_row(s: Slide, x: float, y: float, w: float, en: str, ar: str, fg: str, fill: str, line: str) -> None:
    s.add(Box(x, y, w, 0.62, fill, line, "round", 0.31), Box(x + 0.24, y + 0.23, 0.16, 0.16, fg, None, "oval"))
    s.add(
        tb(x + 0.55, y, w - 3.9, 0.62, p(en, 19, fg, True), anchor="m"),
        tb(x + w - 3.45, y, 3.25, 0.62, p(ar, 17, fg, True, "r"), anchor="m"),
    )


def slide_solution(f: Facts, img: dict[str, Path]) -> Slide:
    s = Slide("solution", "The solution, in one line", "الحل في سطر")
    s.add(
        tb(MARGIN, 1.85, 7.4, 0.95, p("Check before you tap.", 44, "brand", True), anchor="m"),
        tb(MARGIN, 2.8, 7.4, 0.65, p("افحص قبل أن تضغط", 32, "sand", True, "r"), anchor="m"),
        tb(
            MARGIN,
            3.6,
            7.4,
            1.2,
            p(
                "Paste a link, message, email or image. Falcon Lens answers in clear Arabic: what it found, why, and what to do now.",
                20,
                "text",
            ),
        ),
    )
    verdict_row(s, MARGIN, 4.95, 7.4, "Dangerous", "خطِر", "danger", "danger_tint", "danger_line")
    verdict_row(s, MARGIN, 5.67, 7.4, "Suspicious", "مريب", "warn", "warn_tint", "warn_line")
    verdict_row(s, MARGIN, 6.39, 7.4, "No warning signs found", "لم نجد علامات تحذير", "nws", "nws_tint", "nws_line")
    pic = img["check"]  # 767 x 840 design render
    from PIL import Image  # noqa: PLC0415

    with Image.open(pic) as im:
        ph = 4.75
        pw = ph * im.width / im.height
    px = W - MARGIN - pw
    s.add(
        Pic(
            pic,
            px,
            1.85,
            pw,
            ph,
            "Screenshot of the Falcon Lens result page: a Dangerous verdict with three reasons and what to do now",
        ),
        Box(px, 1.85, pw, ph, None, "border", "round", 0.14),
    )
    chip(s, W - MARGIN - 3.6, 6.68, 3.6, "Demo data, not a real check", size=12)
    s.notes = (
        "One line: check before you tap. You paste a link, a message, an email or an image, and you get one clear answer in Arabic: "
        "what we found, why, and what to do now, including what to do if you already clicked. There are three verdicts: Dangerous, Suspicious, "
        "and No warning signs found. The lowest verdict always carries a caution reminder, because no checker can promise that. "
        "The picture on the right is a screenshot of the result page with demo data, labelled as such."
    )
    return s


def agent_card(
    s: Slide, x: float, w: float, accent: str, name_en: str, name_ar: str, role: str, lines: Sequence[str], glyph: str
) -> None:
    s.add(card(x, 1.9, w, 4.05), Box(x, 1.9, w, 0.09, accent, None, "rect"))
    (lens if glyph == "lens" else radar)(s, x + 0.35, 2.3, 0.75, accent)
    s.add(
        tb(x + 1.35, 2.2, w - 1.65, 0.5, p(name_en, 26, "text", True), anchor="m"),
        tb(x + 1.35, 2.68, w - 1.65, 0.4, p(f"{name_ar}  ·  {role}", 16, accent), anchor="m"),
    )
    y = 3.3
    for line in lines:
        s.add(
            Box(x + 0.37, y + 0.12, 0.12, 0.12, accent, None, "oval"),
            tb(x + 0.65, y, w - 0.95, 0.85, p(line, 17, "muted")),
        )
        y += 0.88


def slide_agents(f: Facts) -> Slide:
    s = Slide("agents", "Two AI agents", "وكيلان ذكيان")
    w = 5.95
    agent_card(
        s, MARGIN, w, "brand", "The Investigator", "المحقّق", "judges one input", glyph="lens",
        lines=(
            f.planned("url_check", "Checks a link, message, email or image in tiers, from known lists to an isolated page visit."),
            f.planned("investigator", "An AI model reads only the uncertain cases, through typed tools."),
            "A fixed arbiter, not the AI, sets the verdict.",
        ),
    )  # fmt: skip
    agent_card(
        s, MARGIN + w + 0.2, w, "sand", "The Sentinel", "الحارس", "watches around the clock", glyph="radar",
        lines=(
            f.planned("sentinel_agent", "Links similar checks into campaigns and incidents."),
            "Blocks indicators inside the system, reversibly, and drafts takedown requests.",
            "Nothing leaves the system until a human approves it.",
        ),
    )  # fmt: skip
    s.add(
        card(MARGIN, 6.15, 12.1, 1.0, "s2", "border"),
        tb(
            MARGIN + 0.3,
            6.15,
            11.5,
            1.0,
            p("AI helps, evidence decides, a human approves.", 18, "sand", True, "c"),
            p("الذكاء الاصطناعي يساعد، والأدلة تحسم، والإنسان يوافق", 17, "sand", False, "c"),
            anchor="m",
        ),
    )
    s.notes = (
        "Falcon Lens is two AI agents. The Investigator judges one input: it works through a cascade of checks, from quick known-list lookups to an isolated page visit, "
        "and an AI model is used only for the uncertain cases. The Sentinel works for everyone else. It runs around the clock, links similar checks into campaigns, blocks indicators inside our own system, "
        "and drafts takedown requests that wait for a human. The principle on the bottom line is the design of the whole product: AI helps, evidence decides, a human approves."
    )
    return s


def slide_how(f: Facts) -> Slide:
    s = Slide("how", "How a check works", "كيف يعمل الفحص")
    steps = [
        ("Paste", "ألصق", "A link, a message, an email file or a picture. Or share it from the phone."),
        (
            "Investigate",
            "حقّق",
            "Known lists, then URL signals, then a passive visit in an isolated browser. Tiers T0 to T3.",
        ),
        ("Decide", "احكم", "A fixed arbiter turns the evidence into a score and a verdict. The AI never sets it."),
        ("Explain", "اشرح", "Arabic answer: why, with the evidence behind each reason, and what to do now."),
    ]
    w, g = 2.85, 0.233
    for i, (en, ar, body) in enumerate(steps):
        x = MARGIN + i * (w + g)
        s.add(card(x, 2.0, w, 4.0), Box(x, 2.0, w, 0.09, "brand", None, "rect"))
        lens(s, x + 0.3, 2.35, 0.62)
        s.add(
            tb(x + 0.3, 3.1, w - 0.6, 0.55, p(en, 26, "text", True), anchor="m"),
            tb(x + 0.3, 3.62, w - 0.6, 0.45, p(ar, 20, "sand", True, "r"), anchor="m"),
        )
        s.add(tb(x + 0.3, 4.2, w - 0.6, 1.75, p(body, 17, "muted")))
    s.add(
        tb(
            MARGIN,
            6.3,
            12.1,
            0.75,
            p(
                "Most checks end in the early, deterministic tiers. The language model is called only for the uncertain band, and only on structured evidence, never on raw page text.",
                17,
                "faint",
            ),
        )
    )
    s.notes = (
        "Four steps. You paste or share. The Investigator works through tiers, and it stops as early as the evidence allows: known lists first, then URL and domain signals, "
        "then a passive visit to the page in an isolated browser that never submits a form. A deterministic arbiter then turns the evidence into a score and a verdict. "
        "The language model never sets a score. It only reads structured evidence for the uncertain cases and helps explain. Finally you get the answer in Arabic, with the evidence behind every reason."
    )
    return s


def slide_sentinel(f: Facts, img: dict[str, Path]) -> Slide:
    s = Slide("sentinel", "Sentinel and approval", "الحارس والموافقة")
    pw = 6.1
    ph = pw * 780 / 1152
    s.add(
        Pic(
            img["campaigns"],
            MARGIN,
            1.9,
            pw,
            ph,
            "Design view of the live campaign board: three campaigns with linked checks and a radar of similar checks",
        ),
        Box(MARGIN, 1.9, pw, ph, None, "border", "round", 0.14),
    )
    chip(s, MARGIN, 1.9 + ph + 0.12, pw, "Replay and demo data, labelled in the product", size=12)
    x = MARGIN + pw + 0.45
    w = W - MARGIN - x
    flow = [
        ("Linked checks", "Many similar checks become one campaign.", "brand"),
        ("Internal block", "Automatic, reversible, with an expiry.", "brand"),
        ("Takedown draft", "Prepared for the operator. Not sent.", "sand"),
        ("Human approves", "Only then can anything leave the system.", "warn"),
    ]
    y = 1.9
    for i, (head, body, colour) in enumerate(flow):
        s.add(card(x, y, w, 0.95), Box(x, y, 0.1, 0.95, colour, None, "rect"))
        s.add(
            tb(
                x + 0.35,
                y,
                w - 0.5,
                0.95,
                Para([Run(head, 19, "text", True)], after=2),
                p(body, 16, "muted"),
                anchor="m",
            )
        )
        if i < 3:
            s.add(Box(x + w / 2 - 0.02, y + 0.95, 0.04, 0.2, "border", None, "rect"))
        y += 1.15
    s.add(
        tb(
            x,
            y + 0.02,
            w,
            0.7,
            p(f.planned("audit_log", "Every action is written to an append-only audit log."), 16, "faint"),
        )
    )
    s.notes = (
        "One check protects one person. The Sentinel protects everyone else. It links similar checks into a campaign, opens an incident, and takes the actions that can be automated and undone: "
        "blocking the indicators inside our own system, which is reversible and expires. Anything that would leave the system, such as a takedown request, is only a draft until a human operator approves it. "
        "Every action is written to an append-only audit log. The screenshot is the live campaign board running on replay and demo data, and it is labelled that way in the product."
    )
    return s


def stat_card(
    s: Slide, x: float, y: float, w: float, h: float, value: str, label: str, ci: str, colour: str = "brand"
) -> None:
    s.add(card(x, y, w, h), tb(x + 0.3, y + 0.15, w - 0.6, 0.95, p(value, 46, colour, True), anchor="m"))
    s.add(
        tb(x + 0.3, y + 1.12, w - 0.6, 0.7, p(label, 17, "text", True)),
        tb(x + 0.3, y + h - 0.5, w - 0.6, 0.38, p(ci, 13, "faint"), anchor="m"),
    )


def slide_results(f: Facts) -> Slide:
    s = Slide("results", "Measured, not claimed", "أرقام مقيسة، لا ادعاءات")
    art = f.artifact
    if art is None:
        s.add(
            card(MARGIN, 2.2, 12.1, 2.6),
            tb(MARGIN, 2.2, 12.1, 2.6, p("Evaluation in progress", 44, "sand", True, "c"), anchor="m"),
        )
        s.notes = "No evaluation artifact is published in this build, so the slide shows no number. Numbers appear here only when the evaluation run has produced them."
        return s
    recall, recall_ci = f.metric("test.recall"), f.metric("test.recall_ci95")
    fpr, fpr_ci = f.metric("test.fpr"), f.metric("test.fpr_ci95")
    n, official = f.metric("test.n"), f.metric("test.official_false_dangerous")
    w, g = 3.85, 0.275
    ci = lambda c: f"bootstrap interval {pct(c[0])} to {pct(c[1])}"  # noqa: E731
    stat_card(s, MARGIN, 1.85, w, 2.3, pct(recall), "Phishing links caught", ci(recall_ci))
    stat_card(s, MARGIN + w + g, 1.85, w, 2.3, pct(fpr), "Legitimate links wrongly flagged", ci(fpr_ci), "warn")
    stat_card(
        s,
        MARGIN + 2 * (w + g),
        1.85,
        w,
        2.3,
        str(official),
        "Official sites marked Dangerous",
        "on the same frozen test split",
        "brand",
    )
    s.add(
        tb(
            MARGIN,
            4.25,
            12.1,
            0.6,
            p(
                f"Scope: offline model and arbiter on URLs, real data only, frozen test split of {n} links. It is not a measurement of the whole system.",
                15,
                "muted",
            ),
        )
    )
    fp = f.fp
    if fp is not None:
        fv, fci, fn, target = (
            fp["false_positive_rate"]["value"],
            fp["false_positive_rate"]["ci95"],
            fp["n"],
            fp["target"],
        )
        degraded = fp["degraded"]
        s.add(card(MARGIN, 4.95, 12.1, 1.55, "warn_tint", "warn_line"))
        s.add(tb(MARGIN + 0.3, 4.95, 2.7, 1.55, p(pct(fv), 40, "warn", True), anchor="m"))
        s.add(
            tb(
                MARGIN + 3.0, 4.95, 8.9, 1.55,
                Para([Run("Live end-to-end check on held-out legitimate sites: flagged Suspicious or Dangerous.", 17, "text", True)], after=3),
                p(f"{fn} sites, bootstrap interval {pct(fci[0])} to {pct(fci[1])}. Our target is {pct(target)}. {degraded} of those runs could not complete every check, and such a run is never shown as a clean result. We report it as it is.", 14, "muted"),
                anchor="m",
            )
        )  # fmt: skip
    ne = [humanise(k) for k in (art.not_evaluated or [])]
    if ne:
        s.add(tb(MARGIN, 6.55, 12.1, 0.8, p("Not measured yet: " + ", ".join(ne) + ".", 12, "faint")))
    s.notes = (
        f"Every number on this slide is copied by code from the published evaluation file {art.path.name}, with its bootstrap confidence interval. "
        "Read the scope line first: this is the offline model plus the arbiter on URLs, on a frozen test split, real data only. It is not a measurement of the whole system. "
        "The amber box is the harder number, and we show it because honesty matters more than a clean slide: when we run the full pipeline on held-out legitimate sites, "
        "too many are flagged, and many of those are checks that could not finish. A check that cannot finish is shown as Suspicious, never as a clean result. Our target is much lower, and this is our top engineering item. "
        "Anything not yet measured is listed at the bottom."
    )
    return s


def slide_security(f: Facts) -> Slide:
    s = Slide("security", "Security and privacy", "الأمن والخصوصية")
    cells = [
        (
            "Models explain, code decides",
            "A page cannot talk the model into a lower score: model output never reaches the score.",
            "injection_defence",
        ),
        (
            "Untrusted text is quarantined",
            "Page text is marked and read only by an extractor that has no tools.",
            "injection_defence",
        ),
        (
            "Passive, isolated visits",
            "One normal visit in a sandbox. No form is ever submitted, no login ever typed.",
            "brand_check",
        ),
        ("SSRF guard", "Own DNS resolution, private ranges blocked, every redirect re-checked.", "url_check"),
        ("Private by default", "Personal data is redacted before logs and before any cloud call.", "sovereign"),
        (
            "Sovereign mode",
            "Every model call stays on the local machine. Its accuracy is not yet measured.",
            "sovereign",
        ),
    ]
    w, h, gx, gy = 3.85, 2.2, 0.275, 0.25
    for i, (head, body, cap) in enumerate(cells):
        x = MARGIN + (i % 3) * (w + gx)
        y = 1.9 + (i // 3) * (h + gy)
        s.add(card(x, y, w, h), Box(x, y, 0.1, h, "brand" if i % 2 == 0 else "sand", None, "rect"))
        s.add(
            tb(
                x + 0.35,
                y + 0.2,
                w - 0.6,
                h - 0.35,
                Para([Run(head, 19, "text", True)], after=6),
                p(f.planned(cap, body), 16, "muted"),
            )
        )
    s.add(
        tb(
            MARGIN,
            6.7,
            12.1,
            0.45,
            p(
                "We never ask for personal, banking or ID details. We never give a guarantee.   لا نطلب منك أبداً بيانات شخصية أو مصرفية أو رقم هوية.",
                14,
                "faint",
            ),
        )
    )
    s.notes = (
        "A checker reads content that attackers control, so we designed it as a target. Models read and explain; code decides, so a page that says ignore your instructions cannot lower a score, and the attempt itself becomes evidence. "
        "Untrusted text is marked and read only by an extractor with no tools. Pages are visited once, passively, in an isolated browser, and we never submit a form. The fetcher blocks private network ranges and re-checks every redirect. "
        "Personal data is redacted before logging and before any cloud call, and in sovereign mode every model call stays on the local machine."
    )
    return s


def slide_authorities(f: Facts) -> Slide:
    s = Slide("authorities", "For authorities", "للجهات المختصة")
    s.add(tb(MARGIN, 1.8, 12.1, 0.7, p("Ready to connect. Not connected.", 30, "brand", True), anchor="m"))
    surfaces = [
        ("REST API", "with an OpenAPI description, keys and scopes", "rest_api"),
        ("MCP server", "so another agent can call the checks as tools", "mcp"),
        ("STIX 2.1 export", "of incident indicators for intelligence sharing", "stix"),
        ("Signed webhooks", "campaign alerts with an HMAC signature", None),
        ("Operator board", "the Sentinel proposes, a human approves", "ops_board"),
        ("Sovereign mode", "all model calls stay on local hardware (accuracy not yet measured)", "sovereign"),
    ]
    w, h, gx, gy = 3.85, 1.35, 0.275, 0.2
    for i, (head, body, cap) in enumerate(surfaces):
        x = MARGIN + (i % 3) * (w + gx)
        y = 2.65 + (i // 3) * (h + gy)
        s.add(
            card(x, y, w, h),
            tb(
                x + 0.3,
                y + 0.1,
                w - 0.5,
                1.15,
                Para([Run(head, 20, "text", True)], after=2),
                p(f.planned(cap, body), 15, "muted"),
                anchor="m",
            ),
        )
    s.add(card(MARGIN, 5.75, 12.1, 1.25, "s1", "faint", dash=True))
    s.add(
        tb(
            MARGIN + 0.3, 5.75, 11.5, 1.25,
            Para([Run("No integration with Abu Dhabi Police exists, and none is implied.", 17, "text", True)], after=3),
            p("A real connection needs an agreement with the receiving organisation. External actions stay drafts until a human approves them.   جاهز للربط وليس مربوطاً بأي جهة.", 14, "muted"),
            anchor="m",
        )
    )  # fmt: skip
    s.notes = (
        "This slide is about what we offer, stated carefully. Falcon Lens is an independent project. It is ready to connect and it is not connected to any police system, and we do not imply endorsement. "
        "If an authority wants to connect, there is a REST interface with an OpenAPI description, an MCP server so another agent can use the checks as tools, a STIX export of incident indicators, signed webhooks for campaign alerts, "
        "and an operator board where a human approves or rejects what the Sentinel proposes. In sovereign mode every model call stays on local hardware. A real connection would need an agreement with the receiving organisation."
    )
    return s


GROUPS: list[tuple[str, list[str]]] = [
    ("AI and agents", ["LangGraph", "Anthropic API", "Ollama", "Model Context Protocol Python SDK", "scikit-learn"]),
    ("Backend", ["Python", "FastAPI", "Pydantic", "Playwright", "Redis", "pgvector"]),
    ("Web", ["Next.js", "React", "TypeScript", "motion"]),
    ("Operations", ["Docker Compose", "Caddy", "Prometheus", "Grafana", "OpenTelemetry SDK", "Arize Phoenix"]),
]


DISPLAY = {
    "Prometheus Python client": "Prometheus",
    "OpenTelemetry SDK": "OpenTelemetry",
    "Model Context Protocol Python SDK": "MCP SDK",
    "pgvector (PostgreSQL)": "PostgreSQL + pgvector",
    "Anthropic API (Claude models)": "Claude models",
    "Ollama (local models)": "Ollama local models",
}


def shown_tools(f: Facts) -> list[tuple[str, list[str]]]:
    """The curated groups, filtered to what the generated list contains. Nothing is shown that is not shipped."""
    generated = [name for _, items in f.tools for name in items]
    rows = []
    for title, wanted in GROUPS:
        found = []
        for want in wanted:
            hit = next((g for g in generated if want.lower() in g.lower()), None)
            if hit:
                found.append(DISPLAY.get(hit, re.sub(r" \(.*\)$", "", hit)))
        if found:
            rows.append((title, found))
    return rows


def slide_architecture(f: Facts, img: dict[str, Path]) -> Slide:
    s = Slide("architecture", "Architecture and tech stack", "المعمارية والتقنيات")
    ph = 4.95
    pw = ph * 1200 / 870
    s.add(
        Pic(
            img["arch"],
            MARGIN,
            1.85,
            pw,
            ph,
            "Falcon Lens architecture: gateway, API, worker cascade, sandbox behind an egress proxy, Sentinel, data stores and observability",
        ),
        Box(MARGIN, 1.85, pw, ph, None, "border", "round", 0.1),
    )
    x = MARGIN + pw + 0.35
    w = W - MARGIN - x
    y = 1.85
    for title, names in shown_tools(f):
        s.add(tb(x, y, w, 0.35, p(title, 14, "brand", True), anchor="m"))
        s.add(tb(x, y + 0.36, w, 0.75, p(" · ".join(names), 14, "text")))
        y += 1.2
    s.add(
        tb(
            MARGIN,
            6.95,
            12.1,
            0.35,
            p(
                "The tools shown are generated from the lockfiles and the compose file. Full list: submission/PROJECT_CARD.md.",
                12,
                "faint",
            ),
        )
    )
    s.notes = (
        "A check enters from the web app, the extension or another system through one gateway to the API. Jobs and verdict events travel on Redis streams. The worker runs the cascade and the arbiter. "
        "The sandbox browser sits on an isolated network behind a filtering egress proxy and returns features only. The Sentinel consumes the events, and every action lands in an audit log. Metrics, logs and traces feed the dashboards. "
        "The tool list on the right is generated from our lockfiles and compose file by a script, so it lists only what the shipped code uses."
    )
    return s


def slide_roadmap(f: Facts) -> Slide:
    s = Slide("roadmap", "Roadmap: what is not built yet", "خارطة الطريق")
    items: list[str] = []
    if f.fp is not None:
        items.append(
            f"Bring the live false-alarm rate down to the {pct(f.fp['target'])} target by finishing the checks that currently time out."
        )
    items += [r for r in f.roadmap if not r.startswith("Not built yet")]
    items += [r.replace("Not built yet: ", "Build: ") for r in f.roadmap if r.startswith("Not built yet")]
    ne = [humanise(k) for k in (f.artifact.not_evaluated if f.artifact else [])]
    if ne:
        items.append("Measure what is not measured yet: " + ", ".join(ne[:3]) + ".")
    y = 1.8
    row = 0.56
    for text in items[:9]:
        s.add(card(MARGIN, y, 12.1, row), Box(MARGIN + 0.25, y + row / 2 - 0.07, 0.14, 0.14, "sand", None, "oval"))
        s.add(tb(MARGIN + 0.55, y, 11.3, row, p(text, 16, "text"), anchor="m"))
        y += row + 0.06
    s.add(
        tb(
            MARGIN,
            7.0,
            12.1,
            0.3,
            p(
                "Only items that are not finished appear here. Everything on the other slides is in the shipped code.",
                12,
                "faint",
            ),
        )
    )
    s.notes = (
        "This slide lists only what is not finished, stated plainly. The first item is the live false-alarm rate we showed on the results slide: our target is lower, and the work is to finish the checks that time out. "
        "The rest: production use needs a feed licence for the community phishing feed, more reputation feeds when keys are available, sandbox hardening on a Linux host, an iPhone share flow through a Shortcut, "
        "and any real connection to a police system, which would need an agreement. We would rather show you the gaps than have you find them."
    )
    return s


def slide_team(f: Facts) -> Slide:
    s = Slide("team", "Team", "الفريق")
    people = [
        ("Mohamed Atef", "Team leader", "قائد الفريق"),
        ("Abdulrahman Alseiari", "Team member", "عضو الفريق"),
        ("MokhmadSalakh Salamov", "Team member", "عضو الفريق"),
    ]
    w, g = 3.85, 0.275
    for i, (name, role, role_ar) in enumerate(people):
        x = MARGIN + i * (w + g)
        s.add(card(x, 2.2, w, 2.6), Box(x, 2.2, w, 0.09, "brand" if i == 0 else "sand", None, "rect"))
        lens(s, x + 0.35, 2.65, 0.6, "brand" if i == 0 else "sand")
        s.add(
            tb(x + 0.3, 3.4, w - 0.6, 0.85, p(name, 20, "text", True), anchor="t"),
            tb(x + 0.3, 4.2, w - 0.6, 0.45, p(f"{role}  ·  {role_ar}", 16, "muted"), anchor="m"),
        )
    s.add(card(MARGIN, 5.2, 12.1, 1.5, "s1", "faint", dash=True))
    s.add(
        tb(
            MARGIN + 0.3,
            5.2,
            11.5,
            1.5,
            p(
                "Falcon Lens is an independent hackathon project. It is not affiliated with or endorsed by Abu Dhabi Police, uses no police branding, and is not connected to any police system.",
                16,
                "muted",
            ),
            anchor="m",
        )
    )
    s.notes = "Our team: Mohamed Atef, team leader; Abdulrahman Alseiari; and MokhmadSalakh Salamov. We are an independent team. The disclaimer on this slide is deliberate: we are not affiliated with or endorsed by Abu Dhabi Police."
    return s


def slide_thanks(f: Facts) -> Slide:
    s = Slide("thanks", "Thank you", "شكراً لكم")
    s.add(
        tb(MARGIN, 1.95, 12.1, 1.0, p("Check before you tap.", 48, "brand", True), anchor="m"),
        tb(MARGIN, 2.95, 12.1, 0.7, p("افحص قبل أن تضغط", 34, "sand", True, "r"), anchor="m"),
    )
    s.add(
        card(MARGIN, 4.0, 7.2, 2.2),
        tb(
            MARGIN + 0.35,
            4.0,
            6.6,
            2.2,
            Para([Run("Repository", 14, "faint")], after=2),
            Para([Run(f.repo_url, 17, "brand", True)], after=10),
            Para([Run("Demo video and description document", 14, "faint")], after=2),
            p("in the submission form", 18, "text"),
            anchor="m",
        ),
    )
    s.add(
        card(MARGIN + 7.5, 4.0, 4.6, 2.2, "s1", "faint", dash=True),
        tb(
            MARGIN + 7.8,
            4.0,
            4.0,
            2.2,
            p(
                "An independent project. Ready to connect, not connected. Not affiliated with Abu Dhabi Police.",
                16,
                "muted",
            ),
            anchor="m",
        ),
    )
    s.notes = (
        "Close on the line we started with: check before you tap. The code, the architecture and the evaluation method are in the public repository on this slide, and the demo video and the description document are in the submission form. "
        "Thank you. We are happy to take questions, including the hard ones about the numbers."
    )
    return s


def build_slides(f: Facts, img: dict[str, Path]) -> list[Slide]:
    slides = [
        slide_problem(f),
        slide_solution(f, img),
        slide_agents(f),
        slide_how(f),
        slide_sentinel(f, img),
        slide_results(f),
        slide_security(f),
        slide_authorities(f),
        slide_architecture(f, img),
        slide_roadmap(f),
        slide_team(f),
        slide_thanks(f),
    ]
    for i, s in enumerate(slides):
        frame(s, i + 1, len(slides))
    return slides


# ── images ───────────────────────────────────────────────────────────────────
def prepare_images(root: Path, cache: Path) -> dict[str, Path]:
    """PNG assets: the architecture SVG rendered by Chromium, and crops of the design renders."""
    from PIL import Image  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    cache.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    svg = root / "docs" / "assets" / "architecture.svg"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 870}, device_scale_factor=2)
        page.emulate_media(reduced_motion="reduce")
        page.goto(svg.as_uri())
        page.wait_for_timeout(300)
        out["arch"] = cache / "architecture.png"
        page.screenshot(path=str(out["arch"]), clip={"x": 0, "y": 0, "width": 1200, "height": 870})
        browser.close()
    crops = {
        # the result page without the activity timing column and without the reporting-channel card
        # what is on main now; the v2 render is used automatically once web v2 is merged (web/app/agents exists)
        "check": (
            (root / "web/design/v2/shots/check-dangerous-ar-1440.png", (529, 310, 1296, 1160))
            if (root / "web/app/agents").is_dir()
            else (root / "web/design/app-shots/03-check-dangerous-390-ar-night.png", (0, 0, 390, 560))
        ),
        "campaigns": (root / "web/design/app-shots/08-campaigns-live-1440-ar-night.png", (144, 100, 1296, 880)),
    }
    for key, (src, box) in crops.items():
        if not src.is_file():
            raise FileNotFoundError(src)
        target = cache / f"{key}.png"
        with Image.open(src) as im:
            im.convert("RGB").crop(box).save(target, optimize=True)
        out[key] = target
    return out


# ── pptx writer ──────────────────────────────────────────────────────────────
def rgb(name: str) -> RGBColor:
    return RGBColor.from_string(C[name].upper())


def set_font(run: Any, name: str, rtl: bool) -> None:
    r_pr = run._r.get_or_add_rPr()
    r_pr.set("lang", "ar-AE" if rtl else "en-US")
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = r_pr.find(qn(tag))
        if el is None:
            el = r_pr.makeelement(qn(tag), {})
            r_pr.append(el)
        el.set("typeface", name)


def register_notes_master(prs: Any) -> None:
    """List the notes master in presentation.xml.

    python-pptx creates the notes master part and relates it to the presentation, but never writes
    `<p:notesMasterIdLst>`. PowerPoint and Google Slides tolerate that; Keynote rejects the whole file
    ("format is not valid", AppleScript open returns missing value). Found by bisecting with Keynote.
    """
    pres = prs.part._element
    if pres.find(qn("p:notesMasterIdLst")) is not None:
        return
    rids = [rid for rid, rel in prs.part.rels.items() if rel.reltype.endswith("/notesMaster")]
    if not rids:
        return
    lst = pres.makeelement(qn("p:notesMasterIdLst"), {})
    lst.append(lst.makeelement(qn("p:notesMasterId"), {qn("r:id"): rids[0]}))
    pres.find(qn("p:sldMasterIdLst")).addnext(lst)


def write_pptx(slides: list[Slide], out: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    prs.core_properties.title = "Falcon Lens | عدسة الصقر"
    prs.core_properties.author = "Falcon Lens team"
    prs.core_properties.subject = "ScamShield AI submission"
    blank = prs.slide_layouts[6]
    anchors = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}
    aligns = {"l": PP_ALIGN.LEFT, "r": PP_ALIGN.RIGHT, "c": PP_ALIGN.CENTER}
    for sl in slides:
        slide = prs.slides.add_slide(blank)
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb("bg")
        for shape in sl.shapes:
            if isinstance(shape, Box):
                kind = {"rect": MSO_SHAPE.RECTANGLE, "round": MSO_SHAPE.ROUNDED_RECTANGLE, "oval": MSO_SHAPE.OVAL}[
                    shape.shape
                ]
                item = slide.shapes.add_shape(kind, Inches(shape.x), Inches(shape.y), Inches(shape.w), Inches(shape.h))
                if shape.fill:
                    item.fill.solid()
                    item.fill.fore_color.rgb = rgb(shape.fill)
                else:
                    item.fill.background()
                if shape.line:
                    item.line.color.rgb = rgb(shape.line)
                    item.line.width = Pt(shape.line_w)
                    if shape.dash:
                        ln = item.line._get_or_add_ln()
                        dash = ln.makeelement(qn("a:prstDash"), {"val": "dash"})
                        ln.append(dash)
                else:
                    item.line.fill.background()
                item.shadow.inherit = False
                if shape.shape == "round":
                    item.adjustments[0] = min(0.5, shape.radius / min(shape.w, shape.h))
            elif isinstance(shape, Pic):
                pic = slide.shapes.add_picture(
                    str(shape.path), Inches(shape.x), Inches(shape.y), Inches(shape.w), Inches(shape.h)
                )
                pic._element.nvPicPr.cNvPr.set("descr", shape.alt)
            else:
                box = slide.shapes.add_textbox(Inches(shape.x), Inches(shape.y), Inches(shape.w), Inches(shape.h))
                tf = box.text_frame
                tf.word_wrap = True
                tf.vertical_anchor = anchors[shape.anchor]
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                for i, para in enumerate(shape.paras):
                    para_obj = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    text = "".join(r.text for r in para.runs)
                    rtl = is_arabic(text) if para.rtl is None else para.rtl
                    if rtl:
                        para_obj._p.get_or_add_pPr().set("rtl", "1")
                    para_obj.alignment = aligns[para.align]
                    para_obj.line_spacing = Pt(
                        round(max(r.size for r in para.runs) * 1.1, 1)
                    )  # exact, equal to the CSS line-height of the PDF
                    para_obj.space_after = Pt(para.after)
                    for run in para.runs:
                        r = para_obj.add_run()
                        r.text = run.text
                        r.font.size = Pt(run.size)
                        r.font.bold = run.bold
                        r.font.color.rgb = rgb(run.color)
                        set_font(r, PPTX_FONT, rtl)
        slide.notes_slide.notes_text_frame.text = sl.notes
    out.parent.mkdir(parents=True, exist_ok=True)
    register_notes_master(prs)
    prs.save(str(out))


# ── html writer (PDF and QA renders) ─────────────────────────────────────────
def hx(name: str) -> str:
    return "#" + C[name]


def write_html(slides: list[Slide], out: Path, root: Path) -> None:
    faces = "".join(
        f'@font-face{{font-family:"{FONT}";src:url("{(root / rel).as_uri()}") format("woff2");font-weight:100 900;unicode-range:{rng};}}\n'
        for rel, rng in FONT_FILES.values()
    )
    css = (
        faces
        + f"""@page{{size:{W}in {H}in;margin:0}}
*{{box-sizing:border-box}}html,body{{margin:0;background:#000;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.slide{{position:relative;width:{W}in;height:{H}in;background:{hx("bg")};overflow:hidden;page-break-after:always;break-after:page;font-family:"{FONT}",Arial,sans-serif}}
.slide>*{{position:absolute}}
.t{{display:flex;flex-direction:column;overflow:visible}}
.t p{{margin:0;line-height:1.1;white-space:normal;overflow-wrap:break-word}}
"""
    )
    parts = [
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Falcon Lens | عدسة الصقر</title><style>{css}</style></head><body>'
    ]
    for sl in slides:
        parts.append(f'<section class="slide" data-key="{sl.key}">')
        for sh in sl.shapes:
            geo = f"left:{sh.x}in;top:{sh.y}in;width:{sh.w}in;height:{sh.h}in;"
            if isinstance(sh, Box):
                radius = "50%" if sh.shape == "oval" else (f"{sh.radius}in" if sh.shape == "round" else "0")
                border = f"border:{sh.line_w}pt {'dashed' if sh.dash else 'solid'} {hx(sh.line)};" if sh.line else ""
                fill = f"background:{hx(sh.fill)};" if sh.fill else ""
                parts.append(f'<div style="{geo}{fill}{border}border-radius:{radius}"></div>')
            elif isinstance(sh, Pic):
                parts.append(f'<img src="{sh.path.as_uri()}" alt="{html.escape(sh.alt)}" style="{geo}object-fit:fill">')
            else:
                just = {"t": "flex-start", "m": "center", "b": "flex-end"}[sh.anchor]
                inner = []
                for para in sh.paras:
                    text = "".join(r.text for r in para.runs)
                    rtl = is_arabic(text) if para.rtl is None else para.rtl
                    spans = "".join(
                        f'<span style="font-size:{r.size}pt;color:{hx(r.color)};font-weight:{700 if r.bold else 400}">{html.escape(r.text)}</span>'
                        for r in para.runs
                    )
                    align = {"l": "left", "r": "right", "c": "center"}[para.align]
                    inner.append(
                        f'<p dir="{"rtl" if rtl else "ltr"}" style="text-align:{align};margin-bottom:{para.after}pt!important">{spans}</p>'
                    )
                parts.append(f'<div class="t" style="{geo}justify-content:{just}">{"".join(inner)}</div>')
        parts.append("</section>")
    parts.append("</body></html>")
    out.write_text("".join(parts), encoding="utf-8")


def render_pdf_and_qa(html_path: Path, pdf: Path, qa_dir: Path | None) -> list[str]:
    """Print the PDF. With qa_dir, also screenshot every slide and report text that overflows its box."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    problems: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        page.goto(html_path.as_uri())
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(400)
        overflow = page.evaluate(
            """() => [...document.querySelectorAll('.slide')].flatMap((s, i) =>
              [...s.querySelectorAll('.t')].filter(t => t.scrollHeight > t.clientHeight + 2 || [...t.children].some(c => c.scrollWidth > c.clientWidth + 2))
                .map(t => `slide ${i + 1}: text overflows its box: ${t.innerText.slice(0, 60).replace(/\\n/g, ' / ')}`))"""
        )
        problems += overflow
        fonts_ok = page.evaluate("document.fonts.check('16px \"Readex Pro\"')")
        if not fonts_ok:
            problems.append("Readex Pro did not load in Chromium")
        page.pdf(path=str(pdf), width=f"{W}in", height=f"{H}in", print_background=True, prefer_css_page_size=True)
        if qa_dir:
            qa_dir.mkdir(parents=True, exist_ok=True)
            for i, handle in enumerate(page.query_selector_all(".slide")):
                handle.screenshot(path=str(qa_dir / f"slide-{i + 1:02d}.png"))
        browser.close()
    return problems


# ── checks ───────────────────────────────────────────────────────────────────
def check_text(pptx: Path, art: artifact_mod.Artifact | None, published: Path) -> list[str]:
    """Wording rules and number tracing over every slide and every speaker note."""
    text = check_numbers.pptx_text(pptx)
    problems = [f"wording: {e}" for e in descriptions.wording_errors(text)]
    traceable = check_numbers.traceable_for(art, published)
    problems += [
        f"untraceable number: {finding}" for finding in check_numbers.find_untraceable(text, traceable, pptx.name)
    ]
    return problems


def verify_pptx(pptx: Path, expected: int) -> list[str]:
    """Re-open with python-pptx; no macros, no SmartArt, only PNG images, every slide has notes."""
    import zipfile  # noqa: PLC0415

    problems = []
    prs = Presentation(str(pptx))
    if len(prs.slides) != expected:
        problems.append(f"expected {expected} slides, found {len(prs.slides)}")
    for i, slide in enumerate(prs.slides, 1):
        if not slide.has_notes_slide or not slide.notes_slide.notes_text_frame.text.strip():
            problems.append(f"slide {i} has no speaker notes")
    with zipfile.ZipFile(pptx) as zf:
        for name in zf.namelist():
            low = name.lower()
            if "vbaproject" in low or low.startswith("ppt/diagrams/"):
                problems.append(f"forbidden part: {name}")
            if low.startswith("ppt/media/") and not low.endswith(".png"):
                problems.append(f"non-PNG image: {name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--qa-dir", type=Path, default=None, help="also write one PNG per slide here and report overflow")
    ap.add_argument("--repo-url", default=None)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "submission", help="where the .pptx and .pdf are written")
    args = ap.parse_args(argv)
    root = args.root.resolve()

    facts = gather(root)
    if args.repo_url:
        facts.repo_url = args.repo_url
    out_pptx, out_pdf = args.out_dir / OUT_PPTX.name, args.out_dir / OUT_PDF.name
    images = prepare_images(root, CACHE)
    slides = build_slides(facts, images)
    write_pptx(slides, out_pptx)
    html_path = CACHE / "deck.html"
    write_html(slides, html_path, root)
    problems = render_pdf_and_qa(html_path, out_pdf, args.qa_dir)
    problems += verify_pptx(out_pptx, len(slides))
    problems += check_text(out_pptx, facts.artifact, root / "evals" / "results" / "published")
    for path in (out_pptx, out_pdf):
        size = path.stat().st_size
        print(f"{path}: {size / 1024:.0f} KB")
        if size > MAX_BYTES:
            problems.append(f"{path.name} is over 20 MB")
    print(f"slides: {len(slides)}")
    for item in problems:
        print(f"ERROR: {item}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
