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

from lxml import etree  # noqa: E402
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
from submission import evidence as evidence_mod  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deck_motion  # noqa: E402
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
    "warn_solid": "f4b23a",
    "border_strong": "5a6c92",
    "nws_solid": "3a5bd0",
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
    autonum: int | None = None  # a list marker (1., 2., ...) starting at this value; the digit is not text


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
    shape: str = "rect"  # rect | round | oval | tri_up | tri_right | tri_down | octagon
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


@dataclass
class Movie:
    """A video with its poster frame. Only the deliverables build carries one; the repo build stays PNG-only."""

    path: Path
    poster: Path
    x: float
    y: float
    w: float
    h: float
    ms: int = 0  # length, for the play command
    auto: bool = False  # start when the slide opens instead of on a click


@dataclass
class Group:
    name: str
    shapes: list[Any]


Shape = TextBox | Box | Pic | Movie | Group

# Set by main() from --hook-video: (video, poster PNG, length in ms, start automatically).
HOOK_MEDIA: tuple[Path, Path, int, bool] | None = None


@dataclass
class Mo:
    """One entrance step: the named top-level group, the effect, and how it is triggered (see deck_motion.py)."""

    target: str
    effect: str = "fade"
    trigger: str = "after"  # auto | click | after | with
    delay: int = 0
    dur: int = 400


@dataclass
class Slide:
    key: str
    title_en: str
    title_ar: str
    shapes: list[Shape] = field(default_factory=list)
    notes: str = ""
    chrome: str = "full"  # full (frame and section tracker) | frame | none
    section: int | None = None  # index into SECTIONS for the tracker
    motion: list[Mo] = field(default_factory=list)
    transition: tuple[str, int] | None = None  # (kind, milliseconds) into this slide
    title_size: tuple[float, float] = (34, 30)
    title_w: tuple[float, float] = (7.9, 4.4)

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
    ev: Any = None  # scripts/submission/evidence.Evidence: the other published families

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
    return Facts(art, fp, caps, url, project_card.shipped_tools(root), roadmap, evidence_mod.load(published))


# ── drawing helpers: groups, chips, icons ────────────────────────────────────
def grp(name: str, *shapes: Shape) -> Group:
    return Group(name, list(shapes))


def mo(target: str, effect: str = "fade", trigger: str = "after", delay: int = 0, dur: int = 400) -> Mo:
    # Stretched so that every build is plainly visible on a projector (the first cut read as "no animation").
    return Mo(target, effect, trigger, delay, min(deck_motion.MAX_EFFECT_MS, max(500, round(dur * 1.6))))


def chip_shapes(
    x: float,
    y: float,
    w: float,
    text: str,
    fg: str = "text",
    fill: str = "s2",
    line: str = "border_strong",
    size: float = 14,
    h: float = 0.38,
    dash: bool = False,
) -> list[Shape]:
    box = Box(x, y, w, h, fill, line, "round", h / 2, 1.0, dash)
    return [box, tb(x, y, w, h, p(text, size, fg, True, "c"), anchor="m")]


def chip_w(text: str, size: float = 14) -> float:
    return len(text) * size * 0.0087 + 0.5


def lens_shapes(x: float, y: float, size: float, color: str = "brand") -> list[Shape]:
    inner = size * 0.36
    return [
        Box(x, y, size, size, None, color, "oval", line_w=2.25),
        Box(x + (size - inner) / 2, y + (size - inner) / 2, inner, inner, color, None, "oval"),
    ]


def radar_shapes(x: float, y: float, size: float, color: str = "sand") -> list[Shape]:
    mid, ring, dot = size * 0.5, size * 0.5, size * 0.13
    return [
        Box(x, y, size, size, None, color, "oval", line_w=2.25),
        Box(x + (size - ring) / 2, y + (size - ring) / 2, ring, ring, None, color, "oval", line_w=1.25),
        Box(x + mid - dot / 2, y + mid - dot / 2, dot, dot, color, None, "oval"),
        Box(x + size * 0.68, y + size * 0.2, dot, dot, color, None, "oval"),
    ]


def mic_shapes(x: float, y: float, color: str = "brand") -> list[Shape]:
    """Microphone glyph, about 0.3 x 0.5 in: capsule, stand, base."""
    return [
        Box(x + 0.08, y, 0.16, 0.3, None, color, "round", 0.08, 2.0),
        Box(x, y + 0.14, 0.32, 0.22, None, color, "oval", line_w=1.5),
        Box(x + 0.15, y + 0.36, 0.02, 0.08, color, None, "rect"),
        Box(x + 0.07, y + 0.44, 0.18, 0.025, color, None, "rect"),
    ]


def hairline(x: float, y: float, w: float, color: str = "border") -> Box:
    return Box(x, y, w, 0.012, color, None, "rect")


def plate_shapes(x: float, y: float, w: float, en: str, ar: str, tone: str, glyph: str, h: float = 0.82) -> list[Shape]:
    """A verdict plate: colour, shape and word together (the shapes of the product's verdict marks)."""
    fg, fill, line = {
        "danger": ("danger", "danger_tint", "danger_line"),
        "warn": ("warn", "warn_tint", "warn_line"),
        "nws": ("nws", "nws_tint", "nws_line"),
    }[tone]
    g = 0.3
    return [
        Box(x, y, w, h, fill, line, "round", 0.14),
        Box(x + 0.22, y + (h - g) / 2, g, g, fg, None, glyph),
        tb(x + 0.7, y + 0.06, w - 0.85, 0.4, p(en, 17, fg, True), anchor="m"),
        tb(x + 0.7, y + 0.44, w - 0.85, 0.32, p(ar, 16, fg, True, "l"), anchor="m"),
    ]


def hero_run(text: str, size: float = 96, color: str = "brand") -> Run:
    return Run(text, size, color, True)


# ── frame, section tracker ───────────────────────────────────────────────────
SECTIONS: tuple[tuple[str, str], ...] = (
    ("Hook", "المشهد"),
    ("Problem", "المشكلة"),
    ("Solution", "الحل"),
    ("Live demo", "العرض المباشر"),
    ("Criteria", "المعايير"),
    ("Pilot path", "مسار التجربة"),
    ("Team", "الفريق"),
)
TAG_AR = "اسأل الصقر قبل لا تضغط"
TAG_EN = "Ask the falcon before you tap."
INDEPENDENT = "An independent project. Ready to connect, not connected."
NOT_AFFILIATED = "An independent project. Ready to connect, not connected. Not affiliated with Abu Dhabi Police."


def frame(slide: Slide, number: int = 0, total: int = 0, tracker_at: int | None = None) -> None:
    """Background chrome: top rule, lens mark, wordmark, independence line, bilingual title, section tracker."""
    en_w, ar_w = slide.title_w
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
        tb(MARGIN, 0.9, en_w, 0.75, p(slide.title_en, slide.title_size[0], "text", True), anchor="m"),
        tb(W - MARGIN - ar_w, 0.9, ar_w, 0.75, p(slide.title_ar, slide.title_size[1], "sand", True, "r"), anchor="m"),
    )
    if tracker_at is not None:
        tracker(slide, tracker_at)


def tracker(slide: Slide, active: int) -> None:
    """Seven segments across the content width: past strong, active brand and taller, coming faint. No numerals."""
    seg, gap, y = 1.665, 0.08, 7.02
    for i, (en, ar) in enumerate(SECTIONS):
        x = MARGIN + i * (seg + gap)
        if i == active:
            slide.add(Box(x, y - 0.02, seg, 0.09, "brand", None, "round", 0.04))
            label_w = min(3.3, W - MARGIN - x)
            slide.add(tb(x, 6.74, label_w, 0.24, p(f"{en} · {ar}", 12, "faint"), anchor="b"))
        else:
            slide.add(Box(x, y, seg, 0.05, "border_strong" if i < active else "border", None, "round", 0.025))


# ── facts: values read from the published families ───────────────────────────
def na(f: Facts) -> bool:
    return f.ev is None


def kn(k: Any, n: Any) -> list[Run]:
    return [hero_run(str(k)), hero_run(f" of {n}", 36, "text")]


def st(f: Facts, cap: str, text: str) -> str:
    return status(f, cap, text)


def brand_new_group(f: Facts, group: str) -> dict[str, Any] | None:
    if not (f.ev and f.ev.brand_new):
        return None
    return f.ev.brand_new["groups"][group]  # type: ignore[no-any-return]


def faith_ratio(f: Facts) -> tuple[int, int] | None:
    if not (f.ev and f.ev.faith):
        return None
    v = f.ev.faith["user_facing_reasons_template_only"]["cascade_fixture_verdicts_synthetic"]["all_cascade_verdicts"]
    return int(v["reasons_faithful"]["k"]), int(v["reasons_faithful"]["n"])


def voice_targets(f: Facts) -> dict[str, Any] | None:
    if not (f.ev and f.ev.voice):
        return None
    return f.ev.voice["targets"]["local"]  # type: ignore[no-any-return]


def sovereign_runs(f: Facts) -> list[tuple[str, int, int, int, bool]]:
    """(model label, scenarios passed, scenarios run, cloud calls, run passed) for the newest run per local model."""
    rows = []
    for run in f.ev.sovereign if f.ev else []:
        counts = run["scenario_counts"]
        model = str(run["local_model"])
        label = "Qwen" if "qwen" in model.lower() else "Inkling" if "inkling" in model.lower() else model
        rows.append(
            (
                label,
                int(counts["PASS"]),
                sum(int(v) for v in counts.values()),
                int(run["egress_audit"]["anthropic_sink_hits"]),
                run.get("status") == "passed",
            )
        )
    return rows


