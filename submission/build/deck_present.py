# ruff: noqa: E501  (CSS and JS templates read better unwrapped)
"""A self-contained animated HTML version of the pitch deck (the guaranteed fallback for the stage).

One file: fonts and pictures are inlined, there is no network request. The slides, groups and motion steps are the
same objects `build_deck.py` writes into the .pptx, so the two cannot drift. Keys: Right, Space, Page Down, Enter or a
click go on one beat; Left or Page Up go back; Home and End jump; F toggles full screen; a slide number then Enter
jumps. With `prefers-reduced-motion` every build appears at once on its beat and slides cut.

The hook video is not inlined: when the deck is built with one, the page plays `media/hook.mp4` next to itself.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

VIDEO_REL = "media/hook.mp4"

KEYFRAMES = """
@keyframes fade{from{opacity:0}}
@keyframes zoom{from{opacity:0;transform:scale(.55)}}
@keyframes fly_from_left{from{opacity:0;transform:translateX(-1.1in)}}
@keyframes fly_from_right{from{opacity:0;transform:translateX(1.1in)}}
@keyframes fly_from_bottom{from{opacity:0;transform:translateY(.8in)}}
@keyframes wipe_from_left{from{clip-path:inset(0 calc(100% - var(--l)) 0 0)}to{clip-path:inset(0 calc(100% - var(--r)) 0 0)}}
@keyframes wipe_from_right{from{clip-path:inset(0 0 0 var(--r))}to{clip-path:inset(0 0 0 var(--l))}}
@keyframes wipe_from_top{from{clip-path:inset(0 0 calc(100% - var(--t)) 0)}to{clip-path:inset(0 0 calc(100% - var(--b)) 0)}}
@keyframes wipe_from_bottom{from{clip-path:inset(var(--b) 0 0 0)}to{clip-path:inset(var(--t) 0 0 0)}}
"""

PLAYER = r"""
(() => {
  const M = JSON.parse(document.getElementById('motion').textContent);
  const S = [...document.querySelectorAll('.slide')];
  const stage = document.getElementById('stage'), bar = document.getElementById('bar'), hint = document.getElementById('hint');
  const calm = matchMedia('(prefers-reduced-motion: reduce)');
  let cur = 0, beat = 0, timers = [], typed = '';
  const fit = () => { stage.style.transform = `translate(-50%,-50%) scale(${Math.min(innerWidth / stage.offsetWidth, innerHeight / stage.offsetHeight)})`; };
  const group = (i, n) => S[i].querySelector(`.g[data-n="${n}"]`);
  const video = i => S[i].querySelector('video');
  const stop = () => { timers.forEach(clearTimeout); timers = []; };
  const settle = i => S[i].querySelectorAll('.g').forEach(el => { el.classList.remove('pre'); el.style.animation = ''; });
  const arm = i => M[i].beats.forEach(b => b.items.forEach(it => { const el = group(i, it.n); el.style.animation = ''; el.classList.add('pre'); }));
  const play = (i, b) => M[i].beats[b].items.forEach(it => {
    const el = group(i, it.n);
    const run = () => {
      el.classList.remove('pre');
      if (calm.matches) return;
      el.style.animation = `${it.fx} ${it.dur}ms cubic-bezier(.2,.75,.25,1) both`;
      el.addEventListener('animationend', () => { el.style.animation = ''; }, { once: true });
    };
    if (calm.matches || it.at === 0) run(); else timers.push(setTimeout(run, it.at));
  });
  const go = (i, finished) => {
    i = Math.max(0, Math.min(S.length - 1, i));
    stop(); settle(cur);
    const old = video(cur); if (old) old.pause();
    cur = i;
    S.forEach((s, j) => { s.classList.toggle('cur', j === i); s.classList.toggle('before', j < i); s.classList.toggle('after', j > i); });
    bar.style.width = `${(100 * (i + 1)) / S.length}%`;
    beat = M[i].beats.length;
    if (!finished) {
      arm(i); beat = 0;
      if (M[i].beats.length && M[i].beats[0].auto) { const first = beat++; timers.push(setTimeout(() => play(i, first), calm.matches ? 0 : 450)); }
      const v = video(i);
      if (v) { v.currentTime = 0; if (M[i].autoplay) v.play().catch(() => {}); }
    }
    history.replaceState(null, '', `#${i + 1}`);
  };
  const next = () => {
    const v = video(cur);
    if (v && v.paused && !v.ended && v.currentTime < 0.2) { v.play().catch(() => {}); return; }
    if (beat < M[cur].beats.length) { play(cur, beat++); return; }
    if (cur < S.length - 1) go(cur + 1, false);
  };
  const prev = () => { if (cur > 0) go(cur - 1, true); };
  addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Spacebar', 'Enter'].includes(k)) {
      e.preventDefault();
      if (k === 'Enter' && typed) { go(parseInt(typed, 10) - 1, false); typed = ''; } else next();
    } else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(k)) { e.preventDefault(); typed = ''; prev(); }
    else if (k === 'Home') go(0, false);
    else if (k === 'End') go(S.length - 1, false);
    else if (k === 'f' || k === 'F') { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => {}); }
    else if (/^[0-9]$/.test(k)) typed = (typed + k).slice(-2);
    hint.classList.add('gone');
  });
  addEventListener('click', e => { if (e.target.closest('video') && !video(cur).paused) return; hint.classList.add('gone'); next(); });
  addEventListener('resize', fit);
  let idle; addEventListener('mousemove', () => { document.body.classList.remove('idle'); clearTimeout(idle); idle = setTimeout(() => document.body.classList.add('idle'), 2500); });
  fit();
  const start = parseInt(location.hash.slice(1), 10);
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(() => { fit(); go(Number.isFinite(start) ? start - 1 : 0, false); setTimeout(() => hint.classList.add('gone'), 6000); });
})();
"""


def _data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _bbox(bd: Any, shape: Any) -> tuple[float, float, float, float]:
    if isinstance(shape, bd.Group):
        boxes = [_bbox(bd, child) for child in shape.shapes]
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    return (shape.x, shape.y, shape.x + shape.w, shape.y + shape.h)


def beats(motion: list[Any]) -> list[dict[str, Any]]:
    """The same grouping as deck_motion.timing_xml: click opens a beat, after chains, with runs alongside."""
    out: list[dict[str, Any]] = []
    slots: list[list[list[Any]]] = []
    for m in motion:
        if m.trigger == "click" or not slots:
            slots.append([[m]])
            out.append({"auto": m.trigger != "click", "items": []})
        elif m.trigger in ("after", "auto"):
            slots[-1].append([m])
        else:
            slots[-1][-1].append(m)
    for beat, beat_slots in zip(out, slots, strict=True):
        offset = 0
        for slot in beat_slots:
            for m in slot:
                beat["items"].append({"n": m.target, "fx": m.effect, "at": offset + m.delay, "dur": m.dur})
            offset += max(m.delay + m.dur for m in slot)
    return out


def write(bd: Any, slides: list[Any], out: Path, root: Path) -> None:
    """`bd` is the running build_deck module (passed in so that its classes are the ones the slides were built with)."""
    faces = "".join(
        f'@font-face{{font-family:"{bd.FONT}";src:url("{_data_uri(root / rel, "font/woff2")}") format("woff2");font-weight:100 900;unicode-range:{rng};}}\n'
        for rel, rng in bd.FONT_FILES.values()
    )
    css = (
        faces
        + f"""*{{box-sizing:border-box}}html,body{{margin:0;height:100%;background:#000;overflow:hidden}}
body.idle{{cursor:none}}
#stage{{position:fixed;left:50%;top:50%;width:{bd.W}in;height:{bd.H}in;transform-origin:center;background:{bd.hx("bg")};overflow:hidden}}
.slide{{position:absolute;inset:0;background:{bd.hx("bg")};overflow:hidden;font-family:"{bd.FONT}",Arial,sans-serif;opacity:0;visibility:hidden;transition:opacity .55s ease,transform .7s cubic-bezier(.2,.75,.25,1),visibility 0s .7s}}
.slide.after{{transform:translateX(9%)}}.slide.before{{transform:translateX(-9%)}}
.slide.cur{{opacity:1;visibility:visible;transform:none;transition:opacity .55s ease,transform .7s cubic-bezier(.2,.75,.25,1),visibility 0s}}
.slide>*,.g>*{{position:absolute}}
.g{{inset:0;transform-origin:var(--cx) var(--cy);will-change:transform,opacity}}
.g.pre{{opacity:0}}
.t{{display:flex;flex-direction:column;overflow:visible}}
.t p{{margin:0;white-space:normal;overflow-wrap:break-word}}
video{{object-fit:contain;background:#000}}
#bar{{position:fixed;left:0;bottom:0;height:3px;width:0;background:{bd.hx("brand")};transition:width .4s ease;z-index:5}}
#hint{{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);font:14px/1.4 Arial,sans-serif;color:{bd.hx("muted")};background:rgba(14,22,38,.9);border:1px solid {bd.hx("border")};border-radius:999px;padding:6px 16px;transition:opacity .6s;z-index:6}}
#hint.gone{{opacity:0;pointer-events:none}}
{KEYFRAMES}
@media (prefers-reduced-motion: reduce){{.slide,.slide.cur{{transition:none;transform:none}}#bar{{transition:none}}}}
@media print{{html,body{{overflow:visible;height:auto}}#stage{{position:static;transform:none!important}}.slide{{position:relative;opacity:1;visibility:visible;transform:none;width:{bd.W}in;height:{bd.H}in;break-after:page}}.g.pre{{opacity:1}}#hint,#bar{{display:none}}}}
"""
    )
    parts: list[str] = [
        '<!doctype html><html lang="ar" dir="ltr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Falcon Lens | عدسة الصقر</title><style>{css}</style></head><body>"
        '<main id="stage" aria-live="polite">'
    ]
    motion: list[dict[str, Any]] = []
    for index, sl in enumerate(slides):
        label = html_escape(f"{sl.title_en} · {sl.title_ar}")
        parts.append(f'<section class="slide" data-key="{sl.key}" aria-label="{index + 1}. {label}">')
        entry: dict[str, Any] = {"beats": beats(sl.motion), "autoplay": False}
        for sh in sl.shapes:
            if isinstance(sh, bd.Group):
                if not sh.shapes:
                    continue
                left, top, right, bottom = _bbox(bd, sh)
                style = (
                    f"--l:{left - 0.04:.3f}in;--t:{top - 0.04:.3f}in;--r:{right + 0.04:.3f}in;--b:{bottom + 0.04:.3f}in;"
                    f"--cx:{(left + right) / 2:.3f}in;--cy:{(top + bottom) / 2:.3f}in"
                )
                parts.append(f'<div class="g" data-n="{sh.name}" style="{style}">')
                bd.html_shape(sh, parts)
                parts.append("</div>")
            elif isinstance(sh, bd.Movie):
                geo = f"left:{sh.x}in;top:{sh.y}in;width:{sh.w}in;height:{sh.h}in;"
                parts.append(
                    f'<video src="{VIDEO_REL}" poster="{_data_uri(sh.poster, "image/png")}" preload="auto" playsinline style="{geo}"></video>'
                )
                entry["autoplay"] = bool(sh.auto)
            else:
                bd.html_shape(sh, parts)
        parts.append("</section>")
        motion.append(entry)
    parts.append(
        '</main><div id="bar"></div>'
        '<div id="hint">→ or Space: next · ←: back · F: full screen</div>'
        f'<script id="motion" type="application/json">{json.dumps(motion, ensure_ascii=False)}</script>'
        f"<script>{PLAYER}</script></body></html>"
    )
    page = "".join(parts)

    def inline(match: re.Match[str]) -> str:
        path = Path(unquote(urlparse(match.group(1)).path))
        return f'src="{_data_uri(path, "image/png")}"'

    page = re.sub(r'src="(file://[^"]+\.png)"', inline, page)
    if "file://" in page or re.search(r'(src|href)="https?://', page):
        raise ValueError("the presentation must not reference local paths or the network")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")


def html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
