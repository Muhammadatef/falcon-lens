// Captions and the numbered live steps, the «تمثيل — Dramatisation» label, and the footage layer.
import { C, E, clamp, h, icon, mix, mixc, rgb, seg, tw, words } from "./lib.js";

const DONE_SCALE = 0.5;
const ENTER = 0.1; // a row starts to appear this long before its first word

/**
 * The spoken lines, as on the product's voice page: each line of the answer is a numbered row («الخطوات
 * المباشرة») that gets a tick when it is done, and the line being spoken is the caption. Words light up as they
 * are said; the English line of the same row is the subtitle.
 */
export function makeCaptions(hud, L, TL, speakers) {
  const T = L.text;
  const lines = TL.lines;
  const endT = (TL.scenes.find((sc) => sc.id === "relief") ?? TL.scenes.find((sc) => sc.id === "end") ?? { t0: TL.duration }).t0;
  const rows = lines.map((ln, i) => {
    const el = h("div.cap", { "data-who": ln.who, style: `width:${T.w}px` });
    if (ln.id === "investigator.arbiter_result.dangerous") el.dataset.tone = "danger";
    const num = h("span.cap-num", { text: ln.step ? `${ln.step}.` : "", style: `font-size:${T.num}px` });
    const dot = h("span.cap-dot", { style: `font-size:${T.num}px` });
    const tick = h("span.cap-tick", { style: `font-size:${T.num}px` }, icon("tick", 24));
    const who = speakers[ln.who];
    const tag = h("span.cap-who", { text: who ? `${who[0]} · ${who[1]}` : "", style: `font-size:${T.tag}px` });
    const head = h("div.cap-head", {}, ...(ln.step ? [num, dot, tick] : []), tag);
    const ar = h("div.cap-ar", { dir: "rtl", style: `font-size:${T.ar}px` });
    const ws = words(ar, ln.ar);
    const en = h("div.cap-en", { text: ln.en, style: `font-size:${T.en}px` });
    el.append(head, ar, en);
    hud.append(el);
    const next = lines[i + 1];
    const tin = ln.t0 - ENTER;
    // A numbered row stays the caption until the next line starts; other lines also leave after a short hold.
    let tout = next ? next.t0 - ENTER : endT - 0.3;
    if (!ln.step) tout = Math.min(tout, ln.t1 + (ln.who === "title" ? 0.2 : 0.75));
    tout = Math.min(tout, endT - 0.3);
    return { ln, el, head, ar, en, ws, num, dot, tick, tag, tin, tout, h: 0, hAr: 0 };
  });
  // Measure once (fonts are loaded before this runs).
  for (const r of rows) {
    r.h = r.el.offsetHeight;
    r.hAr = r.en.offsetTop;
  }
  const gap = T.gap ?? 18;

  function update(t) {
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (t < r.tin - 0.02) {
        r.el.style.visibility = "hidden";
        continue;
      }
      const a = tw(t, r.tin + 0.02, 0.28, E.out3); // arrive
      const d = r.ln.step ? tw(t, r.tout - 0.16, 0.36, E.io3) : 0; // become a done row
      const leave = r.ln.step ? 0 : tw(t, r.tout - 0.2, 0.17, E.in2); // gone before the next line arrives
      // Rise by the height of every row that is done after this one (and by its own).
      let rise = 0;
      let rank = 0;
      if (r.ln.step) {
        rise += d * (r.hAr * DONE_SCALE + gap);
        for (let j = i + 1; j < rows.length; j++) {
          const q = rows[j];
          if (!q.ln.step || t < q.tout - 0.16) continue;
          const e = tw(t, q.tout - 0.16, 0.36, E.io3);
          rise += e * (q.hAr * DONE_SCALE + gap);
          rank += e;
        }
      }
      const clear = tw(t, endT - 0.3, 0.3, E.in2);
      let o = a * (1 - leave) * (1 - clear);
      if (r.ln.step) o *= mix(1, rank < 1 ? mix(0.66, 0.36, rank) : mix(0.36, 0, clamp(rank - 1)), d);
      if (o <= 0.004) {
        r.el.style.visibility = "hidden";
        continue;
      }
      r.el.style.visibility = "";
      const sc = mix(1, DONE_SCALE, d);
      const y = T.activeTop + (1 - a) * 26 - rise - leave * 14;
      // Scaling from the top right keeps the Arabic edge of every row on one line.
      r.el.style.transform = `translate3d(${T.x}px,${y.toFixed(2)}px,0) scale(${sc.toFixed(4)})`;
      r.el.style.opacity = o.toFixed(3);
      r.en.style.opacity = (1 - d).toFixed(3);
      r.tag.style.opacity = (1 - d).toFixed(3);
      if (r.ln.step) {
        r.dot.style.display = d > 0.5 ? "none" : "";
        r.tick.style.display = d > 0.5 ? "" : "none";
        r.dot.style.opacity = (0.45 + 0.55 * Math.abs(Math.sin(t * 5))).toFixed(3);
      }
      // Words light up as they are spoken.
      const base = r.ln.who === "title" ? C.sand : r.el.dataset.tone === "danger" ? C.danger : C.text;
      const hot = r.ln.who === "falcon" ? C.brandHi : C.sand;
      for (let k = 0; k < r.ws.length; k++) {
        const wt = r.ln.words[k]?.[1] ?? r.ln.t0;
        const said = seg(t, wt - 0.03, wt + 0.07);
        const settle = seg(t, wt + 0.07, wt + 0.42);
        const w = r.ws[k];
        if (said <= 0) {
          w.style.opacity = "0.3";
          w.style.transform = "";
          w.style.color = "";
        } else {
          const pop = E.bump(seg(t, wt - 0.03, wt + 0.3), 0.28);
          w.style.opacity = mix(0.3, 1, said).toFixed(3);
          w.style.transform = pop > 0.004 ? `translateY(${(-5 * pop).toFixed(2)}px) scale(${(1 + 0.07 * pop).toFixed(4)})` : "";
          w.style.color = settle >= 1 ? "" : rgb(mixc(hot, base, E.out2(settle)));
        }
      }
    }
  }
  return { update };
}