# ── slides ───────────────────────────────────────────────────────────────────
# The spoken lines of slides 3, 5, 7 and 14 are the run-sheet's, word for word (submission/build/demo_template.md).
HOOK_FAIL_AR = "أبو سعيد، خمسة وستون عاماً، وصلته رسالة تقول إن حسابه سيُجمَّد، وقد خسر مالاً من قبل."
HOOK_FAIL_EN = "Abu Saeed is sixty-five. One more text says his account will be frozen. He has already lost money."
PROBLEM_EN = "A blocklist lists a scam page only after somebody reports it, so a page that is new today is on no list today, and the warning is rarely in the language people read."
PROBLEM_AR = "القائمة السوداء لا تُدرج الصفحة إلا بعد أن يبلّغ عنها أحد، فالصفحة الجديدة اليوم ليست في أي قائمة."
SOLUTION_EN = "Falcon Lens is two AI agents. Baseer, the Investigator, judges one message, link or email, and fixed code, not the AI, sets the score. Dir', the Sentinel, watches around the clock, links checks into campaigns and drafts takedowns that wait for a human. You simply talk to it: Hey Falcon."
SOLUTION_AR = "«عدسة الصقر» وكيلان بالذكاء الاصطناعي: «بصير» يحكم على رسالة أو رابط أو بريد واحد، والدرجة يحدّدها كود ثابت لا نموذج لغوي. و«درع» يراقب على مدار الساعة ويربط الفحوص في حملات ويُعدّ مسودات الإزالة بانتظار موافقة إنسان. وتخاطبه بصوتك: «يا صقر»."
SOVEREIGN_EN = "And it runs sovereign, on local models, on this machine."
SOVEREIGN_AR = "ويعمل محلياً بالكامل على هذا الجهاز."
DEMO_EN = "This is live, on our machine."
DEMO_AR = "هذا عرض مباشر على جهازنا."
CLOSE_EN = "Detection with a fixed arbiter and honest numbers. Look-alikes that are on no list. Reasons, a trace and an evidence pack a police analyst can use. Arabic voice and UAE brands. Live, sovereign, and a pilot path: the same stack inside your network, in shadow mode first. Ready to connect, not connected. Ask the falcon before you tap."
CLOSE_AR = "كشف بحكَم ثابت وأرقام صادقة، ومواقع منتحلة لم تُدرج في أي قائمة، وأسباب وأثر وحزمة أدلة يستعملها المحلل، وصوت عربي وعلامات إماراتية. نظام حي وسيادي، ومسار تجريبي: المنظومة نفسها داخل شبكتكم في وضع المراقبة أولاً. جاهز للربط وغير مربوط. اسأل الصقر قبل لا تضغط."


def notes(say_en: str, say_ar: str, do: str, fail: str = "", qa: str = "") -> str:
    """Speaker notes in the order of DECK_DESIGN.md section 4."""
    parts = [f"SAY (EN): {say_en}", f"SAY (AR): {say_ar}", f"DO: {do}"]
    if fail:
        parts.append(f"IF IT FAILS: {fail}")
    if qa:
        parts.append(f"Q&A: {qa}")
    return "\n".join(parts)


def slide_title(f: Facts) -> Slide:
    s = Slide("title", "ScamShield AI entry", "مسابقة ScamShield", chrome="none")
    logo = ROOT / "web" / "public" / "icons" / "icon-512.png"
    s.add(
        grp(
            "logo",
            Pic(logo, 0.9, 1.45, 1.9, 1.9, "The Falcon Lens mark"),
        ),
        grp(
            "wordmark",
            tb(
                3.2,
                1.4,
                9.5,
                1.05,
                Para([Run("عدسة الصقر | Falcon Lens", 52, "brand", True)], "l", rtl=True),
                anchor="m",
            ),
        ),
        grp("tag_ar", tb(3.2, 2.55, 9.5, 0.7, Para([Run(TAG_AR, 36, "sand", True)], "l", rtl=True), anchor="m")),
        grp("tag_en", tb(3.2, 3.25, 9.5, 0.5, p(TAG_EN, 26, "text"), anchor="m")),
        grp(
            "event", tb(0.9, 4.0, 11.6, 0.5, p("ScamShield AI Hackathon · 26 Nov 2026", 22, "muted", True), anchor="m")
        ),
        grp(
            "team",
            tb(0.9, 4.75, 11.6, 0.4, Para([Run("Team · الفريق", 16, "brand", True)]), anchor="m"),
            tb(0.9, 5.15, 4.5, 0.5, p("Mohamed Atef (Team Leader)", 18, "text", True), anchor="m"),
            tb(5.55, 5.15, 3.4, 0.5, p("Abdulrahman Alseiari", 18, "text", True), anchor="m"),
            tb(9.1, 5.15, 3.6, 0.5, p("MokhmadSalakh Salamov", 18, "text", True), anchor="m"),
        ),
        grp(
            "indep",
            *chip_shapes(
                0.9,
                6.2,
                6.9,
                "Independent project · ready to connect, not connected",
                "nws",
                "nws_tint",
                "nws_line",
                15,
                0.42,
            ),
        ),
    )
    s.motion = [
        mo("logo", "zoom", "auto", 200, 600),
        mo("wordmark", "fly_from_right", "after", 0, 500),
        mo("tag_ar", "wipe_from_right", "after", 0, 500),
        mo("tag_en", "fade", "with", 150, 400),
        mo("event", "fly_from_bottom", "after", 0, 400),
        mo("team", "fly_from_bottom", "after", 100, 500),
        mo("indep", "fade", "after", 100, 300),
    ]
    s.transition = ("fade", 600)
    s.notes = notes(
        "Good afternoon. We are Falcon Lens: two AI agents. You will watch a real check run on our own machine, in Arabic, by voice. We are an independent project: ready to connect, not connected.",
        "نحن فريق «عدسة الصقر». سترون فحصاً حقيقياً على جهازنا، بالعربية وبالصوت. مشروع مستقل: جاهز للربط وغير مربوط.",
        "Holding slide. Everything builds by itself; click when invited to start.",
    )
    return s


def slide_agenda(f: Facts) -> Slide:
    s = Slide("agenda", "Agenda", "جدول العرض", chrome="frame")
    rows = [
        ("Hook video", "مشهد افتتاحي"),
        ("The problem", "المشكلة"),
        ("Our solution: Baseer, Dir' and «يا صقر»", "الحل: بصير ودرع و«يا صقر»"),
        ("Architecture", "المعمارية"),
        ("Live demo", "العرض المباشر"),
        ("How we meet the five criteria", "كيف نستوفي المعايير الخمسة"),
        ("Pilot path and limits", "مسار التجربة والحدود"),
        ("Questions", "الأسئلة"),
    ]
    y0, rh, gap = 1.85, 0.54, 0.1
    for i, (en, ar) in enumerate(rows):
        y = y0 + i * (rh + gap)
        s.add(
            grp(
                f"row_{i}",
                Box(MARGIN, y, 12.13, rh, "s1", "border", "round", 0.1),
                Box(MARGIN, y, 0.06, rh, "brand"),
                tb(MARGIN + 0.35, y, 7.2, rh, Para([Run(en, 20, "text", True)], autonum=i + 1), anchor="m"),
                tb(W - MARGIN - 0.35 - 4.2, y, 4.2, rh, Para([Run(ar, 20, "sand", True)], "r"), anchor="m"),
            )
        )
    s.motion = [mo(f"row_{i}", "fly_from_left", "click", 0, 350) for i in range(len(rows))]
    s.transition = ("push_left", 700)
    s.notes = notes(
        "Our path: a short scene, the problem, our solution, the architecture, a live demo, how we meet your five criteria, the pilot path and limits, and then your questions.",
        "مسار العرض: مشهد قصير، ثم المشكلة والحل، ثم المعمارية، ثم عرض مباشر، ثم كيف نستوفي معاييركم الخمسة، ومسار التجربة وحدودنا، ثم أسئلتكم.",
        "Each item appears on a click, one per spoken beat. Click once more to go to the hook; the clock starts there.",
    )
    return s


def slide_hook_video(media: tuple[Path, Path, int, bool]) -> Slide:
    """The hook slide of the deliverables deck: the portrait video at full slide height, the label beside it."""
    video, poster, ms, auto = media
    s = Slide("hook", "Hook", "المشهد", chrome="none")
    vw = H * 9 / 16  # portrait 9:16 at full height
    vx = (W - vw) / 2
    s.add(Movie(video, poster, vx, 0, vw, H, ms, auto))
    s.add(*chip_shapes(0.6, 0.6, 3.5, "تمثيل — Dramatisation", "warn", "warn_tint", "warn_line", 16, 0.46))
    s.add(
        tb(
            0.6,
            1.25,
            3.6,
            1.3,
            p("Invented bank: Falcon Demo Bank. Fictional people. No police logo, uniform or vehicle.", 15, "faint"),
        ),
        Pic(ROOT / "web" / "public" / "icons" / "icon-512.png", W - 1.6, H - 1.6, 1.0, 1.0, "The Falcon Lens mark"),
        tb(W - 4.3, H - 0.62, 3.9, 0.3, Para([Run("عدسة الصقر | Falcon Lens", 13, "faint", True)], "r", rtl=True)),
    )
    s.transition = ("fade", 400)
    start = "The video starts by itself when the slide opens." if auto else "Click once to start the video."
    s.notes = notes(
        "Nothing over the video. Then pause one second.",
        "Nothing over the video.",
        f"{start} It plays with sound and does not loop. Click again to go on. Production facts: invented bank, fictional people, no police logo, uniform or vehicle.",
        f"Say, in Arabic then English: «{HOOK_FAIL_AR}» {HOOK_FAIL_EN} Then click on.",
    )
    return s


