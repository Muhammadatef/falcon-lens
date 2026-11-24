# ruff: noqa: E501  (XML templates read better unwrapped)
"""Slide transitions and entrance animations for the pitch deck (python-pptx 1.0.x + lxml).

Implements Appendix A of DECK_DESIGN.md: one `p:timing` tree per slide (entrance effects only: fade, wipe, zoom),
and a `p:transition` wrapped in `mc:AlternateContent` the way PowerPoint writes it. `motion_report()` reads a saved
.pptx back and checks the acceptance rules of section 5 (counts, schema order, ids, durations).

Playback in PowerPoint and import into Keynote are not verified by this module: it checks structure only.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS_P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"

# name: (presetID, presetSubtype, animEffect filter or None)
EFFECTS: dict[str, tuple[int, int, str | None]] = {
    "fade": (10, 0, "fade"),
    "wipe_from_left": (22, 8, "wipe(left)"),
    "wipe_from_right": (22, 2, "wipe(right)"),
    "wipe_from_top": (22, 1, "wipe(up)"),
    "wipe_from_bottom": (22, 4, "wipe(down)"),
    "zoom": (53, 16, "fade"),
    "fly_from_bottom": (2, 4, None),
    "fly_from_left": (2, 8, None),
    "fly_from_right": (2, 2, None),
}
# Keynote 16 import, checked by opening a probe deck and reading the saved .key: Fade -> Dissolve, Wipe -> Wipe,
# Zoom -> Scale, Fly In -> Move In; transitions fade -> Dissolve, push -> Push, cover -> Move In, wipe -> Wipe.
FLY = {
    "fly_from_bottom": ("#ppt_x", "1+#ppt_h/2"),
    "fly_from_left": ("0-#ppt_w/2", "#ppt_y"),
    "fly_from_right": ("1+#ppt_w/2", "#ppt_y"),
}
TRANSITIONS = {
    "fade": "<p:fade/>",
    "push_left": '<p:push dir="l"/>',
    "cover_left": '<p:cover dir="l"/>',
    "wipe_left": '<p:wipe dir="l"/>',
    "cut": "<p:cut/>",
}
MAX_EFFECT_MS = 1200


@dataclass
class Step:
    spid: int
    effect: str = "fade"
    trigger: str = "after"  # click | after | with
    delay: int = 0  # ms, relative to the trigger
    dur: int = 500  # ms


def transition_xml(kind: str = "fade", dur_ms: int = 600) -> str:
    inner = TRANSITIONS[kind]
    return (
        f'<mc:AlternateContent xmlns:mc="{NS_MC}" xmlns:p="{NS_P}">'
        f'<mc:Choice xmlns:p14="{NS_P14}" Requires="p14"><p:transition spd="med" p14:dur="{dur_ms}">{inner}</p:transition></mc:Choice>'
        f'<mc:Fallback><p:transition spd="med">{inner}</p:transition></mc:Fallback>'
        f"</mc:AlternateContent>"
    )


def _effect(step: Step, node_type: str, ids: Any) -> str:
    if step.dur > MAX_EFFECT_MS:
        raise ValueError(f"effect longer than {MAX_EFFECT_MS} ms")
    preset, subtype, filt = EFFECTS[step.effect]
    tgt = f'<p:tgtEl><p:spTgt spid="{step.spid}"/></p:tgtEl>'
    kids = (
        f'<p:set><p:cBhvr><p:cTn id="{next(ids)}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f"{tgt}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
        f'<p:to><p:strVal val="visible"/></p:to></p:set>'
    )

    def anim(attr: str, start: str, end: str) -> str:
        return (
            f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{next(ids)}" dur="{step.dur}" fill="hold"/>'
            f"{tgt}<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr>"
            f'<p:tavLst><p:tav tm="0"><p:val><p:strVal val="{start}"/></p:val></p:tav>'
            f'<p:tav tm="100000"><p:val><p:strVal val="{end}"/></p:val></p:tav></p:tavLst></p:anim>'
        )

    if step.effect == "zoom":
        kids += anim("ppt_w", "0", "#ppt_w") + anim("ppt_h", "0", "#ppt_h")
    if step.effect in FLY:
        x0, y0 = FLY[step.effect]
        kids += anim("ppt_x", x0, "#ppt_x") + anim("ppt_y", y0, "#ppt_y")
    if filt:
        kids += f'<p:animEffect transition="in" filter="{filt}"><p:cBhvr><p:cTn id="{next(ids)}" dur="{step.dur}"/>{tgt}</p:cBhvr></p:animEffect>'
    return (
        f'<p:par><p:cTn id="{next(ids)}" presetID="{preset}" presetClass="entr" presetSubtype="{subtype}" fill="hold" grpId="0" nodeType="{node_type}">'
        f'<p:stCondLst><p:cond delay="{step.delay}"/></p:stCondLst><p:childTnLst>{kids}</p:childTnLst></p:cTn></p:par>'
    )


def timing_xml(steps: list[Step], text_spids: set[int]) -> str:
    """Steps in play order. 'click' opens a beat; 'after' chains; 'with' runs alongside the previous step.

    A first step that is not a click is an automatic beat: it starts when the slide appears.
    """
    ids = iter(range(3, 100000))
    beats: list[list[list[Step]]] = []  # beat -> slots -> steps
    for st in steps:
        if st.trigger == "click" or not beats:
            beats.append([[st]])
        elif st.trigger == "after":
            beats[-1].append([st])
        else:
            beats[-1][-1].append(st)
    out = ""
    for beat in beats:
        auto = beat[0][0].trigger != "click"
        offset, slots = 0, ""
        for slot in beat:
            body = ""
            for i, st in enumerate(slot):
                node = ("afterEffect" if auto or slot is not beat[0] else "clickEffect") if i == 0 else "withEffect"
                body += _effect(st, node, ids)
            slots += f'<p:par><p:cTn id="{next(ids)}" fill="hold"><p:stCondLst><p:cond delay="{offset}"/></p:stCondLst><p:childTnLst>{body}</p:childTnLst></p:cTn></p:par>'
            offset += max(s.delay + s.dur for s in slot)
        begin = '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>' if auto else ""
        out += f'<p:par><p:cTn id="{next(ids)}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>{begin}</p:stCondLst><p:childTnLst>{slots}</p:childTnLst></p:cTn></p:par>'
    bld = "".join(
        f'<p:bldP spid="{s}" grpId="0" animBg="1"/>' for s in dict.fromkeys(st.spid for st in steps) if s in text_spids
    )
    counter = iter(range(3, 100000))
    out = re.sub(r'<p:cTn id="\d+"', lambda m: f'<p:cTn id="{next(counter)}"', out)  # ids in document order
    return (
        f'<p:timing xmlns:p="{NS_P}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>{out}</p:childTnLst></p:cTn>'
        f'<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        f'<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
        f"</p:childTnLst></p:cTn></p:par></p:tnLst>" + (f"<p:bldLst>{bld}</p:bldLst>" if bld else "") + "</p:timing>"
    )


def media_timing_xml(spid: int, dur_ms: int, auto: bool) -> str:
    """Timing for one video: a play command (on click, or by itself when the slide opens) plus the media node.

    This is the tree PowerPoint writes for "Start: On Click" / "Automatically".
    """
    begin = '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>' if auto else ""
    node = "afterEffect" if auto else "clickEffect"
    tgt = f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
    return (
        f'<p:timing xmlns:p="{NS_P}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        f'<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>{begin}</p:stCondLst><p:childTnLst>'
        f'<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'<p:par><p:cTn id="5" presetID="1" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="{node}">'
        f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="{dur_ms}" fill="hold"/>{tgt}</p:cBhvr></p:cmd>'
        f"</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>"
        f"</p:childTnLst></p:cTn>"
        f'<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        f'<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
        f'<p:video><p:cMediaNode vol="80000"><p:cTn id="7" fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn>'
        f"{tgt}</p:cMediaNode></p:video>"
        f"</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
    )


def apply_motion(
    slide: Any,
    steps: list[Step],
    transition: str | None,
    dur_ms: int = 600,
    media: tuple[int, int, bool] | None = None,
) -> None:
    """Call after every shape is on the slide. Schema order in p:sld: cSld, clrMapOvr, transition, timing, extLst.

    `media` is (shape id, duration in ms, start automatically) for a slide that carries one video and no builds.
    """
    sld = slide._element
    for old in [
        c for c in sld if c.tag in (f"{{{NS_P}}}transition", f"{{{NS_P}}}timing", f"{{{NS_MC}}}AlternateContent")
    ]:
        sld.remove(old)
    ext = sld.find(f"{{{NS_P}}}extLst")
    parts = []
    if transition:
        parts.append(etree.fromstring(transition_xml(transition, dur_ms)))
    if media:
        parts.append(etree.fromstring(media_timing_xml(*media)))
    elif steps:
        text_spids = {sp.shape_id for sp in slide.shapes if getattr(sp, "has_text_frame", False)}
        parts.append(etree.fromstring(timing_xml(steps, text_spids)))
    for el in parts:
        if ext is not None:
            ext.addprevious(el)
        else:
            sld.append(el)


# ── read-back checks (section 5 of DECK_DESIGN.md) ───────────────────────────────────────────────
def _natural(name: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def motion_report(pptx: Path) -> list[dict[str, Any]]:
    """One dict per slide: transition count, entrance count, click beats, problems."""
    out: list[dict[str, Any]] = []
    ns = {"p": NS_P, "mc": NS_MC}
    order = {"cSld": 0, "clrMapOvr": 1, "AlternateContent": 2, "transition": 2, "timing": 3, "extLst": 4}
    with zipfile.ZipFile(pptx) as zf:
        names = sorted((n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_natural)
        for name in names:
            root = etree.fromstring(zf.read(name))
            problems: list[str] = []
            kids = [etree.QName(c).localname for c in root]
            if [order[k] for k in kids] != sorted(order[k] for k in kids):
                problems.append(f"child order {kids}")
            transitions = root.xpath("/p:sld/mc:AlternateContent | /p:sld/p:transition", namespaces=ns)
            if root.xpath("//p:transition[@advTm]", namespaces=ns):
                problems.append("advTm (automatic advance)")
            entr = root.xpath("//p:cTn[@presetClass='entr']", namespaces=ns)
            if root.xpath(
                "//p:cTn[@presetClass and @presetClass!='entr' and @presetClass!='mediacall']", namespaces=ns
            ):
                problems.append("non-entrance effect")
            if root.xpath("//*[@repeatCount or @autoRev]"):
                problems.append("repeatCount or autoRev")
            durs = [
                int(d)
                for d in root.xpath(
                    "//p:timing//p:cTn[@dur != 'indefinite' and not(parent::p:cBhvr/parent::p:cmd)]/@dur", namespaces=ns
                )
            ]
            if durs and max(durs) > MAX_EFFECT_MS:
                problems.append(f"effect longer than {MAX_EFFECT_MS} ms")
            ctn_ids = root.xpath("//p:cTn/@id", namespaces=ns)
            if len(ctn_ids) != len(set(ctn_ids)):
                problems.append("duplicate cTn ids")
            shape_ids = {int(i) for i in root.xpath("//p:cNvPr/@id", namespaces=ns)}
            bad = [t for t in root.xpath("//p:spTgt/@spid", namespaces=ns) if int(t) not in shape_ids]
            if bad:
                problems.append(f"spTgt without a shape: {bad}")
            text_ids = {int(i) for i in root.xpath("//p:sp[p:txBody]/p:nvSpPr/p:cNvPr/@id", namespaces=ns)}
            built = {int(i) for i in root.xpath("//p:bldP/@spid", namespaces=ns)}
            targets = {int(t) for t in root.xpath("//p:spTgt/@spid", namespaces=ns)}
            if (targets & text_ids) - built:
                problems.append("animated text shape without bldP")
            clicks = root.xpath(
                "//p:cTn[p:stCondLst/p:cond[@delay='indefinite'] and not(p:stCondLst/p:cond[@evt='onBegin'])"
                " and not(@nodeType) and not(parent::p:cMediaNode)]",
                namespaces=ns,
            )
            out.append(
                {
                    "part": name,
                    "transitions": len(transitions),
                    "entrance": len(entr),
                    "click_beats": len(clicks),
                    "problems": problems,
                }
            )
    return out


def parse_all_parts(pptx: Path) -> list[str]:
    """Every .xml and .rels part must parse."""
    bad: list[str] = []
    with zipfile.ZipFile(pptx) as zf:
        for name in zf.namelist():
            if name.endswith((".xml", ".rels")):
                try:
                    etree.fromstring(zf.read(name))
                except etree.XMLSyntaxError as exc:
                    bad.append(f"{name}: {exc}")
    return bad
