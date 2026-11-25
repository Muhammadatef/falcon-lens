#!/usr/bin/env python3
# ruff: noqa: E501, S603, S607  (slide copy reads better unwrapped; ffmpeg and git are fixed commands)
"""Build the v2 pitch deck: a tight main path for the three minutes, and a linked deep-dive appendix for questions.

    uv run --no-project --with-requirements scripts/submission/requirements.txt --with lxml \
        python submission/build/build_deck_v2.py --out-dir <dir> [--qa-dir <dir>] [--hook-video media/hook.mp4]

It reuses the drawing model, the motion injector and the HTML presenter of `build_deck.py` (the v1 deck stays as it
is) and adds what v2 needs: one accent colour per part of the product (Baseer teal, Dir' sand, Voice violet,
platform and evidence sky), translucent and gradient fills, more preset shapes, and slide-to-slide links (an index
slide links to every appendix slide and each appendix slide links back).

Rules (CLAUDE.md), enforced by `build_deck.check_text()` on the written file:
- Every figure is read from `evals/results/published/**` at build time; none is typed. The judging weights are drawn
  as bar lengths and never printed, because they are not our measurements.
- The tools slide shows a name only when the generated tools list or the lockfiles, compose file and shipped code
  contain it.
- Never the word for "harmless", never an implied link to Abu Dhabi Police, no police mark. Media is PNG only
  (plus the optional hook video, which is never committed).

Keynote: the .pptx is imported by Keynote (see `submission/build/keynote_v2.sh`), which keeps the builds, the
transitions, the notes and the links. Fonts are Avenir Next (Latin) and Geeza Pro (Arabic); both ship with macOS.
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_deck as bd  # noqa: E402
import deck_motion  # noqa: E402
import deck_present  # noqa: E402
from build_deck import (  # noqa: E402
    Box,
    Facts,
    Group,
    Movie,
    Para,
    Pic,
    Run,
    Slide,
    TextBox,
    chip_shapes,
    grp,
    mo,
    p,
    pct,
    tb,
)
from pptx import Presentation  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Inches  # noqa: E402

ROOT = bd.ROOT
W, H = bd.W, bd.H
M = 0.7
CW = W - 2 * M
NAME = "FalconLens_Pitch_v2"
LATIN_FONT = "Avenir Next"
ARABIC_FONT = "Geeza Pro"
LOGO = ROOT / "web" / "public" / "icons" / "icon-512.png"

# Accent system: one colour per part of the product. Verdict colours (danger, warn) keep their meaning.
bd.C.update(
    {
        "baseer": "3fe0c5",
        "baseer_tint": "0a2726",
        "baseer_line": "1f7a70",
        "dir": "e7d7b6",
        "dir_tint": "25200f",
        "dir_line": "8a7a52",
        "voice": "b9a5ff",
        "voice_tint": "1a1540",
        "voice_line": "5b4bb0",
        "sky": "a9c0ff",
        "sky_tint": "111c3d",
        "sky_line": "34488c",
        "ink": "04211d",
    }
)
bd.PRESET.update(
    {
        "shield": MSO_SHAPE.PENTAGON,
        "chev": MSO_SHAPE.CHEVRON,
        "diamond": MSO_SHAPE.DIAMOND,
        "arrow_d": MSO_SHAPE.DOWN_ARROW,
        "arrow_r": MSO_SHAPE.RIGHT_ARROW,
    }
)
bd.ROTATION["shield"] = 90
bd.CLIP.update(
    {
        "shield": "polygon(0 0,100% 0,100% 50%,50% 100%,0 50%)",
        "chev": "polygon(0 0,50% 0,100% 50%,50% 100%,0 100%,50% 50%)",
        "diamond": "polygon(50% 0,100% 50%,50% 100%,0 50%)",
        "arrow_d": "polygon(25% 0,75% 0,75% 50%,100% 50%,50% 100%,0 50%,25% 50%)",
        "arrow_r": "polygon(0 25%,50% 25%,50% 0,100% 50%,50% 100%,50% 75%,0 75%)",
    }
)
deck_motion.TRANSITIONS.update({"push_up": '<p:push dir="u"/>', "cover_up": '<p:cover dir="u"/>'})


def tones(accent: str) -> tuple[str, str, str]:
    """(foreground, tint, line) of an accent."""
    if accent == "brand":
        accent = "baseer"
    return accent, f"{accent}_tint", f"{accent}_line"


# ── drawing model additions ──────────────────────────────────────────────────
@dataclass
class XBox(Box):
    """A box with a translucent fill (`alpha`, 0 to 1) or a vertical gradient from `fill` (top) to `grad` (bottom)."""

    alpha: float | None = None
    grad: str | None = None


@dataclass
class Hot:
    """An invisible click area that jumps to the slide with this key."""

    x: float
    y: float
    w: float
    h: float
    link: str


def ar(text: str, size: float, color: str = "sand", bold: bool = True, after: float = 0) -> Para:
    return Para([Run(text, size, color, bold)], "r", after)


def en(text: str, size: float, color: str = "text", bold: bool = False, after: float = 0) -> Para:
    return Para([Run(text, size, color, bold)], "l", after)


def panel(x: float, y: float, w: float, h: float, accent: str | None = None, fill: str = "s2") -> list[Any]:
    """A card: a soft vertical gradient, a hairline border and, with an accent, a short bar on the start edge."""
    out: list[Any] = [XBox(x, y, w, h, fill, "border", "round", 0.14, 1.0, False, None, "s1")]
    if accent:
        out.append(Box(x, y + 0.2, 0.055, h - 0.4, tones(accent)[0], None, "round", 0.027))
    return out


def tinted(x: float, y: float, w: float, h: float, accent: str, radius: float = 0.14) -> Box:
    fg, tint, line = tones(accent)
    return Box(x, y, w, h, tint, line, "round", radius)


def pill(
    x: float, y: float, w: float, text: str, accent: str, size: float = 12.5, h: float = 0.34, solid: bool = False
) -> list[Any]:
    fg, tint, line = tones(accent)
    if solid:
        return [Box(x, y, w, h, fg, None, "round", h / 2), tb(x, y, w, h, p(text, size, "ink", True, "c"), anchor="m")]
    return [Box(x, y, w, h, tint, line, "round", h / 2), tb(x, y, w, h, p(text, size, fg, True, "c"), anchor="m")]


def icon_baseer(x: float, y: float, size: float) -> list[Any]:
    return bd.lens_shapes(x, y, size, "baseer")


def icon_dir(x: float, y: float, size: float) -> list[Any]:
    """A shield: Dir' means shield."""
    inner, dot = size * 0.66, size * 0.2
    return [
        Box(x, y, size, size, "dir", None, "shield"),
        Box(x + (size - inner) / 2, y + size * 0.13, inner, inner, "dir_tint", None, "shield"),
        Box(x + (size - dot) / 2, y + size * 0.3, dot, dot, "dir", None, "oval"),
    ]


def icon_voice(x: float, y: float, size: float, color: str = "voice") -> list[Any]:
    """A waveform: five rounded bars."""
    bars = (0.35, 0.7, 1.0, 0.55, 0.3)
    bw = size / 9
    out = []
    for i, k in enumerate(bars):
        bh = size * k
        out.append(Box(x + i * 2 * bw, y + (size - bh) / 2, bw, bh, color, None, "round", bw / 2))
    return out


def badge(x: float, y: float, size: float, accent: str) -> list[Any]:
    """The accent's icon inside a tinted disc."""
    fg, tint, line = tones(accent)
    k = size * 0.5
    ox, oy = x + (size - k) / 2, y + (size - k) / 2
    icon = {
        "baseer": lambda: icon_baseer(ox, oy, k),
        "dir": lambda: icon_dir(ox, oy + k * 0.04, k),
        "voice": lambda: icon_voice(ox, oy, k),
        "sky": lambda: [
            Box(ox, oy + k * (0.1 + 0.32 * i), k, k * 0.2, "sky", None, "round", k * 0.1) for i in range(3)
        ],
        "warn": lambda: [Box(ox, oy, k, k, "warn", None, "tri_up")],
    }[fg]()
    return [Box(x, y, size, size, tint, line, "oval"), *icon]


LOGOS: dict[str, dict[str, Path]] = {}  # slug -> {"light": png, "ink": png}; filled by prepare_logos()
LOGO_DIRS = ("web/public/logos/tools", "submission/build/logos")  # the site's vendored set first, then the deck's
LOGO_NOTE = "Logos belong to their owners; shown to identify the tools used."
# tool -> (logo slug or None, monogram). A tool with no licence-clean file gets the monogram, never a guessed logo.
TOOL_MARK: dict[str, tuple[str | None, str]] = {
    "whisper": ("openai", "Wh"),
    "qwen": ("qwen", "Qw"),
    "kokoro": (None, "Ko"),
    "polly": (None, "Po"),
    "sklearn": ("scikitlearn", "Sk"),
    "playwright": ("playwright", "Pw"),
    "claude": ("claude", "Cl"),
    "ollama": ("ollama", "Ol"),
    "inkling": (None, "In"),
    "python": ("python", "Py"),
    "postgres": ("postgresql", "Pg"),
    "langgraph": ("langgraph", "LG"),
    "langchain": ("langchain", "LC"),
    "dspy": (None, "DS"),
    "fastapi": ("fastapi", "FA"),
    "redis": ("redis", "Re"),
    "docker": ("docker", "Do"),
    "mcp": ("modelcontextprotocol", "MC"),
    "stix": (None, "ST"),
    "grafana": ("grafana", "Gr"),
    "loki": ("grafana", "Lo"),
    "prometheus": ("prometheus", "Pr"),
    "otel": ("opentelemetry", "OT"),
    "phoenix": (None, "Ph"),
    "caddy": ("caddy", "Ca"),
    "cloudflare": ("cloudflare", "CF"),
    "nextjs": ("nextdotjs", "Nx"),
    "mlx": (None, "ML"),
    "fwhisper": (None, "FW"),
}


def prepare_logos(root: Path, cache: Path) -> None:
    """Rasterise every vendored logo to two PNGs (light for dark cards, ink for solid accent fills) with Chromium."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    out_dir = cache / "logos"
    out_dir.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    for slug in {m[0] for m in TOOL_MARK.values() if m[0]}:
        for rel in LOGO_DIRS:
            for ext in ("svg", "png"):
                cand = root / rel / f"{slug}.{ext}"
                if slug not in found and cand.is_file():
                    found[slug] = cand
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 200, "height": 200}, device_scale_factor=1)
        for slug, path in sorted(found.items()):
            LOGOS[slug] = {}
            for tone, colour in (("light", bd.C["text"]), ("ink", bd.C["ink"])):
                target = out_dir / f"{slug}_{tone}.png"
                if path.suffix == ".svg":
                    svg = re.sub(
                        r"<svg ",
                        f'<svg width="160" height="160" fill="#{colour}" ',
                        path.read_text(encoding="utf-8"),
                        count=1,
                    )
                    page.set_content(f'<body style="margin:0;background:transparent">{svg}</body>')
                    page.locator("svg").screenshot(path=str(target), omit_background=True)
                else:
                    target.write_bytes(path.read_bytes())
                LOGOS[slug][tone] = target
        browser.close()


def mark(tool: str, x: float, y: float, size: float, accent: str = "sky", ink: bool = False) -> list[Any]:
    """The tool's logo, or its monogram badge when no licence-clean logo is vendored."""
    slug, mono = TOOL_MARK[tool]
    if slug and slug in LOGOS:
        return [Pic(LOGOS[slug]["ink" if ink else "light"], x, y, size, size, f"{tool} logo")]
    fg, tint, line = tones(accent)
    if ink:
        return [
            Box(x, y, size, size, None, "ink", "round", size * 0.25, 1.0),
            tb(x, y, size, size, p(mono, size * 34, "ink", True, "c"), anchor="m"),
        ]
    return [
        Box(x, y, size, size, tint, line, "round", size * 0.25, 1.0),
        tb(x, y, size, size, p(mono, size * 34, fg, True, "c"), anchor="m"),
    ]


def arrow(x: float, y: float, w: float = 0.26, color: str = "border_strong") -> Box:
    return Box(x, y, w, w, color, None, "chev")


def weight_bar(x: float, y: float, current: int, width: float, color: str) -> list[Any]:
    """The organiser's weights as bar lengths (never printed as figures: they are not our measurements)."""
    total, gap = sum(bd.CRITERIA_FRACTIONS), 0.05
    usable = width - gap * (len(bd.CRITERIA_FRACTIONS) - 1)
    out, cx = [], x
    for i, share in enumerate(bd.CRITERIA_FRACTIONS):
        w = usable * share / total
        out.append(Box(cx, y, w, 0.1, color if i == current else "border", None, "round", 0.05))
        cx += w + gap
    return out


WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def word(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else "several"


def new(key: str, title_en: str, title_ar: str, accent: str, eyebrow: str, appendix: bool = False) -> Slide:
    s = Slide(key, title_en, title_ar, chrome="none")
    s.accent = accent  # type: ignore[attr-defined]
    s.eyebrow = eyebrow  # type: ignore[attr-defined]
    s.appendix = appendix  # type: ignore[attr-defined]
    s.tag = ""  # type: ignore[attr-defined]
    s.plain = False  # type: ignore[attr-defined]
    s.transition = ("fade", 500) if appendix else ("push_left", 700)
    return s


def chrome(s: Slide) -> None:
    """Background glow, eyebrow, bilingual title, footer; on appendix slides the id chip and the way back."""
    accent = tones(s.accent)[0]  # type: ignore[attr-defined]
    decor: list[Any] = [
        XBox(W - 4.4, -3.6, 6.6, 6.6, accent, None, "oval", alpha=0.07),
        XBox(-2.8, 5.3, 5.2, 5.2, accent, None, "oval", alpha=0.04),
    ]
    if s.plain:  # type: ignore[attr-defined]
        s.shapes[:0] = decor
        return
    head: list[Any] = [
        Box(M, 0.5, 0.06, 0.28, accent, None, "round", 0.03),
        tb(M + 0.2, 0.48, 8.5, 0.32, p(s.eyebrow, 12.5, accent, True), anchor="m"),  # type: ignore[attr-defined]
        tb(M, 0.86, 7.7, 0.74, p(s.title_en, 30, "text", True), anchor="m"),
        tb(W - M - 4.9, 0.86, 4.9, 0.74, ar(s.title_ar, 26), anchor="m"),
    ]
    foot: list[Any] = [
        *bd.lens_shapes(M, 6.98, 0.2, "faint"),
        tb(M + 0.32, 6.93, 4.2, 0.3, p("Falcon Lens | عدسة الصقر", 11, "faint", True), anchor="m"),
    ]
    note = "Independent project · ready to connect, not connected"
    if getattr(s, "logos", False):
        note = LOGO_NOTE + " Independent project."
    if s.appendix:  # type: ignore[attr-defined]
        head += pill(W - M - 0.85, 0.46, 0.85, s.tag, s.accent, 13, 0.34)  # type: ignore[attr-defined]
        foot += [
            tb(
                4.3,
                6.93,
                W - M - 2.35 - 4.3,
                0.3,
                p(note, 10.5 if getattr(s, "logos", False) else 11, "faint", align="r"),
                anchor="m",
            ),
            *pill(W - M - 2.15, 6.9, 2.15, "‹ Index · الفهرس", "sky", 12, 0.36),
            Hot(W - M - 2.15, 6.85, 2.15, 0.46, "index"),
        ]
    else:
        foot.append(
            tb(
                W - M - 7.2,
                6.93,
                7.2,
                0.3,
                p(note, 10.5 if getattr(s, "logos", False) else 11, "faint", align="r"),
                anchor="m",
            )
        )
    s.shapes[:0] = decor + head
    s.shapes += foot


def stagger(names: Sequence[str], effect: str, first: str = "auto", gap: int = 130, dur: int = 320) -> list[bd.Mo]:
    """One beat: the first item on `first`, the rest alongside it, each a little later."""
    return [mo(n, effect, first if i == 0 else "with", 100 if i == 0 else gap * i, dur) for i, n in enumerate(names)]


def notes(say_en: str, say_ar: str, do: str, fail: str = "", qa: str = "") -> str:
    return bd.notes(say_en, say_ar, do, fail, qa)


# ── facts ────────────────────────────────────────────────────────────────────
def fresh(f: Facts, part: str, group: str, metric: str) -> tuple[int, int] | None:
    return f.ev._fresh_group(part, group, metric) if f.ev else None


def kof(pair: tuple[int, int] | None, size: float = 30, color: str = "text") -> list[Run]:
    if not pair:
        return [Run("not measured", 16, "faint", True)]
    return [Run(str(pair[0]), size, color, True), Run(f" of {pair[1]}", size * 0.5, "muted", True)]


def src(path: str) -> str:
    return "Source: evals/results/published/" + path


# ── main path ────────────────────────────────────────────────────────────────
TEAM = (("Mohamed Atef", "Team Leader"), ("Abdulrahman Alseiari", ""), ("MokhmadSalakh Salamov", ""))
EVENT = "ScamShield AI Hackathon · Thu 26 Nov 2026"


def slide_title(f: Facts) -> Slide:
    s = new("title", "Falcon Lens", "عدسة الصقر", "baseer", "")
    s.plain = True  # type: ignore[attr-defined]
    s.add(
        grp("logo", Pic(LOGO, 0.95, 1.1, 2.0, 2.0, "The Falcon Lens mark")),
        grp(
            "wordmark",
            tb(
                3.35,
                1.0,
                9.3,
                1.1,
                Para([Run("عدسة الصقر | Falcon Lens", 54, "text", True)], "l", rtl=True),
                anchor="m",
            ),
        ),
        grp("tag_ar", tb(3.35, 2.12, 9.3, 0.72, Para([Run(bd.TAG_AR, 34, "baseer", True)], "l", rtl=True), anchor="m")),
        grp("tag_en", tb(3.35, 2.84, 9.3, 0.46, p(bd.TAG_EN, 21, "muted"), anchor="m")),
    )
    trio = (
        ("baseer", "بصير · Baseer", "The Investigator"),
        ("dir", "درع · Dir'", "The Sentinel"),
        ("voice", "يا صقر · Hey Falcon", "The voice assistant"),
    )
    tw = (CW - 0.4 - 0.5) / 3
    for i, (accent, name, role) in enumerate(trio):
        x = 0.95 + i * (tw + 0.2)
        s.add(
            grp(
                f"agent_{i}",
                tinted(x, 3.78, tw, 0.86, accent),
                *badge(x + 0.16, 3.91, 0.6, accent),
                tb(x + 0.92, 3.84, tw - 1.05, 0.4, Para([Run(name, 17, accent, True)], "l", rtl=False), anchor="m"),
                tb(x + 0.92, 4.2, tw - 1.05, 0.34, p(role, 13.5, "muted"), anchor="m"),
            )
        )
    s.add(grp("event", tb(0.95, 4.98, 11.4, 0.4, p(EVENT, 17, "sand", True), anchor="m")))
    team: list[Any] = [tb(0.95, 5.5, 4, 0.3, p("TEAM · الفريق", 12.5, "faint", True), anchor="m")]
    for i, (name, role) in enumerate(TEAM):
        x = 0.95 + i * (tw + 0.2)
        team += panel(x, 5.86, tw, 0.66)
        team.append(
            tb(
                x + 0.25,
                5.86,
                tw - 0.4,
                0.66,
                Para([Run(name, 17, "text", True)] + ([Run("  ·  " + role, 13, "baseer", True)] if role else [])),
                anchor="m",
            )
        )
    s.add(grp("team", *team))
    s.add(
        grp(
            "indep",
            tb(
                0.95,
                6.82,
                11.4,
                0.3,
                p("An independent project · ready to connect, not connected", 12, "faint"),
                anchor="m",
            ),
        )
    )
    s.motion = [
        mo("logo", "zoom", "auto", 200, 600),
        mo("wordmark", "fly_from_right", "after", 0, 450),
        mo("tag_ar", "wipe_from_right", "after", 0, 450),
        mo("tag_en", "fade", "with", 150, 350),
        *stagger([f"agent_{i}" for i in range(3)], "fly_from_bottom", "after", 140, 350),
        mo("event", "fade", "after", 0, 300),
        mo("team", "fly_from_bottom", "with", 100, 400),
        mo("indep", "fade", "after", 0, 300),
    ]
    s.transition = ("fade", 600)
    s.notes = notes(
        "Good morning. We are Falcon Lens: two AI agents, Baseer and Dir', and a voice on top: Hey Falcon. You will watch a real check run on our own machine, in Arabic, by voice. We are an independent project: ready to connect, not connected.",
        "صباح الخير. نحن فريق «عدسة الصقر»: وكيلان بالذكاء الاصطناعي، «بصير» و«درع»، وفوقهما مساعد صوتي: «يا صقر». سترون فحصاً حقيقياً على جهازنا، بالعربية وبالصوت. مشروع مستقل: جاهز للربط وغير مربوط.",
        "Holding slide; everything builds by itself. Click once to go to the agenda. The clock has not started.",
    )
    return s


def slide_agenda(f: Facts) -> Slide:
    s = new("agenda", "Our three minutes", "دقائقنا الثلاث", "sky", "AGENDA · جدول العرض")
    rows = (
        ("0:00 to 0:25", "Hook: Abu Saeed's story", "المشهد: قصة أبو سعيد", "voice", "hook"),
        (
            "0:25 to 0:55",
            "Why voice · two agents · architecture",
            "لماذا الصوت · الوكيلان · المعمارية",
            "baseer",
            "why_voice",
        ),
        ("0:55 to 2:40", "Live demo, on this machine", "عرض مباشر على هذا الجهاز", "dir", "demo"),
        ("2:40 to 3:00", "Close: five criteria, our evidence", "الختام: المعايير الخمسة وأدلتنا", "sky", "close"),
    )
    lw, rh, gap, y0 = 7.35, 0.98, 0.14, 1.95
    for i, (time, t_en, t_ar, accent, key) in enumerate(rows):
        y = y0 + i * (rh + gap)
        s.add(
            grp(
                f"row_{i}",
                *panel(M, y, lw, rh, accent),
                *pill(M + 0.3, y + 0.32, 1.55, time, accent, 12.5, 0.34),
                tb(M + 2.1, y + 0.1, lw - 2.3, 0.42, p(t_en, 18.5, "text", True), anchor="m"),
                tb(M + 2.1, y + 0.52, lw - 2.3, 0.38, Para([Run(t_ar, 16, "sand", True)], "l", rtl=True), anchor="m"),
            ),
            Hot(M, y, lw, rh, key),
        )
    rx, rw = M + lw + 0.3, CW - lw - 0.3
    rh_all = 4 * rh + 3 * gap
    lines = (
        "Five criteria, one slide each",
        "Baseer · Dir' · the voice layer",
        "Why LangGraph · why DSPy",
        "Tools · sovereignty · integration",
        "Pilot path · honest limits",
    )
    s.add(
        grp(
            "deep",
            tinted(rx, y0, rw, rh_all, "sky"),
            tb(rx + 0.3, y0 + 0.2, rw - 0.6, 0.34, p("THEN · TWO MINUTES OF QUESTIONS", 12.5, "sky", True), anchor="m"),
            tb(rx + 0.3, y0 + 0.56, rw - 0.6, 0.46, p("Deep dive", 24, "text", True), anchor="m"),
            tb(
                rx + 0.3,
                y0 + 1.0,
                rw - 0.6,
                0.4,
                Para([Run("للأسئلة: شرائح التفاصيل", 17, "sand", True)], "l", rtl=True),
                anchor="m",
            ),
            tb(rx + 0.3, y0 + 1.55, rw - 0.6, 1.9, *[en(line, 14.5, "muted", after=5) for line in lines]),
            *pill(rx + 0.3, y0 + rh_all - 0.72, rw - 0.6, "Open the index  ›", "sky", 14, 0.46, solid=True),
        ),
        Hot(rx, y0, rw, rh_all, "index"),
    )
    s.motion = [
        *stagger([f"row_{i}" for i in range(4)], "fly_from_left", "auto", 170, 350),
        mo("deep", "fly_from_right", "after", 0, 400),
    ]
    s.notes = notes(
        "Our path: a short scene, why a voice sits on top of two agents, the architecture, then a live demo, and we close on your five criteria. The deep-dive slides are for your questions.",
        "مسار العرض: مشهد قصير، ثم لماذا وضعنا الصوت فوق وكيلين، ثم المعمارية، ثم عرض مباشر، ونختم بمعاييركم الخمسة. وشرائح التفاصيل لأسئلتكم.",
        "Builds by itself. Every row is a link; 'Open the index' jumps to the deep-dive index. Click (not on a row) to go to the hook: the clock starts there.",
    )
    return s


def slide_hook(f: Facts, media: tuple[Path, Path, int] | None) -> Slide:
    s = new("hook", "Hook", "المشهد", "voice", "")
    s.plain = True  # type: ignore[attr-defined]
    fh = 6.6
    fw = fh * 9 / 16
    fx, fy = (W - fw) / 2, (H - fh) / 2
    if media:
        s.add(Movie(media[0], media[1], fx, fy, fw, fh, media[2], True))
    else:
        s.add(
            XBox(fx, fy, fw, fh, "voice_tint", "voice", "round", 0.18, 2.0, True, None, "s1"),
            Box(fx + fw / 2 - 0.38, fy + 2.05, 0.76, 0.76, "voice", None, "tri_right"),
            tb(fx + 0.25, fy + 3.1, fw - 0.5, 0.5, p("HOOK VIDEO", 20, "voice", True, "c"), anchor="m"),
            tb(
                fx + 0.25,
                fy + 3.6,
                fw - 0.5,
                0.8,
                p("Drag the video onto this frame", 15, "text", False, "c"),
                p("Portrait · fills the frame", 13, "muted", False, "c"),
            ),
            tb(
                fx + 0.25,
                fy + 4.5,
                fw - 0.5,
                0.5,
                Para([Run("اسحب فيديو المشهد إلى هذا الإطار", 16, "sand", True)], "c"),
                anchor="m",
            ),
        )
    s.add(
        grp("chip", *chip_shapes(M, 0.75, 3.3, "تمثيل — Dramatisation", "warn", "warn_tint", "warn_line", 16, 0.46)),
        grp(
            "story_en",
            tb(M, 1.6, 3.9, 0.5, p("Abu Saeed, sixty-five.", 22, "text", True)),
            tb(
                M,
                2.15,
                3.9,
                2.2,
                en("One more text says his account will be frozen.", 16, "muted", after=8),
                en(
                    "He cannot read the small print. He does not know what a phishing link looks like.",
                    16,
                    "muted",
                    after=8,
                ),
                en("He can ask.", 16, "voice", True),
            ),
        ),
        grp(
            "story_ar",
            tb(W - M - 3.9, 1.6, 3.9, 0.5, ar("أبو سعيد، في الخامسة والستين.", 21, "text")),
            tb(
                W - M - 3.9,
                2.2,
                3.9,
                2.4,
                ar("رسالة أخرى تقول إن حسابه سيُجمَّد.", 16, "muted", False, 8),
                ar("لا يقرأ الخط الصغير، ولا يعرف شكل الرابط المزيَّف.", 16, "muted", False, 8),
                ar("لكنه يستطيع أن يسأل.", 16, "voice", True),
            ),
        ),
        tb(
            M,
            6.15,
            3.9,
            0.7,
            p("Invented bank: Falcon Demo Bank. Fictional people. No police logo, uniform or vehicle.", 11.5, "faint"),
        ),
        Pic(LOGO, W - M - 0.7, 6.1, 0.7, 0.7, "The Falcon Lens mark"),
    )
    if not media:
        s.motion = [
            mo("chip", "fade", "auto", 100, 300),
            mo("story_en", "fly_from_left", "after", 0, 400),
            mo("story_ar", "fly_from_right", "with", 0, 400),
        ]
    s.transition = ("fade", 500)
    s.notes = notes(
        "Nothing over the video. When it ends, pause one second.",
        "لا كلام فوق الفيديو. بعد انتهائه توقّف ثانية واحدة.",
        (
            "The video starts by itself, plays with sound and does not loop. Click to go on."
            if media
            else "PLACEHOLDER: drag the hook video onto the dashed frame in Keynote (portrait), then set Start Movie to 'after transition'. Click to go on."
        ),
        f"Say, in Arabic then English: «{bd.HOOK_FAIL_AR}» {bd.HOOK_FAIL_EN} Then click on.",
    )
    return s


def slide_why_voice(f: Facts) -> Slide:
    s = new(
        "why_voice",
        "Why a voice on top of two agents",
        "لماذا الصوت فوق الوكيلين؟",
        "voice",
        "THE PROBLEM · THE ANSWER",
    )
    lw = 3.75
    s.add(
        grp(
            "gap",
            *panel(M, 1.95, lw, 4.7, "warn"),
            tb(M + 0.3, 2.1, lw - 0.5, 0.34, p("THE GAP · الفجوة", 12.5, "warn", True), anchor="m"),
            tb(
                M + 0.3,
                2.55,
                lw - 0.55,
                2.5,
                en("A blocklist lists a scam page only after somebody reports it.", 15.5, "text", after=9),
                en("A page that is new today is on no list today.", 15.5, "text", after=9),
                en("And the warning is rarely in the language people read.", 15.5, "text"),
            ),
            tb(
                M + 0.3,
                5.15,
                lw - 0.55,
                1.4,
                ar("الصفحة الجديدة اليوم ليست في أي قائمة، والتحذير قلّما يأتي بلغة الناس.", 15, "sand", True),
            ),
        )
    )
    cx, cw = M + lw + 0.3, 4.35
    s.add(
        grp(
            "ask",
            tinted(cx, 1.95, cw, 1.95, "voice", 0.2),
            *icon_voice(cx + 0.3, 2.2, 0.62),
            tb(cx + 1.2, 2.1, cw - 1.4, 0.34, p("HE JUST SPEAKS · يتكلّم فقط", 12.5, "voice", True), anchor="m"),
            tb(
                cx + 0.3, 2.9, cw - 0.6, 0.5, Para([Run("«يا صقر، شيّك اللي نسخته»", 20, "text", True)], "c"), anchor="m"
            ),
            tb(
                cx + 0.3,
                3.4,
                cw - 0.6,
                0.36,
                p("“Hey Falcon, check what I copied.”", 14, "muted", False, "c"),
                anchor="m",
            ),
        ),
        grp("down", Box(cx + cw / 2 - 0.17, 4.0, 0.34, 0.34, "voice", None, "arrow_d")),
        grp(
            "answer",
            Box(cx, 4.45, cw, 2.2, "danger_tint", "danger_line", "round", 0.2),
            Box(cx + 0.35, 4.75, 0.42, 0.42, "danger", None, "octagon"),
            tb(cx + 0.95, 4.62, cw - 1.2, 0.34, p("HE HEARS, IN HIS DIALECT", 12, "danger", True), anchor="m"),
            tb(
                cx + 0.3,
                5.2,
                cw - 0.6,
                0.62,
                Para([Run("«خطِر. لا تضغط الرابط.»", 22, "danger", True)], "c"),
                anchor="m",
            ),
            tb(
                cx + 0.3,
                5.85,
                cw - 0.6,
                0.66,
                p("“Dangerous. Do not tap the link.” Then the reasons, spoken.", 13.5, "text", False, "c"),
                anchor="m",
            ),
        ),
    )
    rx = cx + cw + 0.3
    rw = W - M - rx
    who = (
        ("Older residents", "كبار السن", "No small print to read."),
        ("Low literacy", "ضعف القراءة", "No link to inspect, nothing to parse."),
        ("Hands busy", "اليدان مشغولتان", "Driving or working: just ask."),
        ("Arabic first", "العربية أولاً", "Emirati Arabic by voice. English too."),
    )
    ch = 1.07
    for i, (t_en, t_ar, body) in enumerate(who):
        y = 1.95 + i * (ch + 0.14)
        s.add(
            grp(
                f"who_{i}",
                *panel(rx, y, rw, ch, "voice"),
                tb(rx + 0.28, y + 0.1, rw * 0.55, 0.4, p(t_en, 16, "text", True), anchor="m"),
                tb(rx + rw * 0.5, y + 0.1, rw * 0.5 - 0.22, 0.4, ar(t_ar, 14.5), anchor="m"),
                tb(rx + 0.28, y + 0.52, rw - 0.45, 0.46, p(body, 12.5, "muted"), anchor="m"),
            )
        )
    s.motion = [
        mo("gap", "fly_from_left", "auto", 100, 380),
        mo("ask", "zoom", "click", 0, 380),
        mo("down", "wipe_from_top", "after", 0, 300),
        mo("answer", "fly_from_bottom", "after", 0, 380),
        *stagger([f"who_{i}" for i in range(4)], "fly_from_right", "after", 130, 320),
    ]
    s.notes = notes(
        bd.PROBLEM_EN
        + " Abu Saeed cannot read the small print and does not know what a phishing link looks like. So we put a voice on top: he says Hey Falcon, and hears the answer in his own dialect.",
        bd.PROBLEM_AR
        + " وأبو سعيد لا يقرأ الخط الصغير ولا يعرف شكل الرابط المزيَّف. لذلك وضعنا فوق الوكيلين صوتاً: يقول «يا صقر» فيسمع الجواب بلهجته.",
        "The gap card builds by itself. ONE click: the question, the arrow, the spoken answer and the four groups it serves. Then click on.",
        "",
        "Why voice and not only an app? Accessibility: older residents, low literacy, hands busy, Arabic first. The voice calls the same check as the page; details on the voice deep-dive slide.",
    )
    return s


def slide_agents(f: Facts) -> Slide:
    s = new("agents", "Two agents, one voice", "وكيلان وصوت واحد", "baseer", "THE SOLUTION · الحل")
    s.logos = True  # type: ignore[attr-defined]
    cw = (CW - 0.3) / 2
    hunter = bd.st(f, "hunter", "Proactive look-alike hunting: built, off by default")
    cards = (
        (
            "baseer",
            "بصير",
            "Baseer · the Investigator",
            "Judges one message, link, email or QR code.",
            (
                "A cascade, T0–T3: lists, address model, sealed browser, then AI",
                "A deterministic arbiter sets every score; the AI never does",
                "The AI is called only for the unclear cases",
                "Findings for each check, and an evidence pack",
            ),
        ),
        (
            "dir",
            "درع",
            "Dir' · the Sentinel",
            "Watches around the clock, as a LangGraph backend agent.",
            (
                "Correlates single checks into incidents and campaigns",
                hunter,
                "Drafts takedowns and reports; rules decide, the AI explains",
                "A human approves before any external action",
            ),
        ),
    )
    for i, (accent, name_ar, name_en, role, points) in enumerate(cards):
        x = M + i * (cw + 0.3)
        body: list[Any] = [
            *panel(x, 1.95, cw, 3.95, accent),
            *badge(x + 0.3, 2.15, 0.9, accent),
            tb(x + 1.4, 2.08, 2.2, 0.62, Para([Run(name_ar, 34, accent, True)], "l", rtl=True), anchor="m"),
            tb(x + 1.4, 2.7, cw - 1.6, 0.38, p(name_en, 17, "text", True), anchor="m"),
            tb(x + 0.3, 3.25, cw - 0.6, 0.4, p(role, 13.5, "muted"), anchor="m"),
            Box(x + 0.3, 3.72, cw - 0.6, 0.012, "border"),
        ]
        tools = (
            ("sklearn", "playwright", "claude", "ollama") if accent == "baseer" else ("langgraph", "postgres", "redis")
        )
        for j, tool in enumerate(reversed(tools)):
            body += mark(tool, x + cw - 0.62 - j * 0.42, 2.2, 0.3, accent)
        for j, point in enumerate(points):
            y = 3.86 + j * 0.49
            body += [
                Box(x + 0.33, y + 0.15, 0.11, 0.11, accent, None, "oval"),
                tb(x + 0.6, y, cw - 0.85, 0.42, p(point, 13.5, "text"), anchor="m"),
            ]
        s.add(grp(f"card_{i}", *body))
    s.add(
        grp(
            "voice",
            tinted(M, 6.05, CW, 0.7, "voice", 0.2),
            *icon_voice(M + 0.3, 6.2, 0.4),
            tb(
                M + 0.95,
                6.05,
                6.4,
                0.7,
                Para(
                    [
                        Run("Hey Falcon", 16, "voice", True),
                        Run("  ·  one spoken question reaches both agents", 14.5, "text"),
                    ]
                ),
                anchor="m",
            ),
            tb(W - M - 4.6, 6.05, 4.35, 0.7, ar("«يا صقر»: سؤال واحد بصوتك يصل إلى الوكيلين", 15, "sand"), anchor="m"),
        )
    )
    s.motion = [
        mo("card_0", "fly_from_left", "auto", 100, 400),
        mo("card_1", "fly_from_right", "click", 0, 400),
        mo("voice", "wipe_from_left", "after", 0, 450),
    ]
    s.notes = notes(
        bd.SOLUTION_EN,
        bd.SOLUTION_AR,
        "Baseer builds by itself. ONE click: Dir' and the voice strip. Then click on to the architecture.",
        "",
        "Does an LLM decide the verdict? No: fixed code sets the score; the model reads and explains. Is hunting live? It is built and off by default, switched on per deployment.",
    )
    return s


def node(
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    sub: str,
    accent: str,
    solid: bool = False,
    tool: str | None = None,
    glyph: list[Any] | None = None,
) -> list[Any]:
    """A node of the architecture: the tool's logo (or a product glyph) on top, then the name and one short line."""
    fg, tint, line = tones(accent)
    ink = "ink" if solid else "text"
    out: list[Any] = [Box(x, y, w, h, fg if solid else "s1", None if solid else line, "round", 0.1)]
    k = 0.24
    if tool:
        out += mark(tool, x + (w - k) / 2, y + 0.08, k, accent, ink=solid)
    elif glyph:
        out += glyph
    top = y + 0.08 + k + 0.02
    out.append(
        tb(
            x + 0.04,
            top,
            w - 0.08,
            y + h - top - 0.04,
            p(title, 11.5, ink, True, "c"),
            *([p(sub, 10, "ink" if solid else "muted", False, "c")] if sub else []),
            anchor="m",
        )
    )
    return out


def slide_architecture(f: Facts, media: tuple[Path, Path, int] | None = None) -> Slide:
    s = new(
        "architecture",
        "Architecture in three layers",
        "المعمارية في ثلاث طبقات",
        "sky",
        "A REQUEST FLOWS DOWN · الطلب ينزل طبقةً طبقة",
    )
    say_en = (
        "Three layers. The voice layer hears the question on our own machine. It calls the two agents: Baseer runs the cascade and a fixed arbiter sets the score; Dir' links checks and waits for a human. Underneath, the platform: the API, the event bus, the database, the sealed browser, and the integrations, ready to connect. "
        + bd.SOVEREIGN_EN
    )
    say_ar = (
        "ثلاث طبقات: طبقة الصوت تسمع السؤال على جهازنا، ثم الوكيلان: «بصير» يفحص والمحكّم الثابت يحدّد الدرجة، و«درع» يربط الفحوص وينتظر موافقة إنسان، وتحتهما المنصة. "
        + bd.SOVEREIGN_AR
    )
    qa = "Every box is shipped code on main. Integrations are ready to connect, not connected. The tools behind each layer are on the tools deep-dive slide."
    s.logos = True  # type: ignore[attr-defined]
    if media:  # the rendered animated architecture, when it exists at build time
        mh = 4.95
        mw = mh * 16 / 9
        s.add(Movie(media[0], media[1], (W - mw) / 2, 1.82, mw, mh, media[2], True))
        s.notes = notes(
            say_en,
            say_ar,
            "The animated architecture starts by itself, has no sound and does not loop. Click on to the demo slide when the request has reached the platform.",
            "If the film does not play, speak to the still frame.",
            qa,
        )
        return s
    lx, lw = 1.55, W - M - 1.55
    labw = 1.95
    nx = lx + labw + 0.1
    nw = lx + lw - 0.18 - nx
    layers = (
        (2.02, 1.12, "voice", "Voice layer", "طبقة الصوت"),
        (3.36, 1.8, "baseer", "Two AI agents", "طبقة الوكيلين"),
        (5.38, 1.3, "sky", "Platform", "طبقة المنصة"),
    )
    rail_x = M + 0.26
    k = 0.24
    for i, (y, h, accent, t_en, t_ar) in enumerate(layers):
        fg = tones(accent)[0]
        shapes: list[Any] = [
            tinted(lx, y, lw, h, accent, 0.18),
            tb(lx + 0.26, y + h / 2 - 0.42, labw - 0.3, 0.4, p(t_en, 15.5, fg, True), anchor="m"),
            tb(
                lx + 0.26,
                y + h / 2 - 0.02,
                labw - 0.3,
                0.4,
                Para([Run(t_ar, 13.5, "sand", True)], "l", rtl=True),
                anchor="m",
            ),
            XBox(rail_x - 0.27, y + h / 2 - 0.27, 0.54, 0.54, fg, None, "oval", alpha=0.22),
            Box(rail_x - 0.14, y + h / 2 - 0.14, 0.28, 0.28, fg, None, "oval"),
        ]
        ny, nh = y + 0.14, h - 0.28
        if i == 0:
            w1 = (nw - 4 * 0.26) / 5
            xs = [nx + j * (w1 + 0.26) for j in range(5)]
            gx = [x + (w1 - k) / 2 for x in xs]
            shapes += node(
                xs[0],
                ny,
                w1,
                nh,
                "Microphone",
                "end of speech",
                accent,
                glyph=[
                    Box(gx[0] + 0.07, ny + 0.07, 0.1, 0.17, "voice", None, "round", 0.05),
                    Box(gx[0] + 0.11, ny + 0.24, 0.02, 0.05, "voice", None, "rect"),
                    Box(gx[0] + 0.05, ny + 0.29, 0.14, 0.02, "voice", None, "rect"),
                ],
            )
            shapes += node(xs[1], ny, w1, nh, "Speech to text", "Whisper, local", accent, tool="whisper")
            shapes += node(xs[2], ny, w1, nh, "Wake phrase", "«يا صقر»", accent, glyph=icon_voice(gx[2], ny + 0.08, k))
            shapes += node(xs[3], ny, w1, nh, "Intent", "local embeddings", accent, tool="qwen")
            shapes += node(xs[4], ny, w1, nh, "Spoken answer", "prepared clips", accent, tool="kokoro")
            shapes += [arrow(x - 0.23, y + h / 2 - 0.1, 0.2, "voice_line") for x in xs[1:]]
        elif i == 1:
            bw_, dw = nw * 0.6, nw * 0.4 - 0.16
            shapes += [
                Box(nx, ny, bw_, nh, "s1", "baseer_line", "round", 0.14),
                tb(
                    nx + 0.18,
                    ny + 0.05,
                    bw_ - 0.36,
                    0.3,
                    Para(
                        [Run("Baseer", 13.5, "baseer", True), Run("  ·  judges one input", 11.5, "muted")],
                        "l",
                        rtl=False,
                    ),
                    anchor="m",
                ),
                Box(nx + bw_ + 0.16, ny, dw, nh, "s1", "dir_line", "round", 0.14),
                tb(
                    nx + bw_ + 0.34,
                    ny + 0.05,
                    dw - 0.36,
                    0.3,
                    Para(
                        [Run("Dir'", 13.5, "dir", True), Run("  ·  watches all checks", 11.5, "muted")], "l", rtl=False
                    ),
                    anchor="m",
                ),
            ]
            tiers = (
                ("T0", "Lists", "redis"),
                ("T1", "Address", "sklearn"),
                ("T2", "Browser", "playwright"),
                ("T3", "AI", "claude"),
                ("Arbiter", "sets score", "python"),
            )
            tw_ = (bw_ - 0.36 - 4 * 0.09) / 5
            for j, (a, b, tool) in enumerate(tiers):
                shapes += node(
                    nx + 0.18 + j * (tw_ + 0.09), ny + 0.4, tw_, nh - 0.52, a, b, "baseer", solid=j == 4, tool=tool
                )
            steps = (("Correlate", "and rules", "postgres"), ("LangGraph", "triage", "langgraph"))
            sw = (dw - 0.36 - 2 * 0.09) / 3
            for j, (a, b, tool) in enumerate(steps):
                shapes += node(nx + bw_ + 0.34 + j * (sw + 0.09), ny + 0.4, sw, nh - 0.52, a, b, "dir", tool=tool)
            hx_ = nx + bw_ + 0.34 + 2 * (sw + 0.09)
            shapes += node(
                hx_,
                ny + 0.4,
                sw,
                nh - 0.52,
                "Human",
                "approves",
                "dir",
                solid=True,
                glyph=[
                    Box(hx_ + sw / 2 - 0.09, ny + 0.5, 0.07, k - 0.02, "ink", None, "rect"),
                    Box(hx_ + sw / 2 + 0.02, ny + 0.5, 0.07, k - 0.02, "ink", None, "rect"),
                ],
            )
        else:
            names2 = (
                ("REST v1 · SSE", "fastapi"),
                ("Redis Streams", "redis"),
                ("Postgres · pgvector", "postgres"),
                ("Sandbox · proxy", "docker"),
                ("MCP · STIX 2.1", "mcp"),
                ("Observability", "grafana"),
            )
            w3 = (nw - 5 * 0.12) / 6
            for j, (a, tool) in enumerate(names2):
                shapes += node(nx + j * (w3 + 0.12), ny, w3, nh, a, "", accent, tool=tool)
        s.add(grp(f"layer_{i}", *shapes))
    for i in range(2):
        y0 = layers[i][0] + layers[i][1] / 2 + 0.14
        y1 = layers[i + 1][0] + layers[i + 1][1] / 2 - 0.14
        fg = tones(layers[i + 1][2])[0]
        s.add(
            grp(
                f"flow_{i}",
                Box(rail_x - 0.035, y0, 0.07, y1 - y0 - 0.2, fg, None, "rect"),
                Box(rail_x - 0.15, y1 - 0.34, 0.3, 0.3, fg, None, "arrow_d"),
            )
        )
    s.add(grp("request", *pill(M, 1.62, 3.3, "Request · «يا صقر، شيّك اللي نسخته»", "voice", 12, 0.32, solid=True)))
    s.motion = [
        mo("request", "fly_from_left", "auto", 100, 350),
        mo("layer_0", "wipe_from_left", "after", 0, 500),
        mo("flow_0", "wipe_from_top", "click", 0, 350),
        mo("layer_1", "wipe_from_left", "after", 0, 500),
        mo("flow_1", "wipe_from_top", "after", 100, 350),
        mo("layer_2", "wipe_from_left", "after", 0, 500),
    ]
    s.notes = notes(
        say_en,
        say_ar,
        "The request and the voice layer build by themselves. ONE click: the highlighted request flows down to the agents and then to the platform. Then click on to the demo slide.",
        "",
        qa,
    )
    return s


def slide_demo(f: Facts) -> Slide:
    s = new("demo", "Live demo, on this machine", "عرض مباشر على هذا الجهاز", "dir", "LIVE · مباشر")
    beats = (
        (
            "1:00 to 1:35",
            "voice",
            "«يا صقر، شيّك اللي نسخته»",
            "The Arabic SMS is checked step by step. The plate turns red: «خطِر». The falcon speaks the findings.",
            "Voice · Baseer",
        ),
        (
            "1:35 to 1:55",
            "voice",
            "“Hey Falcon…” in English",
            "An English question. A short, sourced answer, in the language you asked in.",
            "Voice",
        ),
        (
            "1:55 to 2:10",
            "baseer",
            "/history · evidence pack",
            "The trace of the check just made. One click downloads the evidence pack.",
            "Baseer",
        ),
        (
            "2:10 to 2:25",
            "dir",
            "/campaigns · /results",
            "Dir' links similar checks into a campaign. Then our numbers, with their limits.",
            "Dir'",
        ),
        (
            "2:25 to 2:40",
            "sky",
            "/ops · route selector",
            "Cloud model with a local fallback, or local only. Same checks, same arbiter.",
            "Sovereign",
        ),
    )
    n = len(beats)
    cw = (CW - (n - 1) * 0.16) / n
    s.add(grp("rail", Box(M + 0.1, 2.14, CW - 0.2, 0.03, "border_strong", None, "rect")))
    for i, (time, accent, head, body, tag) in enumerate(beats):
        x = M + i * (cw + 0.16)
        fg = tones(accent)[0]
        rtl_head = bd.is_arabic(head.lstrip("«“"))
        s.add(
            grp(
                f"beat_{i}",
                Box(x + cw / 2 - 0.13, 2.025, 0.26, 0.26, fg, None, "oval"),
                *panel(x, 2.5, cw, 3.3, accent),
                *pill(x + 0.22, 2.68, 1.5, time, accent, 12, 0.32),
                tb(
                    x + 0.24,
                    3.12,
                    cw - 0.42,
                    0.86,
                    Para([Run(head, 14.5, "text", True)], "r" if rtl_head else "l"),
                    anchor="m",
                ),
                tb(x + 0.24, 4.02, cw - 0.42, 1.3, p(body, 12.5, "muted")),
                tb(x + 0.24, 5.38, cw - 0.42, 0.3, p(tag, 12, fg, True), anchor="m"),
            )
        )
    s.add(
        grp(
            "switch",
            *pill(M, 6.02, 3.6, "›  Switch to the browser now", "dir", 14, 0.5, solid=True),
            tb(
                M + 3.85,
                6.02,
                CW - 3.85,
                0.5,
                p(
                    "If the voice fails: paste the same SMS on the Check page. A check that cannot finish is shown as Suspicious, never clean.",
                    12.5,
                    "faint",
                ),
                anchor="m",
            ),
        )
    )
    s.motion = [
        mo("rail", "wipe_from_left", "auto", 100, 600),
        *stagger([f"beat_{i}" for i in range(n)], "fly_from_bottom", "with", 150, 320),
        mo("switch", "fade", "after", 0, 300),
    ]
    s.notes = notes(
        bd.DEMO_EN
        + " Each step is real: the lists, the address, the page in a sealed browser, then the AI for the unclear part, then the Sentinel. Follow the run-sheet for every beat (submission/DEMO_SCRIPT.md).",
        bd.DEMO_AR + " كل خطوة حقيقية: القوائم، العنوان، الصفحة في متصفح معزول، ثم الذكاء الاصطناعي، ثم درع.",
        "Builds by itself. Switch to the browser at once: the demo starts now. With twenty seconds left, come back to the deck and click on to the close.",
        "Microphone fails: paste box on the Check page. Sound fails: read «خطِر» and the first reason aloud. Tunnel down: use localhost. Browser fails: click on and speak to the close slide and the criterion slides.",
        "If a beat runs long, drop /ops first, then the English question. Never narrate a verdict before it is on screen.",
    )
    return s


def criteria_tiles(f: Facts) -> list[tuple[str, str, str, list[Run], str, str]]:
    """(link key, C-id, name, figure runs, label, source) for the five criteria. Every figure is read from an artifact."""
    out = []
    recall = (
        [Run(pct(f.metric("test.recall")), 38, "text", True)]
        if f.artifact
        else [Run("not measured", 16, "faint", True)]
    )
    out.append(
        (
            "c_detection",
            "C1",
            "Detection accuracy",
            recall,
            "of phishing links caught · frozen test split, address only",
            f.artifact.path.name if f.artifact else "published",
        )
    )
    look = bd.brand_new_group(f, "new_lookalike_brand_pages")
    out.append(
        (
            "c_early",
            "C2",
            "Early detection and coverage",
            kof((look["dangerous_final"]["k"], look["n"]) if look else None, 38),
            "brand-new look-alike pages flagged Dangerous · synthetic",
            "brand_new_pages",
        )
    )
    out.append(
        (
            "c_explain",
            "C3",
            "Explainability and actionability",
            kof(bd.faith_ratio(f), 38),
            "shown reasons cite evidence in the verdict · fixtures",
            "faithfulness",
        )
    )
    vt = bd.voice_targets(f)
    wake = (
        [Run(pct(vt["wake_accuracy"]["accuracy"]), 38, "text", True)]
        if vt
        else [Run("not measured", 16, "faint", True)]
    )
    out.append(
        ("c_uae", "C4", "UAE relevance and innovation", wake, "wake phrase recognised · synthetic speech", "voice")
    )
    runs = bd.sovereign_runs(f)
    calls = (
        [Run(str(sum(r[3] for r in runs)), 38, "text", True), Run(" cloud calls", 17, "muted", True)]
        if runs
        else [Run("not measured", 16, "faint", True)]
    )
    out.append(
        (
            "c_feasible",
            "C5",
            "Feasibility and presentation",
            calls,
            "to a cloud model in sovereign mode · live on one machine",
            "sovereign",
        )
    )
    return out


def slide_close(f: Facts) -> Slide:
    s = new("close", "Five criteria, our evidence", "معاييركم وأدلتنا", "sky", "CLOSE · الختام")
    tiles = criteria_tiles(f)
    tw = (CW - 4 * 0.17) / 5
    for i, (key, cid, name, runs, label, source) in enumerate(tiles):
        x = M + i * (tw + 0.17)
        s.add(
            grp(
                f"tile_{i}",
                *panel(x, 1.95, tw, 2.72),
                *pill(x + 0.2, 2.1, 0.62, cid, "sky", 12, 0.3),
                *weight_bar(x + 0.95, 2.2, i, tw - 1.15, "sky"),
                tb(x + 0.2, 2.5, tw - 0.35, 0.56, p(name, 13, "sky", True), anchor="m"),
                tb(x + 0.2, 3.0, tw - 0.3, 0.78, Para(runs), anchor="m"),
                tb(x + 0.2, 3.8, tw - 0.35, 0.56, p(label, 11, "muted")),
                tb(x + 0.2, 4.36, tw - 0.35, 0.24, p("Source: " + source[:16], 9.5, "faint"), anchor="m"),
            ),
            Hot(x, 1.95, tw, 2.72, key),
        )
    s.add(
        grp("tag_ar", tb(M, 4.9, 7.2, 0.8, Para([Run(bd.TAG_AR, 38, "baseer", True)], "l", rtl=True), anchor="m")),
        grp(
            "tag_en",
            tb(M, 5.68, 7.2, 0.44, p(bd.TAG_EN, 20, "text"), anchor="m"),
            tb(M, 6.14, 7.2, 0.4, p("Live, sovereign, ready to connect, not connected.", 14, "muted"), anchor="m"),
        ),
    )
    tx, twd = M + 7.5, CW - 7.5
    team: list[Any] = [
        *panel(tx, 4.88, twd, 1.52),
        tb(tx + 0.3, 4.94, twd - 0.6, 0.28, p("TEAM · الفريق", 12, "faint", True), anchor="m"),
    ]
    for i, (name, role) in enumerate(TEAM):
        team.append(
            tb(
                tx + 0.3,
                5.22 + i * 0.37,
                twd - 0.6,
                0.36,
                Para([Run(name, 15.5, "text", True)] + ([Run("  ·  " + role, 12, "baseer", True)] if role else [])),
                anchor="m",
            )
        )
    s.add(grp("team", *team))
    s.add(
        grp("qa", *pill(W - M - 2.6, 6.48, 2.6, "Questions  ›  deep dive", "sky", 12, 0.34, solid=True)),
        Hot(W - M - 2.7, 6.42, 2.7, 0.46, "index"),
    )
    s.motion = [
        *stagger([f"tile_{i}" for i in range(5)], "zoom", "auto", 140, 380),
        mo("tag_ar", "wipe_from_right", "after", 0, 500),
        mo("tag_en", "fade", "with", 200, 350),
        mo("team", "fly_from_right", "with", 100, 400),
        mo("qa", "fade", "after", 0, 300),
    ]
    s.notes = notes(
        bd.CLOSE_EN,
        bd.CLOSE_AR,
        "Builds by itself. Each tile is a link to its criterion slide; 'Questions › deep dive' opens the index. Stay here for questions and jump from here.",
        "",
        "The bar on each tile is that criterion's share of the judging score. Say only the figures that are on the screen.",
    )
    return s


# ── appendix ─────────────────────────────────────────────────────────────────
def slide_index(f: Facts, entries: list[Slide]) -> Slide:
    s = new("index", "Deep dive: pick a question", "للأسئلة: اختر الموضوع", "sky", "INDEX · every card is a link")
    cols = 5
    cw = (CW - (cols - 1) * 0.17) / cols
    ch = 1.48
    for i, e in enumerate(entries):
        x = M + (i % cols) * (cw + 0.17)
        y = 1.9 + (i // cols) * (ch + 0.14)
        accent = e.accent  # type: ignore[attr-defined]
        s.add(
            grp(
                f"card_{i}",
                *panel(x, y, cw, ch, accent),
                *pill(x + 0.22, y + 0.16, 0.7, e.tag, accent, 12, 0.3),  # type: ignore[attr-defined]
                tb(x + 0.24, y + 0.5, cw - 0.4, 0.56, p(e.short_en, 13.5, "text", True), anchor="m"),  # type: ignore[attr-defined]
                tb(x + 0.24, y + 1.04, cw - 0.4, 0.36, ar(e.short_ar, 12.5), anchor="m"),  # type: ignore[attr-defined]
            ),
            Hot(x, y, cw, ch, e.key),
        )
    s.add(*pill(M + 3.2, 6.9, 2.3, "‹ Back to the close", "baseer", 12, 0.36), Hot(M + 3.2, 6.85, 2.3, 0.46, "close"))
    s.motion = stagger([f"card_{i}" for i in range(len(entries))], "zoom", "auto", 55, 300)
    s.transition = ("push_up", 600)
    s.notes = notes(
        "These are the deep-dive slides. Tell me which one you would like to see.",
        "هذه شرائح التفاصيل. اختاروا الموضوع الذي تودّون رؤيته.",
        "Click a card to jump to its slide. Every deep-dive slide has '‹ Index' at the bottom right to come back here. '‹ Back to the close' returns to the closing slide.",
    )
    return s


SHORT_AR = {
    "c_early": "الكشف المبكر",
    "c_explain": "التفسير والتنفيذ",
    "c_uae": "الإمارات والابتكار",
    "c_feasible": "الجدوى والعرض",
}


def criterion_slide(
    f: Facts,
    key: str,
    cnum: str,
    index: int,
    t_en: str,
    t_ar: str,
    hero: bd.Hero,
    how: Sequence[tuple[str, str]],
    amber: str,
    note: str,
    say_ar: str,
    qa: str,
    transition: tuple[str, int],
) -> Slide:
    """The v2 layout for the five criterion slides. The content (and every figure) comes from build_deck.slide_c1..c5."""
    s = new(key, t_en, t_ar, "sky", f"CRITERION {cnum} · WHAT WE MEASURED", appendix=True)
    lw = 5.05
    s.add(
        grp(
            "weight",
            *weight_bar(M, 1.98, index, 3.3, "sky"),
            tb(M + 3.45, 1.88, 1.7, 0.3, p("share of the score", 11, "faint"), anchor="m"),
        )
    )
    cx = M
    chips: list[Any] = []
    for text in hero.chips:
        w = bd.chip_w(text, 12)
        chips += chip_shapes(cx, 2.22, w, text, "warn", "warn_tint", "warn_line", 12, 0.32)
        cx += w + 0.1
    if hero.runs:
        runs = [
            Run(r.text, round(r.size * 0.78, 1), "sky" if r.color == "brand" else r.color, r.bold) for r in hero.runs
        ]
        s.add(grp("hero", *chips, tb(M, 2.5, lw, 1.46, Para(runs), anchor="m")))
        s.add(
            Box(M, 3.98, 4.6, 0.06, "border", None, "round", 0.03),
            grp("fill", Box(M, 3.98, max(4.6 * (hero.frac or 0), 0.07), 0.06, "sky", None, "round", 0.03)),
        )
    else:
        s.add(grp("hero", *chips, tb(M, 2.52, lw, 1.38, p("Not measured yet", 38, "faint", True), anchor="m")))
        s.add(
            Box(M, 3.98, 4.6, 0.06, "border", None, "round", 0.03),
            grp("fill", Box(M, 3.98, 0.07, 0.06, "border_strong")),
        )
    s.add(
        grp(
            "label",
            tb(M, 4.12, lw, 0.6, p(hero.label, 15.5, "text")),
            tb(M, 4.74, lw, 0.3, p(hero.source, 11, "faint"), anchor="m"),
        )
    )
    n = len(hero.supports)
    sup: list[Any] = []
    if n:
        sw = (lw - 0.14 * (n - 1)) / n
        for i, (runs2, label) in enumerate(hero.supports):
            sx = M + i * (sw + 0.14)
            sup += [
                *panel(sx, 5.2, sw, 1.5),
                tb(
                    sx + 0.18,
                    5.27,
                    sw - 0.3,
                    0.5,
                    Para(
                        [
                            Run(r.text, min(r.size, 24) if r.bold and r.size > 20 else r.size * 0.9, r.color, r.bold)
                            for r in runs2
                        ]
                    ),
                    anchor="m",
                ),
                tb(sx + 0.18, 5.78, sw - 0.3, 0.88, p(label, 11.5, "muted")),
            ]
    s.add(grp("supports", *sup))
    rx = M + lw + 0.4
    rw = W - M - rx
    y = 1.9
    for i, (lead, body) in enumerate(how):
        s.add(
            grp(
                f"how_{i}",
                *panel(rx, y, rw, 1.1, "sky"),
                tb(
                    rx + 0.3,
                    y + 0.04,
                    rw - 0.5,
                    1.02,
                    Para([Run(lead, 15.5, "text", True)], after=2),
                    p(body, 12.5, "muted"),
                    anchor="m",
                ),
            )
        )
        y += 1.2
    s.add(
        grp(
            "amber",
            Box(rx, y, rw, 6.7 - y, "warn_tint", "warn_line", "round", 0.14),
            tb(
                rx + 0.3,
                y + 0.03,
                rw - 0.5,
                6.7 - y - 0.06,
                Para([Run("Read this with it · اقرأ هذا معه", 12.5, "warn", True)], after=3),
                p(amber, 13.5, "text"),
                anchor="m",
            ),
        )
    )
    s.motion = [
        mo("weight", "wipe_from_left", "auto", 100, 300),
        mo("hero", "zoom", "after", 0, 450),
        mo("fill", "wipe_from_left", "with", 150, 700),
        mo("label", "fade", "after", 0, 300),
        *([mo("supports", "fly_from_bottom", "with", 150, 350)] if sup else []),
        *stagger([f"how_{i}" for i in range(len(how))], "fly_from_right", "with", 130, 300),
        mo("amber", "fly_from_bottom", "after", 0, 350),
    ]
    s.short_en, s.short_ar = t_en, SHORT_AR.get(key, t_ar)  # type: ignore[attr-defined]
    s.notes = notes(
        note, say_ar, "Builds by itself. '‹ Index' at the bottom right goes back to the deep-dive index.", "", qa
    )
    return s


def flow_row(
    names: Sequence[tuple[str, str]],
    x: float,
    y: float,
    w: float,
    h: float,
    accent: str,
    solid_last: bool = False,
    gap: float = 0.34,
) -> list[Any]:
    n = len(names)
    cw = (w - (n - 1) * gap) / n
    out: list[Any] = []
    for i, (a, b) in enumerate(names):
        cx = x + i * (cw + gap)
        fg, tint, line = tones(accent)
        solid = solid_last and i == n - 1
        out += [
            Box(cx, y, cw, h, fg if solid else "s1", None if solid else line, "round", 0.12),
            tb(cx + 0.12, y + 0.1, cw - 0.24, 0.42, p(a, 14, "ink" if solid else fg, True, "c"), anchor="m"),
            tb(cx + 0.12, y + 0.52, cw - 0.24, h - 0.6, p(b, 11.5, "ink" if solid else "muted", False, "c")),
        ]
        if i:
            out.append(arrow(cx - gap / 2 - 0.11, y + h / 2 - 0.11, 0.22, line))
    return out


def fact_card(x: float, y: float, w: float, h: float, head: str, body: str, accent: str, source: str = "") -> list[Any]:
    out = [
        *panel(x, y, w, h, accent),
        tb(
            x + 0.28,
            y + 0.1,
            w - 0.48,
            h - 0.2 - (0.24 if source else 0),
            Para([Run(head, 14.5, "text", True)], after=3),
            p(body, 12.5, "muted"),
            anchor="m",
        ),
    ]
    if source:
        out.append(tb(x + 0.28, y + h - 0.32, w - 0.48, 0.24, p(source, 9.5, "faint"), anchor="m"))
    return out


def slide_baseer(f: Facts) -> Slide:
    s = new(
        "d_baseer",
        "Baseer, the Investigator",
        "«بصير»، المحقّق",
        "baseer",
        "AGENT · judges one message, link, email or QR code",
        appendix=True,
    )
    s.short_en, s.short_ar = "Baseer: cascade and arbiter", "بصير: التدرّج والمحكّم"  # type: ignore[attr-defined]
    tiers = (
        ("T0 · Lists", "Known scam lists and the registry of official domains."),
        ("T1 · Address", "Look-alike spelling, domain age and structure, scored by a small model."),
        ("T2 · Sealed browser", "One passive visit in an isolated sandbox. No form is ever submitted."),
        ("T3 · AI investigator", "Only the unclear cases, with a bounded number of typed tool calls."),
        ("Arbiter", "Fixed code turns evidence into the score and the band. The AI never sets or changes a score."),
    )
    s.add(grp("flow", *flow_row(tiers, M, 1.95, CW, 1.62, "baseer", solid_last=True)))
    plates = (
        ("Dangerous", "خطِر", "danger", "octagon"),
        ("Suspicious", "مشبوه", "warn", "tri_up"),
        ("No warning signs found", "لم نجد علامات تحذير", "nws", "oval"),
    )
    pw = (CW - 0.4) / 3
    for i, (t_en, t_ar, tone, glyph) in enumerate(plates):
        s.add(grp(f"plate_{i}", *bd.plate_shapes(M + i * (pw + 0.2), 3.78, pw, t_en, t_ar, tone, glyph, 0.84)))
    facts: list[tuple[str, str, str]] = [
        (
            "What comes out",
            "A verdict with reasons in Arabic that cite evidence, the findings of each check, what to do now, and an evidence pack for an analyst.",
            "",
        )
    ]
    if f.ev and f.ev.t3:
        facts.append(
            ("The AI stays inside its bounds", (f.ev.t3_line() or "").capitalize() + ".", src("t3_investigator"))
        )
    rt = f.ev.redteam_line("extended") if f.ev else None
    if rt:
        facts.append(("Injected text cannot move the score", "Red-team, synthetic: " + rt + ".", src("redteam")))
    fw = (CW - 0.2 * (len(facts) - 1)) / len(facts)
    for i, (head, body, source) in enumerate(facts):
        s.add(grp(f"fact_{i}", *fact_card(M + i * (fw + 0.2), 4.85, fw, 1.85, head, body, "baseer", source)))
    s.motion = [
        mo("flow", "wipe_from_left", "auto", 100, 700),
        *stagger([f"plate_{i}" for i in range(3)], "zoom", "after", 130, 320),
        *stagger([f"fact_{i}" for i in range(len(facts))], "fly_from_bottom", "after", 130, 320),
    ]
    s.notes = notes(
        "Baseer judges one input. Cheap checks first: lists, then the address, then one passive visit in a sealed browser. Only an unclear case reaches the AI investigator, and it is bounded: a few typed tool calls, no free text that anything acts on. Signals return evidence, never a verdict; a fixed arbiter sets the score. We never say a site is harmless: the lowest verdict is No warning signs found, with a caution.",
        "«بصير» يحكم على مُدخل واحد: القوائم أولاً، ثم العنوان، ثم زيارة واحدة في متصفح معزول، ولا يصل إلى الذكاء الاصطناعي إلا الحالات غير الواضحة. والدرجة يحدّدها محكّم ثابت لا نموذج لغوي.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "Why not let the model decide? A score from fixed code can be inspected and re-run; a model may explain a verdict, it never produces one.",
    )
    return s


def slide_dir(f: Facts) -> Slide:
    s = new(
        "d_dir",
        "Dir', the Sentinel",
        "«درع»، الحارس",
        "dir",
        "AGENT · a backend agent that runs around the clock",
        appendix=True,
    )
    s.short_en, s.short_ar = "Dir': campaigns and approval", "درع: الحملات والموافقة"  # type: ignore[attr-defined]
    steps = (
        ("Listen", "Every finished check arrives as an event on the bus."),
        ("Correlate", "Similar checks are linked: same host, same script, same look."),
        ("Rules decide", "Fixed rules decide what is an incident or a campaign."),
        ("LangGraph triage", "Assess, summarise, propose. The AI only enriches."),
        ("Human approves", "The graph pauses. Nothing leaves without a person."),
    )
    s.add(grp("flow", *flow_row(steps, M, 1.95, CW, 1.62, "dir", solid_last=True)))
    hunter = bd.st(
        f,
        "hunter",
        "New look-alike domains are found from certificate logs and appear on the campaigns board. Built, off by default, switched on per deployment.",
    )
    cards = (
        ("Proactive look-alike hunting", hunter),
        (
            "Built to survive a restart",
            "State is saved in Postgres after each step, under the incident id. After a restart every paused incident continues.",
        ),
        (
            "The model is a worker, not the boss",
            "Past its budget the model is skipped and a template is used. A claim is kept only if it cites evidence that exists.",
        ),
        (
            "Drafts only",
            "Takedown drafts in Arabic and English, STIX bundles and webhooks are prepared and wait for approval. This build sends nothing by itself.",
        ),
    )
    fw = (CW - 0.2) / 2
    for i, (head, body) in enumerate(cards):
        s.add(
            grp(f"fact_{i}", *fact_card(M + (i % 2) * (fw + 0.2), 3.82 + (i // 2) * 1.47, fw, 1.35, head, body, "dir"))
        )
    s.motion = [
        mo("flow", "wipe_from_left", "auto", 100, 700),
        *stagger([f"fact_{i}" for i in range(4)], "fly_from_bottom", "after", 130, 320),
    ]
    s.notes = notes(
        "One check protects one person. Dir' protects many: it listens to every finished check, links the similar ones, and fixed rules decide what is an incident or a campaign. A LangGraph triage then assesses, summarises and proposes actions, and the graph pauses for a human before anything leaves the system. Proactive hunting for new look-alike domains is built and off by default.",
        "فحص واحد يحمي شخصاً، و«درع» يحمي كثيرين: يستمع إلى كل فحص، ويربط المتشابه، والقواعد الثابتة تقرّر ما هو حادثة أو حملة، ثم يتوقف الرسم بانتظار موافقة إنسان قبل أي إجراء خارجي.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "Is hunting on? Built, off by default, switched on per deployment. Does it send takedowns? No: drafts only, a human approves.",
    )
    return s


def slide_voice(f: Facts) -> Slide:
    s = new(
        "d_voice",
        "The voice layer: «يا صقر»",
        "طبقة الصوت: «يا صقر»",
        "voice",
        "VOICE · one spoken question reaches both agents",
        appendix=True,
    )
    s.short_en, s.short_ar = "Voice: how it works", "الصوت: كيف يعمل"  # type: ignore[attr-defined]
    steps = (
        ("Microphone", "The browser detects the end of speech."),
        ("Speech to text", "Whisper on our own machine. Audio is not stored."),
        ("Wake phrase", "“Hey Falcon” or «يا صقر», and the language."),
        ("Intent", "Fixed rules, then a local embedding match, else a redirect."),
        ("Spoken answer", "Prepared clips: Emirati Arabic and English."),
    )
    s.add(grp("flow", *flow_row(steps, M, 1.95, CW, 1.5, "voice", solid_last=True)))
    vt = bd.voice_targets(f)
    tiles: list[tuple[list[Run], str]] = []
    if vt:
        for key, label in (
            ("wake_accuracy", "wake phrase recognised"),
            ("intent_accuracy", "intent understood"),
            ("faq_answer_accuracy", "FAQ answer correct"),
            ("language_accuracy", "language recognised"),
        ):
            tiles.append(([Run(pct(vt[key]["accuracy"]), 28, "voice", True)], label))
        speed = f.ev.voice_speed() if f.ev else None
        if speed:
            tiles.append(([Run(speed, 28, "voice", True)], "round trip, p95"))
    if tiles:
        tw = (CW - 0.16 * (len(tiles) - 1)) / len(tiles)
        for i, (runs, label) in enumerate(tiles):
            x = M + i * (tw + 0.16)
            s.add(
                grp(
                    f"tile_{i}",
                    *panel(x, 3.68, tw, 1.32),
                    tb(x + 0.22, 3.76, tw - 0.4, 0.6, Para(runs), anchor="m"),
                    tb(x + 0.22, 4.36, tw - 0.4, 0.3, p(label, 12, "muted"), anchor="m"),
                    tb(x + 0.22, 4.68, tw - 0.4, 0.24, p("Source: published/voice", 9, "faint"), anchor="m"),
                )
            )
    n_clips = vt["wake_accuracy"]["n"] if vt else None
    bound = (
        f"Measured on {n_clips} synthetic clips (generated voices and synthetic noise), not real speakers: an upper bound."
        if n_clips
        else "Voice figures are not published yet."
    )
    s.add(
        grp(
            "why",
            *fact_card(
                M,
                5.2,
                (CW - 0.2) / 2,
                1.5,
                "Why voice at all",
                "Older residents, people who do not read easily, hands busy, Arabic first. The voice calls the same public check as the page, so nothing is judged differently.",
                "voice",
            ),
        ),
        grp(
            "amber",
            Box(M + (CW + 0.2) / 2, 5.2, (CW - 0.2) / 2, 1.5, "warn_tint", "warn_line", "round", 0.14),
            tb(
                M + (CW + 0.2) / 2 + 0.3,
                5.25,
                (CW - 0.2) / 2 - 0.5,
                1.4,
                Para([Run("Read this with it · اقرأ هذا معه", 12.5, "warn", True)], after=3),
                p(bound + " Attempts to override its instructions by voice are refused.", 13, "text"),
                anchor="m",
            ),
        ),
    )
    s.motion = [
        mo("flow", "wipe_from_left", "auto", 100, 700),
        *stagger([f"tile_{i}" for i in range(len(tiles))], "zoom", "after", 110, 320),
        mo("why", "fly_from_bottom", "after", 0, 320),
        mo("amber", "fly_from_bottom", "with", 130, 320),
    ]
    s.notes = notes(
        "The voice layer is thin on purpose. The browser hears the end of speech, Whisper turns it into text on our own machine, we check the wake phrase and the language, and an intent step decides: check what was copied, answer a prepared question, help, or stop. The answer is spoken from prepared clips. The figures come from synthetic speech, so we call them an upper bound.",
        "طبقة الصوت خفيفة عمداً: يُحوَّل الكلام إلى نص على جهازنا، ثم نتحقق من عبارة التنبيه واللغة، ثم يُحدَّد المقصود، ويُنطق الجواب من مقاطع جاهزة. والأرقام من كلام مُولَّد، فهي حدّ أعلى.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "Is the Arabic voice a cloud call? No: the clips were generated ahead of time from our own script and are played locally. Real speakers? Not measured yet.",
    )
    return s


def grid_slide(
    s: Slide,
    items: Sequence[tuple[str, str]],
    cols: int,
    y0: float,
    y1: float,
    accent: str,
    footer: tuple[str, str, str] | None = None,
) -> None:
    rows = -(-len(items) // cols)
    foot_h = 0.95 if footer else 0
    gap = 0.16
    ch = (y1 - y0 - foot_h - (0.16 if footer else 0) - gap * (rows - 1)) / rows
    cw = (CW - 0.2 * (cols - 1)) / cols
    for i, (head, body) in enumerate(items):
        x = M + (i % cols) * (cw + 0.2)
        y = y0 + (i // cols) * (ch + gap)
        s.add(grp(f"item_{i}", *fact_card(x, y, cw, ch, head, body, accent)))
    names = [f"item_{i}" for i in range(len(items))]
    s.motion = stagger(names, "fly_from_bottom", "auto", 110, 320)
    if footer:
        tone, head, body = footer
        fg, tint, line = tones(tone)
        fy = y1 - foot_h
        s.add(
            grp(
                "footer",
                Box(M, fy, CW, foot_h, tint, line, "round", 0.14),
                tb(
                    M + 0.3,
                    fy + 0.04,
                    CW - 0.6,
                    foot_h - 0.08,
                    Para([Run(head, 13.5, fg, True)], after=2),
                    p(body, 13, "text"),
                    anchor="m",
                ),
            )
        )
        s.motion.append(mo("footer", "fly_from_bottom", "after", 0, 350))


def slide_why_langgraph(f: Facts) -> Slide:
    s = new(
        "d_langgraph", "Why LangGraph", "لماذا LangGraph؟", "dir", "DESIGN CHOICE · the Sentinel's graph", appendix=True
    )
    s.short_en, s.short_ar = "Why LangGraph", "لماذا LangGraph"  # type: ignore[attr-defined]
    items = (
        (
            "An explicit, auditable map",
            "The graph is a visible list of steps and edges, and each step has a defined set of tools. A reviewer reads the map instead of guessing from a prompt.",
        ),
        (
            "It survives restarts",
            "A Postgres checkpointer saves state after each node. A crash or a deployment does not lose an investigation; it resumes from the last saved step.",
        ),
        (
            "A built-in pause for a human",
            "The interrupt stops the graph before any external action and resumes only on approve or reject. No instruction in a message can skip it.",
        ),
        (
            "Budgets, retries and traces",
            "Each node has its own retry policy; each incident has a budget of steps, tokens and time. Metrics and traces show where they go.",
        ),
        (
            "Built to run all day",
            "The Sentinel consumes events around the clock. It is not a request handler, and a graph with saved state suits that shape.",
        ),
        (
            "It works with local models",
            "The graph calls our own model router, so sovereign mode applies to every node and nothing needs a cloud provider.",
        ),
    )
    grid_slide(
        s,
        items,
        3,
        1.9,
        6.7,
        "dir",
        (
            "dir",
            "Why the Investigator is not LangGraph",
            "Baseer is a short, bounded state machine with a few typed tool calls: one check stays fast, resists injection and is reproducible. We depend on langchain-core only, not on prebuilt agents.",
        ),
    )
    s.notes = notes(
        "We chose LangGraph for the Sentinel for five reasons you can audit: the graph is an explicit map of steps and tools; a Postgres checkpointer makes it survive a restart; the human-approval pause is part of the structure, so no injected text can skip it; every node has budgets, retries and traces; and it runs on local models through our own router.",
        "اخترنا LangGraph لـ«درع» لأسباب يمكن تدقيقها: خريطة واضحة للخطوات والأدوات، وحفظ للحالة ينجو من إعادة التشغيل، وتوقّف مدمج لموافقة الإنسان لا يتجاوزه أي نص، وميزانيات وتتبّع لكل خطوة، وعمل على النماذج المحلية.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "Why not a prebuilt agent? A model that decides its own next step with no fixed bound is hard to audit and easy to steer with injected text.",
    )
    return s


def slide_why_dspy(f: Facts) -> Slide:
    s = new(
        "d_dspy",
        "Why DSPy",
        "لماذا DSPy؟",
        "baseer",
        "DESIGN CHOICE · measured prompts for every AI role",
        appendix=True,
    )
    s.short_en, s.short_ar = "Why DSPy, honest result", "لماذا DSPy"  # type: ignore[attr-defined]
    items = (
        (
            "Prompts are measured, not guessed",
            "Hand-tuned prompts improve by feel and regress silently. DSPy optimisers search instructions and examples against labelled cases.",
        ),
        (
            "Typed Signatures are contracts",
            "Each AI role declares typed inputs and outputs: the same contract our validators already check (schema, evidence that exists, valid tool arguments).",
        ),
        (
            "One pipeline, cloud and local",
            "The optimiser runs with the cloud model and with the local model, so the sovereign route gets prompts tuned for the model it really runs.",
        ),
        (
            "Reproducible and versioned",
            "A compiled prompt is a frozen file with a checksum, per role and per route. It can be reviewed, rolled back and re-run.",
        ),
        (
            "A gate against self-deception",
            "A candidate is adopted only when its gain is outside noise on held-out cases. Production loads the frozen file and never imports the optimiser.",
        ),
    )
    roles = len(f.ev.dspy) if f.ev else 0
    adopted = sum(1 for d in (f.ev.dspy if f.ev else []) if d.get("adopted"))
    if roles and not adopted:
        result = f"We ran the optimiser on {word(roles)} AI roles. None is adopted yet: every gain was within noise, so the hand-written prompts stay. We show the pipeline, not a win."
    elif roles:
        result = f"We ran the optimiser on {word(roles)} AI roles; {word(adopted)} passed the gate and are adopted, the rest stay hand-written."
    else:
        result = "No optimisation run is published yet."
    grid_slide(s, [*items, ("The honest result", result)], 3, 1.9, 6.7, "baseer")
    last = s.shapes[-1]
    if isinstance(last, Group):  # the result card is amber: it is a limit, said plainly
        cw = (CW - 0.4) / 3
        x, y, h = M + 2 * (cw + 0.2), last.shapes[0].y, last.shapes[0].h
        last.shapes[:] = [
            Box(x, y, cw, h, "warn_tint", "warn_line", "round", 0.14),
            tb(
                x + 0.28,
                y + 0.1,
                cw - 0.48,
                h - 0.46,
                Para([Run("The honest result · النتيجة بصراحة", 14, "warn", True)], after=3),
                p(result, 12.5, "text"),
                anchor="m",
            ),
            tb(x + 0.28, y + h - 0.32, cw - 0.48, 0.24, p(src("dspy"), 9.5, "faint"), anchor="m"),
        ]
    s.notes = notes(
        "DSPy gives us a systematic way to optimise the prompt of every AI role: each role is a typed Signature, the optimiser is scored by our own production validators on labelled data, and the same pipeline runs for the cloud model and the local model. The honest result is on the slide: we ran it on the roles, and none is adopted yet, because the gate needs a gain outside noise.",
        "تعطينا DSPy طريقة منهجية لتحسين تعليمات كل دور للذكاء الاصطناعي: لكل دور توقيع مكتوب الأنواع، والقياس على بيانات موسومة، والمسار نفسه للنموذج السحابي والمحلي. والنتيجة بصراحة: شغّلناها على الأدوار ولم نعتمد أياً منها بعد، لأن الكسب لم يتجاوز هامش الضجيج.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "Then why keep it? The pipeline is the asset: when a model or a prompt changes, we can measure the change instead of guessing. What would change the result: more labelled cases, which narrows the noise.",
    )
    return s


# (display name, needles): shown only when a needle is in the generated tools list or in the shipped tree.
TOOL_LAYERS: tuple[tuple[str, str, str, tuple[tuple[str, tuple[str, ...], str], ...]], ...] = (
    (
        "voice",
        "Voice layer",
        "طبقة الصوت",
        (
            ("MLX Whisper", ("mlx-whisper", "mlx_whisper"), "mlx"),
            ("faster-whisper", ("faster-whisper",), "fwhisper"),
            ("Whisper large-v3-turbo", ("large-v3-turbo",), "whisper"),
            ("Qwen3-Embedding", ("qwen3-embedding",), "qwen"),
            ("Kokoro · English clips", ("kokoro",), "kokoro"),
            ("Amazon Polly Zayd · offline Arabic clips", ("zayd",), "polly"),
        ),
    ),
    (
        "baseer",
        "Agents and AI",
        "الوكيلان والنماذج",
        (
            ("LangGraph", ("langgraph",), "langgraph"),
            ("langchain-core", ("langchain-core",), "langchain"),
            ("DSPy", ("dspy",), "dspy"),
            ("Claude Sonnet · Haiku", ("claude sonnet", "anthropic"), "claude"),
            ("Ollama", ("ollama",), "ollama"),
            ("Inkling-2-Mini", ("inkling",), "inkling"),
            ("Qwen3.8", ("qwen3.8",), "qwen"),
            ("Playwright sandbox", ("playwright",), "playwright"),
            ("scikit-learn", ("scikit-learn",), "sklearn"),
        ),
    ),
    (
        "sky",
        "Platform and data",
        "المنصة والبيانات",
        (
            ("Python", ("python",), "python"),
            ("FastAPI", ("fastapi",), "fastapi"),
            ("PostgreSQL + pgvector", ("pgvector",), "postgres"),
            ("Redis Streams", ("redis",), "redis"),
            ("MCP server", ("model context protocol", "mcp"), "mcp"),
            ("STIX 2.1", ("stix",), "stix"),
            ("Next.js PWA", ("next.js",), "nextjs"),
        ),
    ),
    (
        "dir",
        "Operations",
        "التشغيل والمراقبة",
        (
            ("OpenTelemetry", ("opentelemetry",), "otel"),
            ("Arize Phoenix", ("phoenix",), "phoenix"),
            ("Prometheus", ("prometheus",), "prometheus"),
            ("Grafana", ("grafana",), "grafana"),
            ("Loki", ("loki",), "loki"),
            ("Caddy", ("caddy",), "caddy"),
            ("Docker Compose", ("docker compose",), "docker"),
            ("Cloudflare Tunnel", ("cloudflare",), "cloudflare"),
        ),
    ),
)
TREE = (
    "uv.lock",
    "docker-compose.yml",
    "web/package.json",
    ".env.example",
    "Makefile",
    "services",
    "packages",
    "infra",
    "config",
    "evals/dspy",
    "scripts/voice_native.sh",
    "web/lib",
    "tools",
)


def in_tree(root: Path, needle: str) -> bool:
    paths = [t for t in TREE if (root / t).exists()]
    done = subprocess.run(["git", "grep", "-qiF", "--", needle, "--", *paths], cwd=root, check=False)
    return done.returncode == 0


def shipped_tools(f: Facts, root: Path) -> list[tuple[str, str, str, list[tuple[str, str]]]]:
    generated = " | ".join(name.lower() for _, items in f.tools for name in items)
    out = []
    for accent, t_en, t_ar, tools in TOOL_LAYERS:
        found = []
        for display, needles, tool in tools:
            if any(n in generated for n in needles) or any(in_tree(root, n) for n in needles):
                found.append((display, tool))
            else:
                print(
                    f"tools slide: dropped {display!r} (not in the generated list or the shipped tree)", file=sys.stderr
                )
        out.append((accent, t_en, t_ar, found))
    return out


def slide_tools(f: Facts, root: Path) -> Slide:
    s = new(
        "d_tools",
        "The stack, layer by layer",
        "الأدوات، طبقةً طبقة",
        "sky",
        "TOOLS · only what the shipped code uses",
        appendix=True,
    )
    s.logos = True  # type: ignore[attr-defined]
    s.short_en, s.short_ar = "Tools and stack, by layer", "الأدوات حسب الطبقة"  # type: ignore[attr-defined]
    rows = shipped_tools(f, root)
    rh, gap, y0 = 1.02, 0.12, 1.9
    labw = 2.7
    for i, (accent, t_en, t_ar, tools) in enumerate(rows):
        y = y0 + i * (rh + gap)
        fg = tones(accent)[0]
        shapes: list[Any] = [
            tinted(M, y, CW, rh, accent, 0.16),
            *badge(M + 0.2, y + 0.24, 0.6, accent),
            tb(M + 0.95, y + 0.14, labw - 0.9, 0.4, p(t_en, 14, fg, True), anchor="m"),
            tb(M + 0.95, y + 0.54, labw - 0.9, 0.4, Para([Run(t_ar, 13, "sand", True)], "l", rtl=True), anchor="m"),
        ]
        x, line, x0, xmax = M + labw + 0.15, 0, M + labw + 0.15, M + CW - 0.2
        for display, tool in tools:
            w = len(display) * 0.094 + 0.66
            if x + w > xmax:
                line, x = line + 1, x0
            cy = y + 0.12 + line * 0.42
            shapes += [
                Box(x, cy, w, 0.36, "s1", tones(accent)[2], "round", 0.18),
                *mark(tool, x + 0.12, cy + 0.06, 0.24, accent),
                tb(x + 0.42, cy, w - 0.46, 0.36, p(display, 12, "text", True), anchor="m"),
            ]
            x += w + 0.1
        s.add(grp(f"row_{i}", *shapes))
    s.add(
        tb(
            M,
            y0 + 4 * (rh + gap) - 0.04,
            CW,
            0.3,
            p(
                "Generated from the lockfiles, the compose file and the shipped code. Unfinished items are not listed.",
                11.5,
                "faint",
            ),
            anchor="m",
        )
    )
    s.motion = stagger([f"row_{i}" for i in range(len(rows))], "wipe_from_left", "auto", 200, 450)
    s.notes = notes(
        "The stack by layer. Voice: Whisper on our own machine and prepared clips. Agents and AI: LangGraph for the Sentinel, DSPy for prompt optimisation, Claude or local models through Ollama, and a Playwright sandbox. Platform: FastAPI, Postgres with pgvector, Redis Streams, an MCP server and STIX export. Operations: OpenTelemetry, Phoenix, Prometheus, Grafana and Loki, behind Caddy, in Docker Compose.",
        "الأدوات حسب الطبقة: الصوت يعمل محلياً، والوكيلان على LangGraph مع نماذج سحابية أو محلية، والمنصة على FastAPI وPostgres وRedis، والمراقبة بأدوات مفتوحة المصدر.",
        "Builds by itself, layer by layer. '‹ Index' goes back.",
        "",
        "Everything on this slide is in the repository's lockfiles, compose file or shipped code. The Arabic voice was generated offline; nothing calls that service at run time.",
    )
    return s


def slide_sovereignty(f: Facts) -> Slide:
    s = new(
        "d_sovereign",
        "Data sovereignty: fully on-premise",
        "سيادة البيانات داخل شبكتكم",
        "sky",
        "SOVEREIGN · open-source local models for every AI job",
        appendix=True,
    )
    s.short_en, s.short_ar = "Data sovereignty", "سيادة البيانات"  # type: ignore[attr-defined]
    s.logos = True  # type: ignore[attr-defined]
    models = (
        ("Language model", "Inkling-2-Mini or Qwen3.8, through Ollama", "ollama"),
        ("Embeddings", "Qwen3-Embedding", "qwen"),
        ("Speech to text", "Whisper large-v3-turbo (MLX or faster-whisper)", "whisper"),
        ("English voice", "Kokoro, prepared clips", "kokoro"),
    )
    lw = 5.6
    for i, (job, model, tool) in enumerate(models):
        y = 1.9 + i * 0.84
        s.add(
            grp(
                f"model_{i}",
                *panel(M, y, lw, 0.72, "sky"),
                *mark(tool, M + 0.28, y + 0.2, 0.32, "sky"),
                tb(M + 0.78, y, 1.6, 0.72, p(job, 13, "sky", True), anchor="m"),
                tb(M + 2.4, y, lw - 2.55, 0.72, p(model, 13, "text", True), anchor="m"),
            )
        )
    s.add(
        grp(
            "arabic",
            *fact_card(
                M,
                5.28,
                lw,
                1.42,
                "Arabic voice: prepared offline",
                "The Emirati Arabic clips were generated ahead of time from our own script (Amazon Polly, voice Zayd). At run time the product plays local files: no live call, no user data.",
                "voice",
            ),
        )
    )
    rx, rw = M + lw + 0.3, CW - lw - 0.3
    runs = bd.sovereign_runs(f)
    proof: list[tuple[list[Run], str]] = []
    for label, ok, n, _hits, _passed in runs:
        proof.append((kof((ok, n), 34, "sky"), f"scenarios passed on {label}"))
    if runs:
        proof.append(([Run(str(sum(r[3] for r in runs)), 34, "sky", True)], "calls to a cloud model, both runs"))
    if proof:
        tw = (rw - 0.16 * (len(proof) - 1)) / len(proof)
        for i, (r, label) in enumerate(proof):
            x = rx + i * (tw + 0.16)
            s.add(
                grp(
                    f"proof_{i}",
                    *panel(x, 1.9, tw, 1.74),
                    tb(x + 0.2, 2.0, tw - 0.3, 0.74, Para(r), anchor="m"),
                    tb(x + 0.2, 2.76, tw - 0.3, 0.5, p(label, 12, "muted")),
                    tb(x + 0.2, 3.3, tw - 0.3, 0.24, p("published/sovereign", 9, "faint"), anchor="m"),
                )
            )
    hw = (rw - 0.5) / 2
    s.add(
        grp(
            "route",
            tb(rx, 3.78, rw, 0.3, p("THE OPERATOR CHOOSES THE ROUTE · /ops", 12, "faint", True), anchor="m"),
            Box(rx, 4.12, hw, 0.9, "s1", "border_strong", "round", 0.14),
            tb(
                rx + 0.15,
                4.12,
                hw - 0.3,
                0.9,
                p("Cloud model", 14, "text", True, "c"),
                p("with a local fallback", 12, "muted", False, "c"),
                anchor="m",
            ),
            tb(rx + hw, 4.12, 0.5, 0.9, p("or", 13, "faint", True, "c"), anchor="m"),
            Box(rx + hw + 0.5, 4.12, hw, 0.9, "sky_tint", "sky", "round", 0.14),
            tb(
                rx + hw + 0.65,
                4.12,
                hw - 0.3,
                0.9,
                p("Local only", 14, "sky", True, "c"),
                p("nothing leaves for a model", 12, "muted", False, "c"),
                anchor="m",
            ),
        )
    )
    failed = any(not r[4] for r in runs)
    amber = (
        ("One run is marked failed in its file: the Sentinel summary fell back to a template. " if failed else "")
        + "Lookups about the checked site (registration data, one passive page visit) still use the internet, through the egress proxy. Proven on one machine."
    )
    s.add(
        grp(
            "amber",
            Box(rx, 5.28, rw, 1.42, "warn_tint", "warn_line", "round", 0.14),
            tb(
                rx + 0.3,
                5.32,
                rw - 0.5,
                1.34,
                Para([Run("Read this with it · اقرأ هذا معه", 12.5, "warn", True)], after=3),
                p(amber, 13, "text"),
                anchor="m",
            ),
        )
    )
    s.motion = [
        *stagger([f"model_{i}" for i in range(4)], "fly_from_left", "auto", 130, 320),
        *stagger([f"proof_{i}" for i in range(len(proof))], "zoom", "after", 130, 350),
        mo("route", "fade", "after", 0, 320),
        mo("arabic", "fly_from_bottom", "after", 0, 320),
        mo("amber", "fly_from_bottom", "with", 130, 320),
    ]
    line = f.ev.sovereign_line() if f.ev else None
    s.notes = notes(
        "The whole product can run on-premise on open-source local models: the language model, the embeddings, speech to text and the English voice. We proved it: "
        + (line + "." if line else "the proof run is not published yet.")
        + " The Arabic voice was prepared offline as clips, so nothing is called at run time. The operator picks the route: a cloud model with a local fallback, or local only.",
        "المنتج كله يعمل داخل شبكتكم على نماذج محلية مفتوحة المصدر: النموذج اللغوي، والتضمينات، وتحويل الكلام إلى نص، والصوت الإنجليزي. والصوت العربي مقاطع أُعدّت مسبقاً، فلا اتصال وقت التشغيل. والمشغّل يختار المسار: سحابي مع بديل محلي، أو محلي بالكامل.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "Does anything leave? Model calls can all stay on the machine. Lookups about the checked site still use the internet through our egress proxy. Scale: proven on one machine only.",
    )
    return s


def slide_integration(f: Facts) -> Slide:
    s = new(
        "d_integration",
        "Integration: ready to connect",
        "الربط: جاهز وغير مربوط",
        "sky",
        "INTEGRATION · for police systems and AI assistants",
        appendix=True,
    )
    s.short_en, s.short_ar = "Integration options", "خيارات الربط"  # type: ignore[attr-defined]
    items = (
        ("REST v1 API", "Check a link, a message, an email or an image; a live stream of steps; scoped API keys."),
        ("MCP server", "The same typed tools for AI assistants and analyst systems, over streamable HTTP."),
        ("STIX 2.1 export", "Incidents and indicators as standard bundles for threat-intelligence platforms."),
        ("Signed webhooks", "Events pushed to a system you choose, signed, and only after a person approves."),
        (
            "Evidence pack",
            bd.st(
                f,
                "evidence_pack",
                "Screenshot, WHOIS and RDAP, hosting, TLS, UTC timestamps, a SHA-256 manifest and a takedown draft in Arabic and English.",
            ),
        ),
        (
            "Batch tool",
            bd.st(
                f,
                "batch_check",
                "A file of URLs in, a results table out, in a strict and a lenient mode: built for a hidden test set.",
            ),
        ),
    )
    grid_slide(
        s,
        items,
        3,
        1.9,
        6.7,
        "sky",
        (
            "sky",
            "Ready to connect, not connected · جاهز للربط وغير مربوط",
            "Nothing is connected to any police system today, and nothing is sent anywhere without a human approving it.",
        ),
    )
    s.notes = notes(
        "Six ways in and out: a REST API, an MCP server for AI assistants and analyst systems, STIX export, signed webhooks, the evidence pack for an analyst, and a batch tool for a file of URLs. All of it is ready to connect; none of it is connected today, and nothing leaves without a human.",
        "ستّ طرق للربط: واجهة REST، وخادم MCP، وتصدير STIX، وإشعارات موقَّعة، وحزمة الأدلة، وأداة الفحص بالجملة. كلها جاهزة للربط وغير مربوطة اليوم، ولا يخرج شيء دون موافقة إنسان.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "Hidden URL set: give us the file; the batch tool runs it live and prints a results table.",
    )
    return s


def slide_pilot(f: Facts) -> Slide:
    s = new("d_pilot", "Pilot path", "مسار التجربة", "dir", "NEXT · the same stack inside your network", appendix=True)
    s.short_en, s.short_ar = "Pilot path", "مسار التجربة"  # type: ignore[attr-defined]
    steps = (
        ("On-premise install", "The same stack inside the authority's network, on local models."),
        ("Shadow mode", "Verdicts are recorded and compared. Nothing is sent to anyone."),
        ("Analyst review", "Your sign-on, your feeds, your security review, your thresholds."),
        ("Connect", "REST, MCP, STIX and webhooks are switched on, one at a time."),
    )
    s.add(grp("flow", *flow_row(steps, M, 1.95, CW, 1.7, "dir", solid_last=False, gap=0.4)))
    cards = (
        ("What you bring", "A test set, your reporting channels, and an analyst to review the first verdicts."),
        (
            "What we measure in shadow mode",
            "False alarms on your own traffic, checks that could not finish, and the time to a verdict.",
        ),
        (
            "What stays true",
            "A human approves every external action. The lowest verdict is “No warning signs found”, with a caution.",
        ),
    )
    fw = (CW - 0.4) / 3
    for i, (head, body) in enumerate(cards):
        s.add(grp(f"fact_{i}", *fact_card(M + i * (fw + 0.2), 3.95, fw, 1.55, head, body, "dir")))
    s.add(
        grp(
            "footer",
            Box(M, 5.72, CW, 0.98, "sky_tint", "sky_line", "round", 0.14),
            tb(
                M + 0.3,
                5.72,
                CW - 0.6,
                0.98,
                Para([Run("Ready to connect, not connected · جاهز للربط وغير مربوط", 14, "sky", True)], after=2),
                p("An independent project. Nothing is connected today.", 13, "text"),
                anchor="m",
            ),
        )
    )
    s.motion = [
        mo("flow", "wipe_from_left", "auto", 100, 700),
        *stagger([f"fact_{i}" for i in range(3)], "fly_from_bottom", "after", 130, 320),
        mo("footer", "fade", "after", 0, 300),
    ]
    s.notes = notes(
        "A pilot is the same stack inside your network, in shadow mode first: verdicts are recorded and compared, nothing is sent. Then your analysts review it with your sign-on, your feeds and your security review, and only then is anything connected. Ready to connect, not connected.",
        "مسار التجربة: المنظومة نفسها داخل شبكتكم، في وضع المراقبة أولاً: تُسجَّل الأحكام وتُقارَن ولا يُرسَل شيء. ثم مراجعة محلّليكم، وبعدها فقط يبدأ الربط. جاهز للربط وغير مربوط.",
        "Builds by itself. '‹ Index' goes back.",
    )
    return s


def slide_limits(f: Facts) -> Slide:
    s = new(
        "d_limits", "Honest limits", "حدودنا بصراحة", "warn", "LIMITS · said by us, with the numbers", appendix=True
    )
    s.short_en, s.short_ar = "Honest limits", "حدودنا بصراحة"  # type: ignore[attr-defined]
    rows: list[tuple[list[Run], str, str, str]] = []
    second_d = fresh(f, "results_second_source", "phishing_all", "dangerous")
    second_w = fresh(f, "results_second_source", "phishing_all", "warned")
    second_g = fresh(f, "results_second_source", "phishing_all", "degraded")
    if second_d and second_w and second_g:
        rows.append(
            (
                kof(second_d, 30, "warn"),
                "Fresh phishing we had never seen: few reach Dangerous",
                f"On hosts from a feed our stack does not query, {second_w[0]} of {second_w[1]} were warned, but only {second_d[0]} of {second_d[1]} as Dangerous (the rest Suspicious), and {second_g[0]} of {second_g[1]} could not complete every check.",
                src("fresh200"),
            )
        )
    legit_w = fresh(f, "results", "legit_all", "warned")
    legit_d = fresh(f, "results", "legit_all", "dangerous")
    uae = fresh(f, "results", "legit_uae", "warned")
    if legit_w and legit_d:
        extra = f" Of {uae[1]} UAE sites, {uae[0]} was warned." if uae else ""
        rows.append(
            (
                kof(legit_w, 30, "warn"),
                "False alarms on legitimate sites",
                f"{legit_w[0]} of {legit_w[1]} legitimate sites were marked Suspicious, and {legit_d[0]} of {legit_d[1]} Dangerous."
                + extra
                + " Labels are not hand-audited; one run on one day.",
                src("fresh200"),
            )
        )
    if f.fp:
        rows.append(
            (
                [Run(pct(f.fp["false_positive_rate"]["value"]), 30, "warn", True)],
                "An earlier held-out run was worse",
                f"Full stack on {f.fp['n']} held-out legitimate sites: that share was flagged, against a target of {pct(f.fp['target'])}. Most were checks that could not finish. It is our first fix.",
                src("fp_regress"),
            )
        )
    rows.append(
        (
            [Run("Synthetic", 21, "warn", True)],
            "Voice, red-team, message and look-alike sets",
            "They are synthetic or fixtures, so the voice figures are an upper bound. The red-team count is always said with the number of cases the model answered.",
            "",
        )
    )
    rows.append(
        (
            [Run("Not measured", 21, "warn", True)],
            "Two things we have not measured yet",
            "A native reader's rating of the Arabic text, and sandbox recall on labelled phishing pages. Scale is by design and proven on one machine.",
            "",
        )
    )
    n = len(rows)
    gap = 0.12
    rh = (6.7 - 1.9 - gap * (n - 1)) / n
    for i, (runs, head, body, source) in enumerate(rows):
        y = 1.9 + i * (rh + gap)
        shapes = [
            Box(M, y, CW, rh, "warn_tint", "warn_line", "round", 0.14),
            tb(M + 0.3, y, 2.4, rh, Para(runs), anchor="m"),
            tb(
                M + 2.8,
                y + 0.03,
                CW - 3.1,
                rh - 0.06,
                Para([Run(head, 14, "text", True)], after=1),
                Para([Run(body, 12, "muted")] + ([Run("  " + source, 9.5, "faint")] if source else [])),
                anchor="m",
            ),
        ]
        s.add(grp(f"row_{i}", *shapes))
    s.motion = stagger([f"row_{i}" for i in range(n)], "fly_from_bottom", "auto", 140, 320)
    s.notes = notes(
        "Our limits, from us. On fresh phishing from a feed we do not query, every site was warned, but very few reached Dangerous and many could not finish every check: the figures are on the slide. On legitimate sites the fresh run flagged some as Suspicious and none as Dangerous; an earlier held-out run was worse and above our target. Voice, red-team and message sets are synthetic. And two things are not measured yet.",
        "حدودنا نقولها نحن: في مواقع تصيّد جديدة لم نرها من قبل حذّرنا منها كلها، لكن قليلاً منها بلغ «خطِر». وفي المواقع المشروعة ظهرت إنذارات خاطئة بدرجة «مشبوه» ولم يُوصَف أي منها بأنه «خطِر». ومجموعات الصوت والفريق الأحمر مُولَّدة. وهناك أمران لم نقِسهما بعد.",
        "Builds by itself. '‹ Index' goes back.",
        "",
        "UAE-specific recall on live phishing: not measured as its own figure; the fresh run has UAE legitimate sites only. Say 'not measured yet'.",
    )
    return s


# ── assembly ─────────────────────────────────────────────────────────────────
def build_slides(
    f: Facts, root: Path, media: tuple[Path, Path, int] | None, arch: tuple[Path, Path, int] | None = None
) -> tuple[list[Slide], int]:
    main = [
        slide_title(f),
        slide_agenda(f),
        slide_hook(f, media),
        slide_why_voice(f),
        slide_agents(f),
        slide_architecture(f, arch),
        slide_demo(f),
        slide_close(f),
    ]
    bd.criterion_slide = (
        criterion_slide  # the five criterion builders of v1 supply content and figures; v2 lays them out
    )
    appendix = [
        bd.slide_c1(f),
        bd.slide_c2(f),
        bd.slide_c3(f),
        bd.slide_c4(f),
        bd.slide_c5(f),
        slide_baseer(f),
        slide_dir(f),
        slide_voice(f),
        slide_why_langgraph(f),
        slide_why_dspy(f),
        slide_tools(f, root),
        slide_sovereignty(f),
        slide_integration(f),
        slide_pilot(f),
        slide_limits(f),
    ]
    for i, s in enumerate(appendix):
        s.tag = f"A{i + 1}"  # type: ignore[attr-defined]
    index = slide_index(f, appendix)
    slides = [*main, index, *appendix]
    for s in slides:
        chrome(s)
        for sh in walk(s.shapes):
            if isinstance(sh, TextBox):
                for para in sh.paras:
                    para.runs = split_scripts(para.runs)
    return slides, len(main)


def walk(shapes: Sequence[Any]) -> Any:
    for sh in shapes:
        if isinstance(sh, Group):
            yield from walk(sh.shapes)
        else:
            yield sh


def _script(ch: str) -> str | None:
    if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ" or ch in "«»":
        return "ar"
    if ch.isalnum():
        return "la"
    return None


def split_scripts(runs: list[Run]) -> list[Run]:
    """One run per script, so that Latin text gets the Latin face and Arabic text the Arabic face."""
    out: list[Run] = []
    for run in runs:
        seg, kind = "", None
        for ch in run.text:
            k = _script(ch)
            if k and kind and k != kind:
                out.append(Run(seg, run.size, run.color, run.bold))
                seg = ""
            if k:
                kind = k
            seg += ch
        if seg:
            out.append(Run(seg, run.size, run.color, run.bold))
    return out


# ── writers ──────────────────────────────────────────────────────────────────
_set_font = bd.set_font


def set_font(run: Any, name: str, rtl: bool) -> None:
    arabic = any(_script(ch) == "ar" for ch in run.text)
    _set_font(run, ARABIC_FONT if arabic else LATIN_FONT, arabic)


def emit(container: Any, shapes: Sequence[Any], ids: dict[str, int] | None, slide_of: dict[str, Any]) -> None:
    for shape in shapes:
        if isinstance(shape, Group):
            if not shape.shapes:
                continue
            g = container.add_group_shape()
            emit(g.shapes, shape.shapes, None, slide_of)
            g.name = shape.name
            if ids is not None:
                ids[shape.name] = g.shape_id
        elif isinstance(shape, Hot):
            item = container.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(shape.x), Inches(shape.y), Inches(shape.w), Inches(shape.h)
            )
            item.fill.solid()
            item.fill.fore_color.rgb = bd.rgb("bg")
            _alpha(item, 0.01)
            item.line.fill.background()
            item.shadow.inherit = False
            item.name = f"link_{shape.link}"
            item.click_action.target_slide = slide_of[shape.link]
        elif isinstance(shape, Movie):
            bd.emit_shapes(container, [shape], ids)
        else:
            bd.emit_shapes(container, [shape], None)
            if isinstance(shape, XBox) and (shape.alpha is not None or shape.grad):
                item = list(container)[-1]
                if shape.grad:
                    item.fill.gradient()
                    item.fill.gradient_angle = 90
                    stops = item.fill.gradient_stops
                    stops[0].color.rgb = bd.rgb(shape.grad)
                    stops[0].position = 0
                    stops[1].color.rgb = bd.rgb(shape.fill or "bg")
                    stops[1].position = 1
                else:
                    _alpha(item, shape.alpha or 0)


def _alpha(item: Any, alpha: float) -> None:
    clr = item.fill._xPr.find(qn("a:solidFill"))[0]
    clr.append(clr.makeelement(qn("a:alpha"), {"val": str(round(alpha * 100000))}))


def write_pptx(slides: list[Slide], out: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    prs.core_properties.title = "Falcon Lens | عدسة الصقر"
    prs.core_properties.author = "Falcon Lens team"
    prs.core_properties.subject = "ScamShield AI pitch, v2"
    blank = next(layout for layout in prs.slide_layouts if layout.name == "Blank")
    made = [prs.slides.add_slide(blank) for _ in slides]
    slide_of = {sl.key: slide for sl, slide in zip(slides, made, strict=True)}
    for sl, slide in zip(slides, made, strict=True):
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = bd.rgb("bg")
        ids: dict[str, int] = {}
        emit(slide.shapes, sl.shapes, ids, slide_of)
        slide.notes_slide.notes_text_frame.text = sl.notes
        steps = []
        for m in sl.motion:
            if m.target not in ids:
                raise KeyError(f"slide {sl.key}: motion target {m.target!r} is not a top-level group")
            steps.append(
                deck_motion.Step(ids[m.target], m.effect, "after" if m.trigger == "auto" else m.trigger, m.delay, m.dur)
            )
        kind, ms = sl.transition if sl.transition else (None, 0)
        movie = next((sh for sh in sl.shapes if isinstance(sh, Movie)), None)
        media = (ids["hook_video"], movie.ms, movie.auto) if movie else None
        deck_motion.apply_motion(slide, steps, kind, ms, media)
    for layout in list(prs.slide_layouts):
        if layout.name != "Blank":
            prs.slide_layouts.remove(layout)
    out.parent.mkdir(parents=True, exist_ok=True)
    bd.register_notes_master(prs)
    prs.save(str(out))


_html_shape = bd.html_shape
NUMBER_OF: dict[str, int] = {}


def html_shape(sh: Any, parts: list[str]) -> None:
    if isinstance(sh, Group):
        for child in sh.shapes:
            html_shape(child, parts)
    elif isinstance(sh, Hot):
        parts.append(
            f'<a class="hot" data-go="{NUMBER_OF.get(sh.link, 1)}" aria-label="Go to {html.escape(sh.link)}" style="left:{sh.x}in;top:{sh.y}in;width:{sh.w}in;height:{sh.h}in;cursor:pointer;z-index:3"></a>'
        )
    elif isinstance(sh, XBox) and (sh.alpha is not None or sh.grad):
        geo = f"left:{sh.x}in;top:{sh.y}in;width:{sh.w}in;height:{sh.h}in;"
        radius = "50%" if sh.shape == "oval" else (f"{sh.radius}in" if sh.shape == "round" else "0")
        border = f"border:{sh.line_w}pt {'dashed' if sh.dash else 'solid'} {bd.hx(sh.line)};" if sh.line else ""
        if sh.grad:
            fill = f"background:linear-gradient(180deg,{bd.hx(sh.fill or 'bg')},{bd.hx(sh.grad)});"
        else:
            c = bd.C[sh.fill or "bg"]
            fill = f"background:rgba({int(c[0:2], 16)},{int(c[2:4], 16)},{int(c[4:6], 16)},{sh.alpha});"
        parts.append(f'<div style="{geo}{fill}{border}border-radius:{radius}"></div>')
    else:
        _html_shape(sh, parts)


LINK_JS = """
document.addEventListener('click', e => {
  const a = e.target.closest('[data-go]');
  if (!a) return;
  e.stopPropagation(); e.preventDefault();
  for (const ch of String(a.dataset.go)) dispatchEvent(new KeyboardEvent('keydown', { key: ch }));
  dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
}, true);
"""


def same_fonts(page: str) -> str:
    """The HTML uses the faces Keynote uses (both ship with macOS); the embedded Readex Pro is the fallback elsewhere."""
    return page.replace(
        f'font-family:"{bd.FONT}",Arial,sans-serif',
        f'font-family:"{LATIN_FONT}","{ARABIC_FONT}","{bd.FONT}",Arial,sans-serif',
    )


def check_motion(pptx: Path, slides: list[Slide]) -> list[str]:
    problems = []
    for i, (row, sl) in enumerate(zip(deck_motion.motion_report(pptx), slides, strict=True)):
        problems += [f"slide {i + 1} ({sl.key}): {item}" for item in row["problems"]]
        if row["transitions"] != 1:
            problems.append(f"slide {i + 1} ({sl.key}): expected one transition, found {row['transitions']}")
        clicks = sum(1 for m in sl.motion if m.trigger == "click")
        if row["click_beats"] != clicks and not any(isinstance(sh, Movie) for sh in sl.shapes):
            problems.append(f"slide {i + 1} ({sl.key}): {row['click_beats']} click beats, expected {clicks}")
        if clicks > 1:
            problems.append(f"slide {i + 1} ({sl.key}): more than one click beat")
    return problems


def probe_video(
    video: Path, cache: Path, stem: str = "hook", scale: str = "720:-2", poster: Path | None = None
) -> tuple[Path, Path, int]:
    """(video for the deck, poster PNG, length in ms) through ffmpeg and ffprobe.

    The deck carries a 720 by 1280 H.264 main-profile copy: Keynote did not open the .pptx with the owner's 24 MB
    original embedded, and opened it with this copy (checked on Keynote 16). The HTML deck plays the original.
    """
    cache.mkdir(parents=True, exist_ok=True)
    small, still = cache / f"{stem}_small.mp4", cache / f"{stem}_poster.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            "scale=720:-2",
            "-c:v",
            "libx264",
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "22",
            "-preset",
            "fast",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(small),
        ],
        check=True,
    )
    if poster and poster.is_file():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(poster), str(still)], check=True)
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(small), "-frames:v", "1", str(still)],
            check=True,
        )
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(small)],
        check=True,
        capture_output=True,
        text=True,
    )
    return small, still, round(float(out.stdout.strip()) * 1000)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument(
        "--out-dir", type=Path, required=True, help="where the .pptx, the QA .pdf and the .html are written"
    )
    ap.add_argument(
        "--qa-dir",
        type=Path,
        default=None,
        help="also write one PNG per slide here (Chromium render) and report overflow",
    )
    ap.add_argument(
        "--hook-video",
        type=Path,
        default=None,
        help="an .mp4 for the hook slide (never committed); embedded when the file exists",
    )
    ap.add_argument(
        "--arch-video",
        type=Path,
        default=None,
        help="the rendered animated architecture (.mp4); when the file exists it replaces the native diagram",
    )
    ap.add_argument("--arch-poster", type=Path, default=None, help="final-frame PNG for --arch-video")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    bd.set_font = set_font
    bd.html_shape = html_shape
    bd.PPTX_FONT = LATIN_FONT
    media = probe_video(args.hook_video.resolve(), bd.CACHE) if args.hook_video and args.hook_video.is_file() else None
    arch = (
        probe_video(args.arch_video.resolve(), bd.CACHE, "arch", "1280:-2", args.arch_poster)
        if args.arch_video and args.arch_video.is_file()
        else None
    )
    prepare_logos(root, bd.CACHE)
    facts = bd.gather(root)
    slides, n_main = build_slides(facts, root, media, arch)
    NUMBER_OF.update({sl.key: i + 1 for i, sl in enumerate(slides)})
    out_pptx = args.out_dir / f"{NAME}.pptx"
    qa_pdf = args.out_dir / f"{NAME}.chromium.pdf"
    out_html = args.out_dir / f"{NAME}.html"
    write_pptx(slides, out_pptx)
    bd.CACHE.mkdir(parents=True, exist_ok=True)
    html_path = bd.CACHE / "deck_v2.html"
    bd.write_html(slides, html_path, root)
    html_path.write_text(same_fonts(html_path.read_text(encoding="utf-8")), encoding="utf-8")
    problems = [
        x for x in bd.render_pdf_and_qa(html_path, qa_pdf, args.qa_dir) if "Readex Pro did not load" not in x
    ]  # the fallback face is unused on macOS
    problems += bd.verify_pptx(out_pptx, len(slides), strict_motion=False, video="auto" if media or arch else None)
    problems += check_motion(out_pptx, slides)
    deck_present.write(bd, slides, out_html, root)
    page = same_fonts(out_html.read_text(encoding="utf-8")).replace("</body>", f"<script>{LINK_JS}</script></body>")
    out_html.write_text(page, encoding="utf-8")
    problems += bd.check_text(out_pptx, facts.artifact, root / "evals" / "results" / "published")
    links = sum(1 for sl in slides for sh in walk(sl.shapes) if isinstance(sh, Hot))
    print(f"slides: {len(slides)} (main path {n_main}, index 1, appendix {len(slides) - n_main - 1}); links: {links}")
    for i, sl in enumerate(slides):
        print(
            f"  {i + 1:>2} {getattr(sl, 'tag', '') or 'main':<5} {sl.key:<14} builds {len(sl.motion):>2} clicks {sum(1 for m in sl.motion if m.trigger == 'click')}"
        )
    for path in (out_pptx, out_html):
        print(f"{path}: {path.stat().st_size / 1024:.0f} KB")
    for item in problems:
        print(f"ERROR: {item}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