def slide_hook(f: Facts) -> Slide:
    if HOOK_MEDIA:
        return slide_hook_video(HOOK_MEDIA)
    s = Slide("hook", "Hook", "المشهد", chrome="none")
    s.add(
        Box(0.35, 0.35, W - 0.7, H - 0.7, None, "border_strong", "rect", line_w=1.5),
        Box(W / 2 - 0.55, 2.55, 1.1, 1.1, None, "brand", "oval", line_w=3),
        Box(W / 2 - 0.16, 2.88, 0.38, 0.44, "brand", None, "tri_right"),
        tb(W / 2 - 3, 3.85, 6, 0.5, p("Hook video · مشهد افتتاحي", 18, "muted", align="c"), anchor="m"),
        tb(
            0.9,
            6.7,
            W - 1.8,
            0.4,
            p(
                "Invented bank: Falcon Demo Bank. Fictional people. No police logo, uniform or vehicle.",
                15,
                "faint",
                align="c",
            ),
            anchor="m",
        ),
    )
    s.add(*chip_shapes(0.6, 0.6, 3.7, "تمثيل — Dramatisation", "warn", "warn_tint", "warn_line", 16, 0.46))
    s.transition = ("fade", 400)
    s.notes = notes(
        "Nothing over the video. Then pause one second.",
        "Nothing over the video.",
        "The video starts by itself. Owner step on the presenting machine only: insert the video cut made from demo-kit/hook-video/PROMPT.md, size it to the full slide, set it to start automatically, then select the chip and choose Bring to Front so the label stays over the video from the first frame. The submitted file carries no video. Production facts: invented bank, fictional people, no police logo, uniform or vehicle.",
        f"Say, in Arabic then English: «{HOOK_FAIL_AR}» {HOOK_FAIL_EN} Then click on.",
    )
    return s


def slide_problem(f: Facts) -> Slide:
    s = Slide("problem", "The problem", "المشكلة")
    px, py = 0.9, 1.85
    s.add(
        grp(
            "phone",
            Box(px, py, 2.6, 4.75, "s1", "border_strong", "round", 0.3, 2.5),
            Box(px + 0.95, py + 0.18, 0.7, 0.07, "border_strong", None, "round", 0.035),
            tb(px + 0.2, py + 4.0, 2.2, 0.5, p("TEST FIXTURE", 12, "faint", True, "c"), anchor="m"),
        ),
        grp(
            "sms",
            Box(px + 0.25, py + 1.2, 2.1, 1.3, "s2", "border", "round", 0.2),
            tb(px + 0.35, py + 1.2, 1.9, 1.3, Para([Run("حسابك سيُجمَّد", 22, "sand", True)], "c"), anchor="m"),
        ),
        grp(
            "story_ar",
            tb(
                4.3,
                1.85,
                8.4,
                2.15,
                Para(
                    [
                        Run(
                            "رسالة واحدة: «حسابك سيُجمَّد». والصفحة المزيّفة وُلدت اليوم، فليست في أي قائمة.",
                            40,
                            "sand",
                            True,
                        )
                    ],
                    "r",
                ),
                anchor="m",
            ),
        ),
        grp(
            "story_en",
            tb(
                4.3,
                4.1,
                8.4,
                1.45,
                p(
                    "One text: 'your account will be frozen'. The fake page was born today, so it is on no list.",
                    30,
                    "text",
                ),
                anchor="m",
            ),
        ),
        grp(
            "blocklist",
            tb(
                4.3,
                5.7,
                8.4,
                0.95,
                p("A blocklist lists a page only after someone reports it.", 17, "muted", after=2),
                Para([Run("القائمة السوداء لا تُدرج الصفحة إلا بعد أن يبلّغ عنها أحد.", 17, "muted")], "r"),
                anchor="m",
            ),
        ),
    )
    s.motion = [
        mo("phone", "fly_from_left", "auto", 150, 400),
        mo("sms", "zoom", "after", 200, 400),
        mo("story_ar", "wipe_from_right", "after", 100, 600),
        mo("story_en", "fade", "after", 0, 500),
        mo("blocklist", "fly_from_bottom", "after", 300, 400),
    ]
    s.transition = ("push_left", 700)
    s.section = 1
    s.notes = notes(
        PROBLEM_EN,
        PROBLEM_AR,
        "Builds by itself. One click to the solution. The slide quotes no statistic on purpose: a figure appears in this project only with a public source link.",
    )
    return s


def slide_solution(f: Facts) -> Slide:
    s = Slide("solution", "Two agents and the voice", "وكيلان والصوت")
    pill_w = 4.4
    s.add(
        grp(
            "voice",
            Box((W - pill_w) / 2, 1.8, pill_w, 0.72, "s1", "brand", "round", 0.36, 2.0),
            *mic_shapes((W - pill_w) / 2 + 0.4, 1.95, "brand"),
            tb(
                (W - pill_w) / 2 + 0.9,
                1.8,
                pill_w - 1.1,
                0.72,
                Para([Run("«يا صقر»", 22, "brand", True), Run("   Hey Falcon", 20, "text", True)]),
                anchor="m",
            ),
        )
    )
    cw = 5.95
    cards = [
        (
            "baseer",
            MARGIN,
            "brand",
            "بصير",
            "Baseer, the Investigator",
            "Judges one message, link or email.",
            "يحكم على رسالة أو رابط أو بريد واحد.",
            lens_shapes,
        ),
        (
            "dir",
            MARGIN + cw + 0.23,
            "sand",
            "درع",
            "Dir', the Sentinel",
            "Watches around the clock and links checks into campaigns.",
            "يراقب على مدار الساعة ويربط الفحوص في حملات.",
            radar_shapes,
        ),
    ]
    for name, x, accent, ar, en, line_en, line_ar, icon in cards:
        s.add(
            grp(
                name,
                card(x, 2.75, cw, 2.4),
                Box(x, 2.75, cw, 0.08, accent, None, "rect"),
                *icon(x + 0.35, 3.1, 0.8, accent),
                tb(x + 1.45, 3.0, cw - 1.7, 0.75, Para([Run(ar, 40, "text", True)]), anchor="m"),
                tb(x + 1.45, 3.75, cw - 1.7, 0.4, p(en, 20, accent, True), anchor="m"),
                tb(
                    x + 0.35,
                    4.2,
                    cw - 0.7,
                    0.85,
                    p(line_en, 16, "muted", after=2),
                    Para([Run(line_ar, 16, "muted")], "r"),
                ),
            )
        )
    s.add(
        grp(
            "rule",
            tb(
                MARGIN,
                5.28,
                12.13,
                0.42,
                p("Fixed code sets the score, not the AI. Outside actions wait for a human.", 18, "sand", True, "c"),
                anchor="m",
            ),
        )
    )
    pw = (12.13 - 0.4) / 3
    plates = [
        ("plate_d", "Dangerous", "خطِر", "danger", "octagon"),
        ("plate_s", "Suspicious", "مريب", "warn", "tri_up"),
        ("plate_n", "No warning signs found", "لم نجد علامات تحذير", "nws", "oval"),
    ]
    for i, (name, en, ar, tone, glyph) in enumerate(plates):
        s.add(grp(name, *plate_shapes(MARGIN + i * (pw + 0.2), 5.8, pw, en, ar, tone, glyph)))
    s.motion = [
        mo("voice", "zoom", "auto", 150, 450),
        mo("baseer", "fly_from_left", "after", 0, 500),
        mo("dir", "fly_from_right", "with", 150, 500),
        mo("rule", "fade", "click", 0, 400),
        mo("plate_d", "zoom", "after", 80, 300),
        mo("plate_s", "zoom", "after", 80, 300),
        mo("plate_n", "zoom", "after", 80, 300),
    ]
    s.transition = ("push_left", 700)
    s.section = 2
    s.notes = notes(
        SOLUTION_EN,
        SOLUTION_AR,
        "Click once at 'fixed code, not the AI, sets the score' to bring in the verdict plates.",
    )
    return s


