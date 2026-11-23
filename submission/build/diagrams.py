# ruff: noqa: E501
"""Simple print-friendly flow diagrams for the description document, generated as SVG then rendered to PNG.

Colour key (matches the README diagrams): teal = fixed code, blue = AI model, amber = a human gate.
No numbers appear in these pictures, so nothing needs tracing.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from common import WORK, svg_to_png

COLORS = {
    "code": ("#e3f4f2", "#0b6e69"),
    "ai": ("#e4edfb", "#2457a6"),
    "human": ("#fdf0d5", "#9a6700"),
    "data": ("#eef1f4", "#51606e"),
}
LEGEND = [("code", "Fixed code (no AI)"), ("ai", "AI model"), ("human", "A person decides"), ("data", "Data or input")]


@dataclass(frozen=True)
class Step:
    title: str
    lines: tuple[str, ...]
    kind: str = "code"


def flow_svg(steps: list[Step], per_row: int, width: int = 1100, box_h: int = 132) -> str:
    gap = 46
    margin = 20
    box_w = (width - 2 * margin - gap * (per_row - 1)) // per_row
    rows = (len(steps) + per_row - 1) // per_row
    row_gap = 46
    height = margin * 2 + rows * box_h + (rows - 1) * row_gap + 50
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" font-family="Helvetica, Arial, sans-serif">',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0L10 5L0 10z" fill="#51606e"/></marker></defs>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    pos: list[tuple[int, int]] = []
    for i, step in enumerate(steps):
        r, c = divmod(i, per_row)
        x = margin + c * (box_w + gap)
        y = margin + r * (box_h + row_gap)
        pos.append((x, y))
        fill, stroke = COLORS[step.kind]
        out.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        out.append(
            f'<circle cx="{x + 22}" cy="{y + 24}" r="13" fill="{stroke}"/><text x="{x + 22}" y="{y + 29}" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">{i + 1}</text>'
        )
        out.append(
            f'<text x="{x + 44}" y="{y + 29}" font-size="17" font-weight="700" fill="#14202b">{html.escape(step.title)}</text>'
        )
        for j, line in enumerate(step.lines):
            out.append(
                f'<text x="{x + 16}" y="{y + 58 + j * 20}" font-size="14" fill="#2b3a47">{html.escape(line)}</text>'
            )
    for i in range(len(steps) - 1):
        (x1, y1), (x2, y2) = pos[i], pos[i + 1]
        if y1 == y2:
            out.append(
                f'<line x1="{x1 + box_w + 4}" y1="{y1 + box_h / 2}" x2="{x2 - 4}" y2="{y2 + box_h / 2}" stroke="#51606e" stroke-width="2.5" marker-end="url(#a)"/>'
            )
        else:  # wrap to the next row: elbow below the first row back to the left
            ymid = y1 + box_h + row_gap / 2
            out.append(
                f'<path d="M{x1 + box_w / 2} {y1 + box_h + 2} V{ymid} H{x2 + box_w / 2} V{y2 - 4}" fill="none" stroke="#51606e" stroke-width="2.5" marker-end="url(#a)"/>'
            )
    lx = margin
    ly = height - 28
    for kind, label in LEGEND:
        fill, stroke = COLORS[kind]
        out.append(
            f'<rect x="{lx}" y="{ly - 12}" width="18" height="18" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="2"/><text x="{lx + 26}" y="{ly + 2}" font-size="13" fill="#2b3a47">{html.escape(label)}</text>'
        )
        lx += 34 + 8 * len(label) + 28
    out.append("</svg>")
    return "\n".join(out)


CHECK = [
    Step("Something to check", ("A link, a message,", "an email or a picture", "arrives (nothing personal)."), "data"),
    Step("T0  Memory and lists", ("Seen before? On a known", "bad list? A verified", "official site?"), "code"),
    Step("T1  The address", ("Look-alike tricks, domain", "age, plus a small", "trained classifier."), "code"),
    Step("T2  Sealed browser", ("Open the page once,", "passively. Does it claim a", "brand it does not own?"), "code"),
    Step("T3  AI Investigator", ("Only for unclear cases:", "a few checked look-ups", "to collect more facts."), "ai"),
    Step(
        "Arbiter and verdict", ("Fixed code sets the score.", "Reasons cite evidence.", "Arabic and English."), "code"
    ),
]

INVESTIGATOR = [
    Step("Input arrives", ("Facts so far come from", "the earlier layers as", "structured evidence."), "data"),
    Step(
        "Reader in a closed room",
        ("Page text is read by a", "model with no tools and", "a strict answer format."),
        "ai",
    ),
    Step("Plan", ("The model picks one", "approved look-up as a", "short structured request."), "ai"),
    Step("Check the request", ("Code checks the tool and", "that the address came from", "the case itself."), "code"),
    Step("Act and observe", ("The look-up runs; its", "result is added as new", "evidence."), "code"),
    Step("Decide", ("Stop when enough is known", "or the budget is used.", "Repeat only within limits."), "ai"),
    Step("Arbiter scores", ("Fixed code sets the score", "and the verdict. The model", "cannot change it."), "code"),
]

SENTINEL = [
    Step("Listen", ("Every finished check is", "published as an event on", "a message stream."), "code"),
    Step("Correlate", ("Plain code groups similar", "checks: same page kit, brand,", "domain pattern, time."), "code"),
    Step("Rules open an incident", ("Written, unit-tested rules", "decide what is a campaign.", "No AI here."), "code"),
    Step(
        "Triage (LangGraph)",
        ("Enrich, compare, assess,", "summarise, propose: an AI", "adds a bilingual summary."),
        "ai",
    ),
    Step(
        "Internal actions", ("Block a known-bad link", "inside our own system, with", "an expiry and an undo."), "code"
    ),
    Step(
        "Draft external actions", ("Takedown or police-report", "drafts are written, then", "the graph pauses."), "ai"
    ),
    Step("Human approves", ("An operator approves or", "rejects. Every action is", "kept in an audit log."), "human"),
]


def build_all() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, steps, per_row in (
        ("check-layers", CHECK, 3),
        ("investigator-simple", INVESTIGATOR, 4),
        ("sentinel-simple", SENTINEL, 4),
    ):
        svg = WORK / f"{name}.svg"
        svg.parent.mkdir(parents=True, exist_ok=True)
        svg.write_text(flow_svg(steps, per_row), encoding="utf-8")
        out[name] = svg_to_png(svg, WORK / f"{name}.png", scale=2.0)
    return out
