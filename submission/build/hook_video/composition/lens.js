// The Falcon: the product's lens instrument (web/components/Lens.tsx) and the flat brand mark it wakes from.
// Geometry is copied from the product (400 x 400 box): tick ring, four tier arcs T0..T3, eight aperture blades,
// brow stroke. The mark is web/public/icons/icon.svg scaled so its ring sits where the instrument's does.
import { C, clamp, h, icon, mix, rgb, s } from "./lib.js";

const polar = (r, deg) => [200 + r * Math.sin((deg * Math.PI) / 180), 200 - r * Math.cos((deg * Math.PI) / 180)];
const fx = (n) => n.toFixed(1);

function arcPath(r, a0, a1) {
  const [x0, y0] = polar(r, a0);
  const [x1, y1] = polar(r, a1);
  return `M${fx(x0)} ${fx(y0)}A${r} ${r} 0 0 1 ${fx(x1)} ${fx(y1)}`;
}

function bladePoints(aperture, i) {
  const R = 141;
  const n = 8;
  const rv = aperture / Math.cos(Math.PI / n);
  const twist = 34 + (78 - aperture) * 0.9;
  const a0 = i * 45 + 22.5;
  const a1 = a0 + 45;
  return [polar(rv, a0), polar(rv, a1), polar(R, a1 + twist), polar(R, a0 + twist)].map(([x, y]) => `${fx(x)},${fx(y)}`).join(" ");
}

export const APERTURE = { shut: 3, sleep: 14, think: 44, scan: 56, locked: 66, idle: 92, listen: 104, wide: 132 };
const MARK_BROW = "M24.4 97.6c64.4-70.2 207.8-90.7 339.5-32.2";
const MARK_MALAR = "M153.2 340.5c-8.8 35.1-26.3 61.5-52.7 79";

let uid = 0;