def slide_architecture(f: Facts) -> Slide:
    s = Slide(
        "architecture",
        "Architecture in three layers",
        "المعمارية في ثلاث طبقات",
        title_size=(30, 26),
        title_w=(6.9, 5.2),
    )
    x0 = MARGIN + 0.55  # the start-side gutter carries the flow beam
    bw = W - MARGIN - x0
    head_w = 2.25
    cx = x0 + head_w + 0.15
    cw = W - MARGIN - cx - 0.15
    size, ch, cgap = 13, 0.33, 0.08

    def layout(items: Sequence[str], x: float, y: float, w: float) -> tuple[list[Shape], float]:
        shapes: list[Shape] = []
        cur, row = x, 0
        for text in items:
            tw = chip_w(text, size)
            if cur + tw > x + w and cur > x:
                cur, row = x, row + 1
            shapes += chip_shapes(cur, y + row * (ch + cgap), tw, text, "text", "s2", "border_strong", size, ch)
            cur += tw + cgap
        return shapes, (row + 1) * ch + row * cgap

    def band(
        name: str, y: float, title: str, title_ar: str, rows: Sequence[tuple[str, Sequence[str]]]
    ) -> tuple[Group, float]:
        inner: list[Shape] = []
        cy = y + 0.14
        for label, items in rows:
            lw = 0.0
            if label:
                lw = 1.15
                inner.append(tb(cx + 0.15, cy, lw, ch, p(label, 15, "sand", True), anchor="m"))
            shapes, h = layout(items, cx + 0.15 + lw, cy, cw - lw - 0.3)
            inner += shapes
            cy += h + 0.1
        height = cy - y - 0.1 + 0.14
        box = [
            card(x0, y, bw, height),
            Box(x0, y, 0.07, height, "brand", None, "rect"),
            tb(
                x0 + 0.25,
                y + 0.12,
                head_w - 0.2,
                height - 0.24,
                Para([Run(title, 13, "brand", True)], after=3),
                Para([Run(title_ar, 14, "sand", True)], "l", rtl=True),
                anchor="m",
            ),
        ]
        return grp(name, *box, *inner), height

    y = 1.75
    voice, hv = band(
        "band_voice",
        y,
        "VOICE",
        "طبقة المساعد الصوتي",
        [("", ["mic · speech to text, local", "wake phrase «يا صقر»", "intent", "action", "narration"])],
    )
    y_agents = y + hv + 0.1
    agents, ha = band(
        "band_agents",
        y_agents,
        "TWO AGENTS",
        "طبقة الوكيلين الذكيين",
        [
            ("Baseer", ["T0", "T1", "T2", "T3", "deterministic arbiter"]),
            ("Dir'", ["listens", "correlates", "rules decide", "LangGraph triage", "human approval"]),
        ],
    )
    y_plat = y_agents + ha + 0.1
    platform, hp = band(
        "band_platform",
        y_plat,
        "PLATFORM",
        "طبقة المنصة",
        [
            (
                "",
                [
                    "REST and SSE API",
                    "event bus",
                    "Postgres with pgvector",
                    "isolated sandbox and egress proxy",
                    "MCP, STIX, webhooks · ready to connect, not connected",
                    "observability",
                ],
            )
        ],
    )
    s.add(voice, agents, platform)
    bx = MARGIN + 0.2
    top, bottom = y + hv / 2, y_plat + hp / 2
    s.add(
        grp(
            "beam",
            Box(bx - 0.015, top, 0.03, bottom - top - 0.1, "brand"),
            Box(bx - 0.1, bottom - 0.14, 0.2, 0.16, "brand", None, "tri_down"),
        )
    )
    for name, cy_ in (("dot_voice", top), ("dot_agents", y_agents + ha / 2), ("dot_platform", bottom - 0.04)):
        s.add(grp(name, Box(bx - 0.09, cy_ - 0.09, 0.18, 0.18, "brand", "bg", "oval", line_w=2)))
    cap_y = y_plat + hp + 0.1
    s.add(
        grp(
            "caption",
            tb(
                x0,
                cap_y,
                bw,
                0.32,
                Para(
                    [
                        Run(
                            "A request flows down: the voice layer calls the same public check API.", 15, "brand", True
                        ),
                        Run("   الطلب ينزل من الأعلى إلى الأسفل.", 15, "sand", True),
                    ]
                ),
                anchor="m",
            ),
        ),
        tb(
            x0,
            cap_y + 0.34,
            bw,
            0.26,
            p("Model route chosen by an operator: cloud with local fallback, or local only.", 13, "faint"),
            anchor="m",
        ),
    )
    s.motion = [
        mo("band_voice", "wipe_from_top", "auto", 150, 600),
        mo("band_agents", "wipe_from_top", "after", 250, 600),
        mo("band_platform", "wipe_from_top", "after", 250, 600),
        mo("beam", "wipe_from_top", "click", 0, 900),
        mo("dot_voice", "fade", "with", 0, 250),
        mo("dot_agents", "fade", "with", 350, 250),
        mo("dot_platform", "fade", "with", 700, 250),
        mo("caption", "fade", "after", 0, 400),
    ]
    s.transition = ("push_left", 700)
    s.section = 2
    s.notes = notes(
        "Three layers. Your voice on top, the two agents in the middle, the platform underneath. A request flows down, and it can all run sovereign, on local models, on this machine.",
        "ثلاث طبقات: صوتك في الأعلى، والوكيلان في الوسط، والمنصة في الأسفل. الطلب ينزل من الأعلى إلى الأسفل، وكل ذلك يعمل محلياً على هذا الجهاز.",
        "Layers build by itself. Click once at 'a request flows down'.",
        "If time is short, skip this slide and say the last sentence over the solution slide.",
    )
    return s


def slide_demo(f: Facts) -> Slide:
    s = Slide("demo", "Live demo", "العرض المباشر")
    stops = [
        (
            "0:55 to 1:00",
            "Switch to the browser",
            "Home page in Arabic, with the voice control. This is live, on our machine.",
        ),
        (
            "1:00 to 1:35",
            "Arabic voice check",
            "«يا صقر، شيّك اللي نسخته»: live steps, then «خطِر».  "
            + st(f, "voice_findings", "The falcon speaks the real findings."),
        ),
        (
            "1:35 to 1:55",
            "English question",
            '"Hey Falcon, someone called saying he\'s from the bank." A short, sourced answer.',
        ),
        (
            "1:55 to 2:10",
            "Trace in /history",
            "Every step, signal and the arbiter's rule. " + st(f, "evidence_pack", "Then the evidence pack download."),
        ),
        (
            "2:10 to 2:25",
            "Campaigns and results",
            "/campaigns links checks into one campaign. /results shows the numbers with their limits.",
        ),
        (
            "2:25 to 2:40",
            "Route selector in /ops",
            "Cloud model with local fallback, or local only. "
            + st(f, "hunter", "Hunting: built, off by default, switched on per deployment."),
        ),
    ]
    pitch, sw = 2.0, 1.9
    s.add(grp("rail", Box(MARGIN, 2.42, 12.13, 0.04, "border_strong")))
    for i, (when, head, body) in enumerate(stops):
        x = MARGIN + i * pitch
        s.add(
            grp(
                f"stop_{i}",
                Box(x, 2.32, 0.24, 0.24, "brand", "bg", "oval", line_w=2),
                tb(x, 2.75, sw, 0.35, p(when, 15, "brand", True), anchor="m"),
                tb(x, 3.15, sw, 0.8, p(head, 18, "text", True)),
                tb(x, 4.0, sw, 2.2, p(body, 15, "muted")),
            )
        )
    s.add(
        grp(
            "foot",
            tb(
                MARGIN,
                6.3,
                12.13,
                0.4,
                p(
                    "Live on our own machine. Demo data is labelled. Fallback: the paste box, and localhost.",
                    15,
                    "faint",
                ),
                anchor="m",
            ),
        )
    )
    s.motion = [mo("rail", "wipe_from_left", "auto", 100, 700)] + [
        mo(f"stop_{i}", "fly_from_bottom", "with", 100 + 150 * i, 300) for i in range(6)
    ]
    s.motion.append(mo("foot", "fade", "after", 0, 300))
    s.transition = ("push_left", 700)
    s.section = 3
    s.notes = notes(
        DEMO_EN,
        DEMO_AR,
        "Switch to the browser at once. The beat-by-beat lines are in the run-sheet table (submission/DEMO_SCRIPT.md).",
        "Follow the run-sheet failure table: the paste box, localhost, the criterion slides.",
    )
    return s


# criterion slides ------------------------------------------------------------------------------
CRITERIA_FRACTIONS = (6, 5, 4, 3, 2)  # the organiser's proportions as bar geometry only; never printed


def weight_bar(x: float, y: float, current: int, width: float = 4.6) -> list[Shape]:
    total = sum(CRITERIA_FRACTIONS)
    gap = 0.05
    usable = width - gap * (len(CRITERIA_FRACTIONS) - 1)
    out: list[Shape] = []
    cx = x
    for i, share in enumerate(CRITERIA_FRACTIONS):
        w = usable * share / total
        out.append(Box(cx, y, w, 0.12, "sand" if i == current else "border", None, "round", 0.06))
        cx += w + gap
    return out


@dataclass
class Hero:
    runs: list[Run]  # the figure; empty means not measured yet
    frac: float | None  # meter fill 0..1 (None: no fill)
    label: str
    source: str
    chips: Sequence[str] = ()
    supports: Sequence[tuple[list[Run], str]] = ()