/** The label that stays on every frame. In the portrait cut it also sits exactly over the footage's own label. */
export function makeLabel(root, L, text) {
  const c = L.chip;
  const el = h("div.label", { text, style: `left:${c.x}px;top:${c.y}px;width:${c.w}px;height:${c.h}px;font-size:${c.font}px` });
  root.append(el);
  return { update(o) { el.style.opacity = o.toFixed(3); el.style.visibility = o > 0.004 ? "" : "hidden"; } }; // prettier-ignore
}

/**
 * Footage of the owner's dramatisation, shown as an image sequence so that a frame of film is exactly a frame of
 * source. `plate` is the two-shot that opens the cut: sharp for half a second, then held, blurred and dimmed
 * behind the message.
 */
export function makeLive(root, L, TL, opts) {
  const pics = TL.live_pic ?? [];
  if (!pics.length || !opts.frames) return { update: async () => {}, active: () => 0 };
  const V = L.live;
  const scale = V.w / 1080;
  const box = h("div.live-box", { style: `left:${V.x}px;top:${V.y}px;width:${V.w}px;height:${V.h}px` });
  const img = h("img.live-img", { style: `width:${V.w}px;height:${Math.round(1920 * scale)}px;top:${-Math.round(V.srcY * scale)}px;transform-origin:50% 35%` });
  const shade = h("div.live-shade");
  const dim = h("div.live-shade");
  box.append(img, dim, shade);
  root.append(box);
  const bg = rgb(C.bg);
  const clear = rgb(C.bg, 0);
  shade.style.background = L.portrait
    ? `linear-gradient(to bottom, ${clear} ${Math.round((V.fade0 / V.h) * 100)}%, ${bg} 100%)`
    : `linear-gradient(to right, ${clear} 80%, ${bg} 100%), linear-gradient(to bottom, ${clear} 84%, ${rgb(C.bg, 0.85)} 100%)`;
  const sc = (id) => TL.scenes.find((x) => x.id === id);
  const plate = pics.find((p) => p.id === "plate");
  const plateEnd = sc("call")?.t0 ?? plate?.t1 ?? 0;
  const land = TL.marks["cold.land"] ?? 0;
  const fps = opts.sourceFps ?? 30;
  let shown = "";

  async function update(t) {
    let pic = pics.find((p) => p.id !== "plate" && t >= p.t0 && t < p.t1);
    let blur = 0;
    let dark = 0;
    let zoom = 1;
    let src = null;
    if (pic) {
      src = pic.src0 + (t - pic.t0);
      zoom = 1.0 + 0.012 * seg(t, pic.t0, pic.t1); // a breath of push-in on every shot
    } else if (plate && t >= plate.t0 && t < plateEnd) {
      pic = plate;
      src = Math.min(plate.src1 - 1 / fps, plate.src0 + (t - plate.t0));
      const k = tw(t, land - 0.08, 0.55, E.io3);
      blur = 22 * k * scale;
      dark = 0.62 * k;
      zoom = 1.02 + 0.03 * seg(t, plate.t0, plateEnd) + 0.05 * k;
    }
    if (!pic) {
      box.style.visibility = "hidden";
      return;
    }
    box.style.visibility = "";
    const f = Math.floor(src * fps + 1e-4);
    const url = `${opts.frames}/${String(f).padStart(5, "0")}.jpg`;
    if (url !== shown) {
      img.src = url;
      shown = url;
      await img.decode();
    }
    img.style.transform = `scale(${zoom.toFixed(4)})`;
    img.style.filter = blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : "";
    dim.style.background = rgb(C.bg, dark);
  }
  /** 1 while a sharp shot of the footage fills the picture area (the animation layers hide then). */
  const active = (t) => (pics.some((p) => p.id !== "plate" && t >= p.t0 && t < p.t1) ? 1 : 0);
  return { update, active };
}