export function makeLens(parent) {
  const id = `lens${uid++}`;
  const root = h("div.lens");
  // Below the glass: halo, tick ring, tier arcs, ring, the dark disc.
  const under = s("svg", { class: "lens-svg", viewBox: "0 0 400 400" });
  const grad = s("radialGradient", { id: `${id}g`, cx: "42%", cy: "38%", r: "70%" }, s("stop", { offset: 0, "stop-color": "#1b2a4a" }), s("stop", { offset: 0.6, "stop-color": "#070b14" }), s("stop", { offset: 1, "stop-color": "#020409" }));
  const iris = s("radialGradient", { id: `${id}i`, cx: "50%", cy: "50%", r: "50%" }, s("stop", { offset: 0.35, "stop-color": "currentColor", "stop-opacity": 0 }), s("stop", { offset: 0.82, "stop-color": "currentColor", "stop-opacity": 0.42 }), s("stop", { offset: 1, "stop-color": "currentColor", "stop-opacity": 0 }));
  under.append(s("defs", {}, grad, iris));
  const back = s("circle", { class: "lens-back", cx: 200, cy: 200, r: 197 }); // the magnifier's frame: hides what is behind the rim
  const halo = s("circle", { class: "lens-halo", cx: 200, cy: 200, r: 200 });
  const ticks = s("circle", { class: "lens-ticks", cx: 200, cy: 200, r: 190 });
  const majors = s("circle", { class: "lens-majors", cx: 200, cy: 200, r: 190 });
  const spin = s("g", { class: "lens-spin" }, ticks, majors);
  const arcsBase = [];
  const arcsFill = [];
  for (let i = 0; i < 4; i++) {
    const d = arcPath(170, i * 90 + 7, i * 90 + 83);
    arcsBase.push(s("path", { class: "lens-arc lens-arc--base", d }));
    arcsFill.push(s("path", { class: "lens-arc lens-arc--fill", d, pathLength: 1 }));
  }
  const ring = s("circle", { class: "lens-ring", cx: 200, cy: 200, r: 152 });
  const disc = s("circle", { cx: 200, cy: 200, r: 141, fill: `url(#${id}g)` });
  const tint = s("circle", { class: "lens-tint", cx: 200, cy: 200, r: 141 });
  under.append(back, halo, spin, ...arcsBase, ...arcsFill, ring, disc, tint);

  // Magnified content sits inside the glass, under the blades.
  const mag = h("div.lens-mag");
  const magInner = h("div.lens-mag-inner");
  mag.append(magInner);

  // Above the glass: iris and pupil (the eye), blades, glint, brow.
  const over = s("svg", { class: "lens-svg", viewBox: "0 0 400 400" });
  const irisRing = s("circle", { class: "lens-iris", cx: 200, cy: 200, r: 120, fill: `url(#${id}i)` });
  const pupil = s("circle", { class: "lens-pupil", cx: 200, cy: 200, r: 26 });
  const pupilGlint = s("circle", { class: "lens-pupil-glint", cx: 191, cy: 191, r: 6 });
  const eye = s("g", {}, irisRing, pupil, pupilGlint);
  const blades = [];
  const bladeG = s("g");
  for (let i = 0; i < 8; i++) {
    const p = s("polygon", { class: i % 2 ? "lens-blade" : "lens-blade lens-blade--odd" });
    blades.push(p);
    bladeG.append(p);
  }
  const clip = s("clipPath", { id: `${id}c` }, s("circle", { cx: 200, cy: 200, r: 141 }));
  over.append(s("defs", {}, clip));
  const inside = s("g", { "clip-path": `url(#${id}c)` }, eye, bladeG);
  const glint = s("ellipse", { class: "lens-glint", cx: 168, cy: 166, rx: 9, ry: 5, transform: "rotate(-35 168 166)" });
  const brow = s("path", { class: "lens-brow", d: "M52 86C120 22 262 6 372 78" });
  over.append(inside, glint, brow);

  const sweep = h("div.lens-sweep");
  const core = h("div.lens-core");
  const coreVerdict = icon("dangerous", 96, "lens-core-verdict");
  const coreMic = icon("mic", 96, "lens-core-mic");
  core.append(coreVerdict, coreMic);

  const instrument = h("div.lens-instrument", {}, under, mag, over, sweep, core);

  // The flat mark (logo).
  const mark = s("svg", { class: "lens-svg lens-mark", viewBox: "0 0 400 400" });
  const mBrow = s("path", { class: "mark-sand", d: MARK_BROW, pathLength: 1 });
  const mRing = s("circle", { class: "mark-ring", cx: 200, cy: 200, r: 120, pathLength: 1, transform: "rotate(-90 200 200)" });
  const mPupil = s("circle", { class: "mark-pupil", cx: 200, cy: 200, r: 46.8 });
  const mMalar = s("path", { class: "mark-sand", d: MARK_MALAR, pathLength: 1 });
  mark.append(mBrow, mRing, mPupil, mMalar);

  root.append(instrument, mark);
  parent.append(root);

  let lastAperture = -1;
  function update(st) {
    const o = st.o ?? 1;
    if (o <= 0.002) {
      root.style.visibility = "hidden";
      return;
    }
    root.style.visibility = "";
    const sc = st.scale ?? 1;
    root.style.transform = `translate3d(${(st.x - 200).toFixed(2)}px,${(st.y - 200).toFixed(2)}px,0) rotate(${(st.rot ?? 0).toFixed(3)}deg) scale(${sc.toFixed(4)})`;
    root.style.opacity = o >= 0.998 ? "" : o.toFixed(3);
    const col = st.color ?? C.brand;
    root.style.setProperty("--lens-c", rgb(col));
    const glow = st.glow ?? 1;
    const blur = st.blur ?? 0;
    root.style.filter = `${blur > 0.05 ? `blur(${blur.toFixed(2)}px) ` : ""}drop-shadow(0 0 ${(26 * glow).toFixed(1)}px ${rgb(col, clamp(0.34 * glow, 0, 0.9))})`;

    const m = clamp(st.m ?? 1);
    // Instrument.
    if (m <= 0.002) instrument.style.visibility = "hidden";
    else {
      instrument.style.visibility = "";
      instrument.style.opacity = m.toFixed(3);
      instrument.style.transform = `scale(${mix(0.86, 1, m).toFixed(4)})`;
      const blink = clamp(st.blink ?? 0);
      const ap = Math.max(1, (st.aperture ?? APERTURE.idle) * (1 - 0.92 * blink));
      if (Math.abs(ap - lastAperture) > 0.02) {
        for (let i = 0; i < 8; i++) blades[i].setAttribute("points", bladePoints(ap, i));
        lastAperture = ap;
      }
      halo.setAttribute("opacity", (0.1 + 0.14 * (st.halo ?? 0)).toFixed(3));
      back.setAttribute("opacity", (0.9 * clamp(st.mag ?? 0)).toFixed(3));
      spin.setAttribute("transform", `rotate(${(st.tickRot ?? 0).toFixed(2)} 200 200)`);
      const arcs = st.arcs ?? [0, 0, 0, 0];
      for (let i = 0; i < 4; i++) {
        const a = clamp(arcs[i]);
        const running = st.run === i;
        arcsFill[i].setAttribute("stroke-dashoffset", (running ? 0 : 1 - a).toFixed(4));
        arcsFill[i].setAttribute("opacity", running ? (0.3 + 0.3 * (st.breathe ?? 0)).toFixed(3) : a > 0 ? "1" : "0");
      }
      tint.setAttribute("opacity", (0.32 * (st.core ?? 0)).toFixed(3));
      const gz = st.gaze ?? [0, 0];
      const eyeO = clamp(st.eye ?? 1) * (1 - (st.core ?? 0)) * (1 - (st.mic ?? 0)) * (1 - (st.mag ?? 0));
      const reach = Math.min(ap * 0.42, 34);
      eye.setAttribute("transform", `translate(${(gz[0] * reach).toFixed(2)} ${(gz[1] * reach).toFixed(2)})`);
      eye.setAttribute("opacity", eyeO.toFixed(3));
      irisRing.setAttribute("r", Math.min(ap * 1.05, 132).toFixed(1));
      const pr = 26 * (st.pupil ?? 1) * clamp(ap / 60, 0.25, 1.15);
      pupil.setAttribute("r", pr.toFixed(2));
      pupilGlint.setAttribute("r", (pr * 0.23).toFixed(2));
      pupilGlint.setAttribute("cx", (200 - pr * 0.34).toFixed(2));
      pupilGlint.setAttribute("cy", (200 - pr * 0.34).toFixed(2));
      glint.setAttribute("transform", `translate(${(-gz[0] * 7).toFixed(2)} ${(-gz[1] * 7).toFixed(2)}) rotate(-35 168 166)`);
      brow.setAttribute("transform", `translate(0 ${(-(st.browLift ?? 0) + 16 * blink).toFixed(2)})`);
      brow.setAttribute("opacity", (0.85 * (st.brow ?? 1)).toFixed(3));
      const sw = st.sweepO ?? 0;
      sweep.style.opacity = sw.toFixed(3);
      if (sw > 0.002) sweep.style.transform = `rotate(${(st.sweep ?? 0).toFixed(2)}deg)`;
      const cv = clamp(st.core ?? 0);
      coreVerdict.style.opacity = cv.toFixed(3);
      coreVerdict.style.transform = `scale(${mix(0.4, 1, st.coreScale ?? cv).toFixed(4)})`;
      const mc = clamp(st.mic ?? 0);
      coreMic.style.opacity = mc.toFixed(3);
      coreMic.style.transform = `scale(${mix(0.7, 1, mc).toFixed(4)})`;
      const mg = clamp(st.mag ?? 0);
      mag.style.opacity = mg.toFixed(3);
      mag.style.visibility = mg > 0.002 ? "" : "hidden";
    }
    // Mark.
    const k = 1 - m;
    if (k <= 0.002) mark.style.visibility = "hidden";
    else {
      mark.style.visibility = "";
      mark.style.opacity = k.toFixed(3);
      mark.style.transform = `scale(${mix(1.14, 1, k).toFixed(4)})`;
      const d = clamp(st.draw ?? 1);
      // Strokes draw on in order: brow, ring, malar stripe; the pupil pops last.
      const part = (a, b) => clamp((d - a) / (b - a));
      mBrow.setAttribute("stroke-dashoffset", (1 - part(0, 0.42)).toFixed(4));
      mRing.setAttribute("stroke-dashoffset", (1 - part(0.18, 0.78)).toFixed(4));
      mMalar.setAttribute("stroke-dashoffset", (1 - part(0.62, 0.92)).toFixed(4));
      for (const [el, a, b] of [[mBrow, 0, 0.42], [mRing, 0.18, 0.78], [mMalar, 0.62, 0.92]]) el.setAttribute("opacity", part(a, b) > 0.001 ? "1" : "0"); // prettier-ignore
      const pp = st.markPupil ?? part(0.8, 1);
      const blink = clamp(st.blink ?? 0);
      mPupil.setAttribute("transform", `translate(200 200) scale(${pp.toFixed(4)} ${(pp * (1 - 0.9 * blink)).toFixed(4)}) translate(-200 -200)`);
      mPupil.setAttribute("opacity", pp > 0.01 ? "1" : "0");
      const dim = st.markDim ?? 1;
      mRing.style.stroke = rgb(col, dim);
    }
  }
  return { el: root, mag, magInner, update };
}