def criterion_slide(
    f: Facts,
    key: str,
    cnum: str,
    index: int,
    en: str,
    ar: str,
    hero: Hero,
    how: Sequence[tuple[str, str]],
    amber: str,
    note: str,
    say_ar: str,
    qa: str,
    transition: tuple[str, int],
) -> Slide:
    s = Slide(key, en, ar, title_size=(28, 24), title_w=(6.7, 5.4))
    lx, lw = MARGIN, 5.1
    s.add(grp("chipset", *chip_shapes(lx, 1.8, 0.8, cnum, "brand", "s1", "brand", 16, 0.38)))
    cx = lx + 0.95
    for text in hero.chips:
        w = chip_w(text, 13)
        s.add(*chip_shapes(cx, 1.8, w, text, "warn", "warn_tint", "warn_line", 13, 0.38))
        cx += w + 0.1
    s.add(
        grp(
            "weight",
            *weight_bar(lx, 2.36, index),
            tb(lx, 2.5, 4.6, 0.24, p("Share of the judging score", 12, "faint"), anchor="m"),
        ),
    )
    if hero.runs:
        s.add(grp("hero", tb(lx, 2.68, lw, 1.62, Para(hero.runs), anchor="m")))
        meter = [Box(lx, 4.34, 4.6, 0.06, "border", None, "round", 0.03)]
        fill = Box(lx, 4.34, max(4.6 * (hero.frac or 0), 0.07), 0.06, "brand", None, "round", 0.03)
        s.add(*meter, grp("fill", fill))
    else:
        s.add(grp("hero", tb(lx, 2.68, lw, 1.62, p("Not measured yet", 40, "faint", True), anchor="m")))
        s.add(
            Box(lx, 4.34, 4.6, 0.06, "border", None, "round", 0.03),
            grp("fill", Box(lx, 4.34, 0.07, 0.06, "border_strong")),
        )
    s.add(
        grp("label", tb(lx, 4.48, lw, 0.55, p(hero.label, 17, "text"))),
        grp("source", tb(lx, 5.05, lw, 0.4, p(hero.source, 12, "faint"))),
    )
    n = len(hero.supports)
    if n:
        sw = (lw - 0.1 * (n - 1)) / n
        for i, (runs, label) in enumerate(hero.supports):
            sx = lx + i * (sw + 0.1)
            s.add(
                tb(sx, 5.5, sw, 0.5, Para(runs), anchor="m"),
                tb(sx, 6.02, sw, 0.68, p(label, 13, "muted")),
            )
    rx = lx + lw + 0.4
    rw = W - MARGIN - rx
    y = 1.8
    for i, (lead, body) in enumerate(how):
        s.add(
            grp(
                f"how_{i}",
                card(rx, y, rw, 1.12),
                Box(rx, y, 0.07, 1.12, "brand", None, "rect"),
                tb(
                    rx + 0.3,
                    y,
                    rw - 0.5,
                    1.12,
                    Para([Run(lead, 17, "text", True)], after=2),
                    p(body, 14, "muted"),
                    anchor="m",
                ),
            )
        )
        y += 1.22
    s.add(
        grp(
            "amber",
            Box(rx, y + 0.05, rw, 6.7 - y - 0.05, "warn_tint", "warn_line", "round", 0.12),
            Box(rx, y + 0.05, 0.05, 6.7 - y - 0.05, "warn", None, "rect"),
            tb(
                rx + 0.3,
                y + 0.05,
                rw - 0.5,
                6.7 - y - 0.05,
                Para([Run("Read this with it", 14, "warn", True)], after=3),
                p(amber, 15, "text"),
                anchor="m",
            ),
        )
    )
    s.motion = [
        mo("weight", "wipe_from_left", "auto", 100, 300),
        mo("hero", "zoom", "after", 0, 550),
        mo("fill", "wipe_from_left", "with", 150, 800),
        mo("label", "fade", "after", 0, 300),
        mo("source", "fade", "with", 100, 300),
        mo("amber", "fly_from_bottom", "with", 250, 400),
        mo("how_0", "fly_from_right", "with", 150, 300),
        mo("how_1", "fly_from_right", "with", 300, 300),
        mo("how_2", "fly_from_right", "with", 450, 300),
    ]
    s.transition = transition
    s.section = 4
    s.notes = notes(note, say_ar, "Builds by itself in about two seconds; no click.", "", qa)
    return s


def src(family: str, stem: str | None = None) -> str:
    return "Source: evals/results/published/" + family + ("/" + stem if stem else "")


def slide_c1(f: Facts) -> Slide:
    art = f.artifact
    fp = f.fp
    if art is not None:
        recall, fpr = f.metric("test.recall"), f.metric("test.fpr")
        official = f.metric("test.official_false_dangerous")
        second = f.ev._fresh_group("results_second_source", "phishing_all", "warned") if f.ev else None
        supports: list[tuple[list[Run], str]] = [
            ([Run(pct(fpr), 28, "text", True)], "false-alarm rate"),
            ([Run(str(official), 28, "text", True)], "official sites marked Dangerous"),
        ]
        if second:
            supports.append(
                (
                    [Run(str(second[0]), 28, "text", True), Run(f" of {second[1]}", 16, "muted")],
                    "warned, hosts from a feed we do not query",
                )
            )
        hero = Hero(
            [hero_run(pct(recall))],
            float(recall),
            "of phishing links caught · frozen test split, address only",
            src(art.path.name),
            (),
            supports,
        )
    else:
        hero = Hero([], None, "", src("published"))
    rt = f.ev.redteam_line("extended") if f.ev else None
    amber = (
        f"Live full stack: {pct(fp['false_positive_rate']['value'])} of {fp['n']} held-out legitimate sites flagged, target {pct(fp['target'])}. Above target; it is our first fix."
        if fp
        else "No live end-to-end false-alarm figure is published yet."
    )
    how = [
        (
            "Cascade T0 to T3 and a fixed arbiter",
            "Lists, address model, sealed browser, then the AI only for the unclear band.",
        ),
        (
            "Redirects and cloaking",
            "The sandbox follows redirects and judges the final page; a cloaking check compares two loads.",
        ),
        (
            "The AI cannot change the score",
            ("Red-team, synthetic: " + rt + ".") if rt else "Page text is quarantined before any model sees it.",
        ),
    ]
    batch = (
        " For your hidden set, run our batch checker: make batch with a file of URLs, strict or lenient."
        if cap_on(f, "batch_check")
        else ""
    )
    note = (
        "First criterion, detection accuracy. A cascade with a fixed arbiter, so the AI never sets the score. On our frozen test split the address-only model catches most phishing with a low false-alarm rate, and no official site is marked Dangerous; the figures are on the slide with their scope. "
        "The fresh two-hundred-site test is the harder number: on hosts from a feed our stack does not query, every one was warned, but few were Dangerous and many could not finish every check. We say that plainly. "
        "The red-team row always carries the answered count next to the harmful count." + batch
    )
    return criterion_slide(
        f,
        "c_detection",
        "C1",
        0,
        "Detection accuracy",
        "دقّة الكشف",
        hero,
        how,
        amber,
        note,
        "المعيار الأول، دقّة الكشف: الدرجة يحدّدها محكّم ثابت لا نموذج لغوي، والأرقام أمامكم مع حدودها.",
        "Hidden set: give us the file. False alarms on banks and government: the live number above target, our first fix. Redirects and cloaking: the sandbox follows redirects and compares two loads; no separate score is published, so we quote none.",
        ("push_left", 600),
    )


def slide_c2(f: Facts) -> Slide:
    look = brand_new_group(f, "new_lookalike_brand_pages")
    ben = brand_new_group(f, "benign_controls_novel_hosts")
    msg = f.ev.message["results"]["test"]["shipped"] if f.ev and f.ev.message else None
    if look and ben:
        supports: list[tuple[list[Run], str]] = []
        if msg:
            supports = [
                ([Run(pct(msg["recall"]["value"]), 28, "text", True)], "recall on messages with no link · synthetic"),
                (
                    [Run(str(msg["fpr"]["k"]), 28, "text", True), Run(f" of {msg['n_legit']}", 16, "muted")],
                    "legitimate messages flagged",
                ),
            ]
        hero = Hero(
            kn(look["dangerous_final"]["k"], look["n"]),
            look["dangerous_final"]["k"] / look["n"],
            "brand-new look-alike pages flagged Dangerous · hosts in no feed",
            src("brand_new_pages"),
            ("Synthetic",),
            supports,
        )
        amber = f"Benign controls warned {ben['warning_final']['k']} of {ben['n']}. Search, ads and Maps: 'Ready, needs a key'; no result is shown."
    else:
        hero = Hero([], None, "", src("brand_new_pages"))
        amber = "Search, ads and Maps: 'Ready, needs a key'; no result is shown."
    how = [
        (
            "New look-alike pages, no list needed",
            "A page that claims a brand it does not own and asks for credentials is flagged by a rule.",
        ),
        (
            "Messages with no link",
            "Arabic and English scam scripts are recognised from the text itself. Synthetic set, one author.",
        ),
        (
            "Hunting and fake helplines",
            st(
                f,
                "hunter",
                "Proactive hunting for new look-alike domains: built, off by default, switched on per deployment.",
            )
            + " "
            + st(f, "helpline_registry", "Numbers in a message are checked against an official-number registry."),
        ),
    ]
    note = (
        "Second criterion, early detection and coverage. The point is the page that is on no list yet. A rule flags a page that claims a brand it does not own and asks for credentials. "
        "On our synthetic look-alike set every one was Dangerous, and the benign controls are shown next to it, because a rule like this must not cry wolf. Messages with no link are judged from the text, on a small synthetic set with a wide interval. "
        "Proactive hunting is built, off by default, and switched on per deployment. Search, ads and Maps are ready and need a key; none is configured, so we show no figure."
    )
    return criterion_slide(
        f,
        "c_early",
        "C2",
        1,
        "Early detection and coverage",
        "الكشف المبكر والتغطية",
        hero,
        how,
        amber,
        note,
        "المعيار الثاني، الكشف المبكر: نلتقط الصفحة المنتحِلة حتى إن لم تُدرج في أي قائمة، ونعرض الصفحات المشروعة للمقارنة بجانبها.",
        "Search, ads and Maps: Ready, needs a key. Brand-new look-alikes: caught from the page, not from a list.",
        ("push_left", 600),
    )


def slide_c3(f: Facts) -> Slide:
    fr = faith_ratio(f)
    t3 = f.ev.t3["by_route"]["cloud"] if f.ev and f.ev.t3 else None
    if fr:
        supports = []
        if t3:
            fk = t3["forbidden_tool_call_rate"]
            supports = [
                (
                    [Run(str(fk["k"]), 28, "text", True), Run(f" of {fk['n']}", 16, "muted")],
                    "forbidden tool calls by the Investigator",
                ),
                (
                    [
                        Run(str(t3["reached_T3"]["k"]), 28, "text", True),
                        Run(f" of {t3['reached_T3']['n']}", 16, "muted"),
                    ],
                    "cloud checks that reached T3",
                ),
            ]
        hero = Hero(
            kn(*fr),
            fr[0] / fr[1],
            "shown reasons cite evidence in the verdict · fixture verdicts",
            src("faithfulness"),
            ("Synthetic",),
            supports,
        )
    else:
        hero = Hero([], None, "", src("faithfulness"))
    pack = st(
        f,
        "evidence_pack",
        "Evidence pack: screenshot, WHOIS and RDAP, hosting, UTC times, SHA-256 manifest, takedown draft and STIX.",
    )
    amber = pack + " Reasons are templates tied to evidence, not model text."
    trace = st(
        f,
        "observability_links",
        "Every step, signal and the arbiter's rule is kept in /history, with operator links to the trace and dashboards.",
    )
    export = "REST, signed webhooks, MCP and STIX: ready to connect, not connected."
    if cap_on(f, "batch_check"):
        export += " Batch: a file of URLs in, a results table out."
    how = [
        ("A verdict with reasons", "A risk level, the reasons in Arabic, and what to do now, including after a click."),
        ("A trace for every check", trace),
        ("Nothing leaves without a human", "Takedowns and reports are drafts until a person approves them. " + export),
    ]
    note = (
        "Third criterion, explainability and actionability. Every verdict has a risk level and reasons in plain Arabic, and each reason points at evidence in the verdict; we measured that on fixtures. "
        "Every check keeps a trace you can open, and an operator can jump from it to the trace and dashboards. For a police analyst the evidence pack is the deliverable: screenshot, WHOIS and RDAP, hosting, UTC timestamps, a SHA-256 manifest, a takedown draft and a STIX bundle. "
        "Nothing is sent out by us: a human approves every takedown."
    )
    return criterion_slide(
        f,
        "c_explain",
        "C3",
        2,
        "Explainability and actionability",
        "قابلية التفسير والتنفيذ",
        hero,
        how,
        amber,
        note,
        "المعيار الثالث، التفسير: لكل حكم أسبابه وأثره، ولا يخرج أي إجراء إلا بموافقة إنسان.",
        "Does an LLM decide the verdict? No: the model reads and explains, a fixed arbiter sets the score, and page text is quarantined.",
        ("push_left", 600),
    )


def slide_c4(f: Facts) -> Slide:
    vt = voice_targets(f)
    if vt:
        supports = [
            ([Run(pct(vt["intent_accuracy"]["accuracy"]), 28, "text", True)], "intent understood"),
            ([Run(pct(vt["faq_answer_accuracy"]["accuracy"]), 28, "text", True)], "FAQ answer correct"),
            ([Run(pct(vt["language_accuracy"]["accuracy"]), 28, "text", True)], "language recognised"),
        ]
        hero = Hero(
            [hero_run(pct(vt["wake_accuracy"]["accuracy"]))],
            float(vt["wake_accuracy"]["accuracy"]),
            f"wake phrase recognised · {vt['wake_accuracy']['n']} synthetic clips",
            src("voice"),
            ("Synthetic speech",),
            supports,
        )
    else:
        hero = Hero([], None, "", src("voice"))
    speed = f.ev.voice_speed() if f.ev else None
    voice_row = "Hey Falcon, in Arabic and English, narrates the live steps, greets you" + (
        " and speaks the real findings of each check." if cap_on(f, "voice_findings") else "."
    )
    if speed:
        voice_row += f" Round trip p95 {speed}."
    how = [
        ("Voice assistant", voice_row),
        (
            "Arabic first, UAE brands",
            "UAE banks, TAMM, UAE PASS, Salik, RTA and Abu Dhabi Mobility, each with its official domains.",
        ),
        (
            "Campaigns and visual match",
            "The Sentinel links checks into campaigns; a perceptual hash compares page appearance. "
            + st(f, "mobile_ios", "Works by voice on iPhone and Android."),
        ),
    ]
    amber = "Synthetic speech and noise, not real speakers: an upper bound. A native reader's rating of the Arabic is not measured yet."
    note = (
        "Fourth criterion, UAE relevance and innovation. Formal Arabic first, Emirati Arabic by voice, English too. The brand registry holds the banks, TAMM, UAE PASS, Salik and the road authorities people are actually impersonated as. "
        "What is new: you can simply talk to it, يا صقر; it links checks into scam networks; it compares how a page looks; and an AI helps only in the unclear band, bounded by code. The voice figures come from synthetic speech, so we call them an upper bound."
    )
    return criterion_slide(
        f,
        "c_uae",
        "C4",
        3,
        "UAE relevance and innovation",
        "الارتباط بدولة الإمارات والابتكار",
        hero,
        how,
        amber,
        note,
        "المعيار الرابع: عربي أولاً، وعلامات إماراتية، وتخاطبه بصوتك: يا صقر. أرقام الصوت من كلام مُولَّد، فهي حدّ أعلى.",
        "",
        ("push_left", 600),
    )


def slide_c5(f: Facts) -> Slide:
    runs = sovereign_runs(f)
    if runs:
        hits = sorted({r[3] for r in runs})
        hero_text = str(hits[0]) if len(hits) == 1 else str(sum(r[3] for r in runs))
        supports = [
            (
                [Run(str(ok), 28, "text", True), Run(f" of {n}", 16, "muted")],
                f"scenarios passed on {label}",
            )
            for label, ok, n, _hits, _passed in runs
        ]
        hero = Hero(
            [hero_run(hero_text)],
            0.0,
            "calls to a cloud model in sovereign mode · one machine",
            src("sovereign"),
            (),
            supports[:3],
        )
        failed = any(not r[4] for r in runs)
    else:
        hero = Hero([], None, "", src("sovereign"))
        failed = False
    amber = (
        "One of the runs is marked failed: the Sentinel summary fell back to a template. " if failed else ""
    ) + "Lookups about the checked site still use the internet through the egress proxy."
    how = [
        ("Working live demo", "Everything you saw runs on one Mac Studio, in front of you."),
        ("Sovereign by design", "Every model call can stay on the machine; only lookups about the checked site leave."),
        ("Scales by adding workers", "Redis streams and stateless workers. Proven on one machine only."),
    ]
    note = (
        "Fifth criterion, feasibility and presentation. The demo is live on our own machine. We ran the sovereign proof on two local models, and the cloud-call count is on the slide. "
        "One of the runs is marked failed in the file because the Sentinel summary fell back to a template; we do not hide that. Scaling is by design and proven on one machine only. "
        "A pilot runs the same stack inside the authority's network, in shadow mode first. Ready to connect, not connected."
    )
    return criterion_slide(
        f,
        "c_feasible",
        "C5",
        4,
        "Feasibility and presentation",
        "الجدوى والعرض التقديمي",
        hero,
        how,
        amber,
        note,
        "المعيار الخامس: عرض حي على جهازنا، ويعمل محلياً بالكامل، ومسار تجريبي داخل شبكتكم. جاهز للربط وغير مربوط.",
        "Sovereignty: model calls stay local; lookups use the egress proxy. Scale: add workers; one machine proven.",
        ("push_left", 600),
    )


def slide_pilot(f: Facts) -> Slide:
    s = Slide("pilot_limits", "Pilot path and honest limits", "مسار التجربة وحدودنا", title_w=(7.4, 4.7))
    steps = [
        ("On-premise install", "The same stack inside the authority's network."),
        ("Shadow mode", "Verdicts recorded, nothing sent."),
        ("Analyst review", "Their sign-on, feeds and security review."),
        ("Connect", "REST, MCP, STIX: ready to connect, not connected."),
    ]
    s.add(
        tb(MARGIN, 1.8, 6, 0.32, Para([Run("Pilot path · مسار التجربة", 15, "brand", True)]), anchor="m"),
        grp("pilot_rail", Box(MARGIN + 0.3, 2.37, 11.4, 0.04, "border_strong")),
    )
    sw, pitch = 2.7, 3.15
    for i, (head, body) in enumerate(steps):
        x = MARGIN + i * pitch
        last = i == len(steps) - 1
        s.add(
            grp(
                f"step_{i}",
                Box(x + 0.1, 2.25, 0.28, 0.28, None if last else "brand", "brand", "oval", line_w=2.5, dash=last),
                tb(x, 2.75, sw, 0.4, p(head, 18, "text", True), anchor="m"),
                tb(x, 3.17, sw, 0.8, p(body, 14, "muted")),
            )
        )
    s.add(tb(MARGIN, 4.1, 6, 0.32, Para([Run("Honest limits · حدودنا بصراحة", 15, "warn", True)]), anchor="m"))
    cards: list[tuple[str, str]] = []
    if f.fp is not None:
        fp = f.fp
        cards.append(
            (
                "Live false alarms are above target",
                f"Full stack on {fp['n']} held-out legitimate sites: {pct(fp['false_positive_rate']['value'])} flagged, target {pct(fp['target'])}. Most are checks that could not finish.",
            )
        )
    caveat = f.ev.fresh_caveat() if f.ev else None
    cards.append(
        (
            "One fresh run, synthetic sets",
            (caveat.capitalize() + ". " if caveat else "")
            + "Voice, red-team, message and look-alike sets are synthetic or fixtures.",
        )
    )
    cards.append(
        (
            "Not measured yet",
            "A native reader's rating of the Arabic text, and sandbox recall on labelled phishing pages.",
        )
    )
    cw = (12.13 - 0.4) / 3
    for i, (head, body) in enumerate(cards):
        x = MARGIN + i * (cw + 0.2)
        s.add(
            grp(
                f"limit_{i}",
                Box(x, 4.5, cw, 2.15, "warn_tint", "warn_line", "round", 0.12),
                Box(x, 4.5, cw, 0.06, "warn", None, "rect"),
                tb(x + 0.25, 4.62, cw - 0.5, 1.95, Para([Run(head, 17, "warn", True)], after=4), p(body, 14, "text")),
            )
        )
    s.motion = [mo("pilot_rail", "wipe_from_left", "auto", 100, 600)]
    s.motion += [mo(f"step_{i}", "zoom", "with", 200 * i, 300) for i in range(4)]
    s.motion += [mo("limit_0", "fly_from_bottom", "after", 80, 350)]
    s.motion += [mo(f"limit_{i}", "fly_from_bottom", "with", 180 * i, 350) for i in range(1, len(cards))]
    s.transition = ("push_left", 700)
    s.section = 5
    fp_line = (
        f"live false alarms above target, {pct(f.fp['false_positive_rate']['value'])} against {pct(f.fp['target'])}, and it is our first fix"
        if f.fp
        else "the live false-alarm figure is not published yet"
    )
    s.notes = notes(
        f"A pilot is the same stack inside your network, shadow mode first: your sign-on, your feeds, your security review. REST, MCP and STIX are ready to connect; nothing is connected today. Our limits, from us: {fp_line}; the fresh test is one run; voice, red-team and message sets are synthetic; and two things are not measured yet: a native reader's rating of the Arabic, and sandbox recall on labelled phishing pages.",
        "مسار التجربة: المنظومة نفسها داخل شبكتكم، في وضع المراقبة أولاً. وحدودنا نقولها نحن: الإنذارات الخاطئة في التشغيل الحي أعلى من هدفنا، وهي أول ما نصلحه.",
        "Builds by itself. Leave it up during questions.",
        "",
        "What a pilot looks like: install on-premise, shadow mode, analyst review, then connect. What the limits are: the limit cards.",
    )
    return s


def slide_close(f: Facts) -> Slide:
    s = Slide("close", "Close and team", "الختام والفريق")
    s.add(
        grp("tag_ar", tb(MARGIN, 1.75, 12.13, 0.95, Para([Run(TAG_AR, 54, "brand", True)], "c"), anchor="m")),
        grp("tag_en", tb(MARGIN, 2.72, 12.13, 0.55, p(TAG_EN, 28, "sand", False, "c"), anchor="m")),
    )
    recap = [
        ("Detection", "cascade, fixed arbiter, honest numbers"),
        ("Early detection", "look-alikes with no list"),
        ("Explainable", "reasons, trace, evidence pack"),
        ("UAE and new", "Arabic voice, UAE brands, campaigns"),
        ("Feasible", "live, sovereign, pilot path"),
    ]
    cw, gap = 2.3, 0.1583
    for i, (head, body) in enumerate(recap):
        x = MARGIN + i * (cw + gap)
        s.add(
            grp(
                f"chip_{i}",
                card(x, 3.5, cw, 1.4),
                tb(
                    x + 0.15,
                    3.55,
                    cw - 0.3,
                    1.3,
                    Para([Run(head, 17, "sand", True)], after=3),
                    p(body, 15, "muted"),
                    anchor="m",
                ),
            )
        )
    people = ["Mohamed Atef (Leader)", "Abdulrahman Alseiari", "MokhmadSalakh Salamov"]
    s.add(
        grp(
            "team",
            tb(MARGIN, 5.05, 3, 0.4, Para([Run("Team · الفريق", 16, "brand", True)]), anchor="m"),
            *[
                tb(MARGIN + i * 4.05, 5.45, 3.95, 0.5, p(name, 20, "text", True), anchor="m")
                for i, name in enumerate(people)
            ],
        ),
        tb(MARGIN, 6.1, 6.2, 0.5, p(f.repo_url, 16, "brand", True), anchor="m"),
        Box(W - MARGIN - 5.6, 6.0, 5.6, 0.66, "s1", "faint", "round", 0.12, 1.0, True),
        tb(
            W - MARGIN - 5.45,
            6.0,
            5.3,
            0.66,
            p(NOT_AFFILIATED, 12, "muted", align="c"),
            anchor="m",
        ),
    )
    s.motion = [
        mo("tag_ar", "zoom", "auto", 200, 600),
        mo("tag_en", "fade", "after", 100, 400),
        mo("chip_0", "fly_from_bottom", "after", 0, 300),
    ]
    s.motion += [mo(f"chip_{i}", "fly_from_bottom", "with", 120 * i, 300) for i in range(1, 5)]
    s.motion += [mo("team", "fade", "after", 200, 400)]
    s.transition = ("fade", 600)
    s.section = 6
    s.notes = notes(
        CLOSE_EN + " We are Mohamed Atef, Abdulrahman Alseiari and MokhmadSalakh Salamov. Thank you.",
        CLOSE_AR + " شكراً لكم.",
        "Jump here from the browser with twenty seconds left: type the slide index and press Return in slideshow mode, or keep this window on the slide in a second space. Stay on this slide for questions.",
    )
    return s


def build_slides(f: Facts, img: dict[str, Path] | None = None) -> list[Slide]:
    slides = [
        slide_title(f),
        slide_agenda(f),
        slide_hook(f),
        slide_problem(f),
        slide_solution(f),
        slide_architecture(f),
        slide_demo(f),
        slide_c1(f),
        slide_c2(f),
        slide_c3(f),
        slide_c4(f),
        slide_c5(f),
        slide_pilot(f),
        slide_close(f),
    ]
    for i, s in enumerate(slides):
        if s.chrome == "full":
            frame(s, i + 1, len(slides), s.section)
        elif s.chrome == "frame":
            frame(s, i + 1, len(slides))
    return slides


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


# ── status helpers ───────────────────────────────────────────────────────────
def cap_on(f: Facts, cap: str) -> bool:
    return bool(f.caps.get(cap, False))


def status(f: Facts, cap: str, text: str) -> str:
    """The text as it is when the capability is merged in this checkout, else a 'Planned:' line."""
    return text if cap_on(f, cap) else f"Planned, not on main yet: {text[0].lower()}{text[1:]}"


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


PRESET = {
    "rect": MSO_SHAPE.RECTANGLE,
    "round": MSO_SHAPE.ROUNDED_RECTANGLE,
    "oval": MSO_SHAPE.OVAL,
    "tri_up": MSO_SHAPE.ISOSCELES_TRIANGLE,
    "tri_right": MSO_SHAPE.ISOSCELES_TRIANGLE,
    "tri_down": MSO_SHAPE.ISOSCELES_TRIANGLE,
    "octagon": MSO_SHAPE.OCTAGON,
}
ROTATION = {"tri_right": 90, "tri_down": 180}
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
AUTONUM_PPR = (
    f'<a:buClr xmlns:a="{_A}"><a:srgbClr val="{{c}}"/></a:buClr>',
    f'<a:buFont xmlns:a="{_A}" typeface="Arial"/>',
    f'<a:buAutoNum xmlns:a="{_A}" type="arabicPeriod" startAt="{{n}}"/>',
)


def line_factor(rtl: bool) -> float:
    return 1.25 if rtl else 1.1  # Arabic marks need room (DECK_DESIGN.md 2.3)


def emit_shapes(container: Any, shapes: Sequence[Shape], ids: dict[str, int] | None) -> None:
    """Write drawing-model shapes into a slide or a group. `ids` collects the shape id of each top-level group."""
    anchors = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}
    aligns = {"l": PP_ALIGN.LEFT, "r": PP_ALIGN.RIGHT, "c": PP_ALIGN.CENTER}
    for shape in shapes:
        if isinstance(shape, Group):
            if not shape.shapes:
                continue
            g = container.add_group_shape()
            emit_shapes(g.shapes, shape.shapes, None)
            g.name = shape.name
            if ids is not None:
                ids[shape.name] = g.shape_id
        elif isinstance(shape, Box):
            item = container.add_shape(
                PRESET[shape.shape], Inches(shape.x), Inches(shape.y), Inches(shape.w), Inches(shape.h)
            )
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
                    ln.append(ln.makeelement(qn("a:prstDash"), {"val": "dash"}))
            else:
                item.line.fill.background()
            item.shadow.inherit = False
            if shape.shape == "round":
                item.adjustments[0] = min(0.5, shape.radius / min(shape.w, shape.h))
            if shape.shape in ROTATION:
                item.rotation = ROTATION[shape.shape]
        elif isinstance(shape, Movie):
            mv = container.add_movie(
                str(shape.path),
                Inches(shape.x),
                Inches(shape.y),
                Inches(shape.w),
                Inches(shape.h),
                poster_frame_image=str(shape.poster),
                mime_type="video/mp4",
            )
            mv.name = "hook_video"
            if ids is not None:
                ids["hook_video"] = mv.shape_id
        elif isinstance(shape, Pic):
            pic = container.add_picture(
                str(shape.path), Inches(shape.x), Inches(shape.y), Inches(shape.w), Inches(shape.h)
            )
            pic._element.nvPicPr.cNvPr.set("descr", shape.alt)
        else:
            box = container.add_textbox(Inches(shape.x), Inches(shape.y), Inches(shape.w), Inches(shape.h))
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
                para_obj.line_spacing = Pt(round(max(r.size for r in para.runs) * line_factor(rtl), 1))
                para_obj.space_after = Pt(para.after)
                if para.autonum is not None:
                    ppr = para_obj._p.get_or_add_pPr()
                    ppr.set("marL", str(Inches(0.6)))
                    ppr.set("indent", str(-Inches(0.6)))
                    for tpl in AUTONUM_PPR:
                        ppr.append(etree.fromstring(tpl.format(c=C["brand"].upper(), n=para.autonum)))
                for run in para.runs:
                    r = para_obj.add_run()
                    r.text = run.text
                    r.font.size = Pt(run.size)
                    r.font.bold = run.bold
                    r.font.color.rgb = rgb(run.color)
                    set_font(r, PPTX_FONT, rtl)


def write_pptx(slides: list[Slide], out: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    prs.core_properties.title = "Falcon Lens | عدسة الصقر"
    prs.core_properties.author = "Falcon Lens team"
    prs.core_properties.subject = "ScamShield AI submission"
    blank = next(layout for layout in prs.slide_layouts if layout.name == "Blank")
    for sl in slides:
        slide = prs.slides.add_slide(blank)
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb("bg")
        ids: dict[str, int] = {}
        emit_shapes(slide.shapes, sl.shapes, ids)
        slide.notes_slide.notes_text_frame.text = sl.notes
        steps = []
        for m in sl.motion:
            if m.target not in ids:
                raise KeyError(f"slide {sl.key}: motion target {m.target!r} is not a top-level group")
            trigger = "after" if m.trigger == "auto" else m.trigger
            steps.append(deck_motion.Step(ids[m.target], m.effect, trigger, m.delay, m.dur))
        kind, ms = sl.transition if sl.transition else (None, 0)
        movie = next((sh for sh in sl.shapes if isinstance(sh, Movie)), None)
        media = (ids["hook_video"], movie.ms, movie.auto) if movie else None
        deck_motion.apply_motion(slide, steps, kind, ms, media)
    # Keynote lists unused layouts (Picture with Caption and others) as unsupported media: keep only Blank.
    for layout in list(prs.slide_layouts):
        if layout.name != "Blank":
            prs.slide_layouts.remove(layout)
    out.parent.mkdir(parents=True, exist_ok=True)
    register_notes_master(prs)
    prs.save(str(out))


# ── html writer (PDF and QA renders) ─────────────────────────────────────────
def hx(name: str) -> str:
    return "#" + C[name]


CLIP = {
    "tri_up": "polygon(50% 0,100% 100%,0 100%)",
    "tri_right": "polygon(0 0,100% 50%,0 100%)",
    "tri_down": "polygon(0 0,100% 0,50% 100%)",
    "octagon": "polygon(29% 0,71% 0,100% 29%,100% 71%,71% 100%,29% 100%,0 71%,0 29%)",
}


def html_shape(sh: Shape, parts: list[str]) -> None:
    if isinstance(sh, Group):
        for child in sh.shapes:
            html_shape(child, parts)
        return
    geo = f"left:{sh.x}in;top:{sh.y}in;width:{sh.w}in;height:{sh.h}in;"
    if isinstance(sh, Box):
        radius = "50%" if sh.shape == "oval" else (f"{sh.radius}in" if sh.shape == "round" else "0")
        border = f"border:{sh.line_w}pt {'dashed' if sh.dash else 'solid'} {hx(sh.line)};" if sh.line else ""
        fill = f"background:{hx(sh.fill)};" if sh.fill else ""
        clip = f"clip-path:{CLIP[sh.shape]};" if sh.shape in CLIP else ""
        parts.append(f'<div style="{geo}{fill}{border}{clip}border-radius:{radius}"></div>')
    elif isinstance(sh, Movie):
        parts.append(f'<img src="{sh.poster.as_uri()}" alt="Hook video, poster frame" style="{geo}object-fit:fill">')
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
            if para.autonum is not None:
                num = f'<span style="color:{hx("brand")};display:inline-block;width:0.6in">{para.autonum}.</span>'
                spans = num + spans
            align = {"l": "left", "r": "right", "c": "center"}[para.align]
            inner.append(
                f'<p dir="{"rtl" if rtl else "ltr"}" style="text-align:{align};line-height:{line_factor(rtl)};margin-bottom:{para.after}pt!important">{spans}</p>'
            )
        parts.append(f'<div class="t" style="{geo}justify-content:{just}">{"".join(inner)}</div>')


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
.t p{{margin:0;white-space:normal;overflow-wrap:break-word}}
"""
    )
    parts = [
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Falcon Lens | عدسة الصقر</title><style>{css}</style></head><body>'
    ]
    for sl in slides:
        parts.append(f'<section class="slide" data-key="{sl.key}">')
        for sh in sl.shapes:
            html_shape(sh, parts)
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


ENTRANCE_MIN = (6, 8, 0, 5, 7, 8, 8, 9, 9, 9, 9, 9, 8, 8)  # DECK_DESIGN.md 3.3, per slide
CLICK_BEATS = (0, 8, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0)  # the agenda builds item by item on click (owner)


def verify_pptx(pptx: Path, expected: int, strict_motion: bool = False, video: str | None = None) -> list[str]:
    """Re-open with python-pptx; every part parses; PNG-only media; Blank layout only; notes; motion rules."""
    import zipfile  # noqa: PLC0415

    problems = [f"xml: {item}" for item in deck_motion.parse_all_parts(pptx)]
    prs = Presentation(str(pptx))
    if len(prs.slides) != expected:
        problems.append(f"expected {expected} slides, found {len(prs.slides)}")
    for i, slide in enumerate(prs.slides, 1):
        if not slide.has_notes_slide or not slide.notes_slide.notes_text_frame.text.strip():
            problems.append(f"slide {i} has no speaker notes")
    with zipfile.ZipFile(pptx) as zf:
        for name in zf.namelist():
            low = name.lower()
            if "vbaproject" in low or low.startswith(("ppt/diagrams/", "ppt/embeddings/", "ppt/activex/")):
                problems.append(f"forbidden part: {name}")
            if low.startswith("ppt/media/") and not low.endswith(".png") and not (video and low.endswith(".mp4")):
                problems.append(f"non-PNG media: {name}")
        if b"<p:notesMasterIdLst>" not in zf.read("ppt/presentation.xml"):
            problems.append("presentation.xml has no notesMasterIdLst (Keynote rejects the file)")
        types = zf.read("[Content_Types].xml").decode("utf-8")
        for bad in ("video/", "audio/", "image/svg", "image/x-emf", "image/x-wmf", "image/webp"):
            if bad in types and not (video and bad == "video/"):
                problems.append(f"content type {bad} in the package")
        layouts = [n for n in zf.namelist() if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)]
        if len(layouts) != 1:
            problems.append(f"{len(layouts)} slide layouts; only Blank may remain")
    if strict_motion:
        report = deck_motion.motion_report(pptx)
        for i, row in enumerate(report):
            problems += [f"slide {i + 1}: {item}" for item in row["problems"]]
            if row["transitions"] != 1:
                problems.append(f"slide {i + 1}: expected one transition, found {row['transitions']}")
            if i < len(ENTRANCE_MIN) and row["entrance"] < ENTRANCE_MIN[i]:
                problems.append(f"slide {i + 1}: {row['entrance']} entrance effects, need {ENTRANCE_MIN[i]}")
            want = 1 if (i == 2 and video == "click") else CLICK_BEATS[i] if i < len(CLICK_BEATS) else 0
            if i < len(CLICK_BEATS) and row["click_beats"] != want:
                problems.append(f"slide {i + 1}: {row['click_beats']} click beats, expected {want}")
        total = sum(r["entrance"] for r in report)
        if total < 100:
            problems.append(f"{total} entrance effects in total, need at least 100")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--qa-dir", type=Path, default=None, help="also write one PNG per slide here and report overflow")
    ap.add_argument("--repo-url", default=None)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "submission", help="where the .pptx and .pdf are written")
    ap.add_argument("--name", default=OUT_PPTX.stem, help="base name of the .pptx and .pdf")
    ap.add_argument("--hook-video", type=Path, default=None, help="an .mp4 for the hook slide (never committed)")
    ap.add_argument("--hook-poster", type=Path, default=None, help="PNG poster frame for --hook-video")
    ap.add_argument("--hook-ms", type=int, default=0, help="length of --hook-video in milliseconds")
    ap.add_argument("--hook-auto", action="store_true", help="start the video when the slide opens, not on a click")
    ap.add_argument("--present-html", type=Path, default=None, help="also write a self-contained animated HTML deck")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    global HOOK_MEDIA  # noqa: PLW0603
    HOOK_MEDIA = None
    if args.hook_video:
        if not args.hook_poster:
            ap.error("--hook-video needs --hook-poster")
        HOOK_MEDIA = (args.hook_video.resolve(), args.hook_poster.resolve(), args.hook_ms, args.hook_auto)

    facts = gather(root)
    if args.repo_url:
        facts.repo_url = args.repo_url
    out_pptx, out_pdf = args.out_dir / f"{args.name}.pptx", args.out_dir / f"{args.name}.pdf"
    slides = build_slides(facts, {})
    write_pptx(slides, out_pptx)
    CACHE.mkdir(parents=True, exist_ok=True)
    html_path = CACHE / "deck.html"
    write_html(slides, html_path, root)
    problems = render_pdf_and_qa(html_path, out_pdf, args.qa_dir)
    video = None if not HOOK_MEDIA else ("auto" if args.hook_auto else "click")
    problems += verify_pptx(out_pptx, len(slides), strict_motion=True, video=video)
    if args.present_html:
        import deck_present  # noqa: PLC0415

        deck_present.write(sys.modules[__name__], slides, args.present_html, root)
        print(f"{args.present_html}: {args.present_html.stat().st_size / 1024:.0f} KB")
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
