// Small maths and DOM helpers. Everything is a pure function of the time handed to it.

export const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
export const mix = (a, b, k) => a + (b - a) * k;
export const mixv = (a, b, k) => a.map((v, i) => v + (b[i] - v) * k);
/** Linear progress of `t` through [a, b], clamped to 0..1. */
export const seg = (t, a, b) => clamp((t - a) / (b - a));
export const TAU = Math.PI * 2;

export const E = {
  lin: (x) => x,
  in2: (x) => x * x,
  out2: (x) => 1 - (1 - x) * (1 - x),
  io2: (x) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2),
  in3: (x) => x * x * x,
  out3: (x) => 1 - Math.pow(1 - x, 3),
  io3: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  out4: (x) => 1 - Math.pow(1 - x, 4),
  out5: (x) => 1 - Math.pow(1 - x, 5),
  io5: (x) => (x < 0.5 ? 16 * Math.pow(x, 5) : 1 - Math.pow(-2 * x + 2, 5) / 2),
  outE: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)), // tokens.css --fl-ease-out: fast start, long settle
  inE: (x) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10)),
  back: (x, s = 1.70158) => 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2),
  /** One soft overshoot, like tokens.css --fl-ease-spring. */
  spring: (x) => (x >= 1 ? 1 : 1 - Math.exp(-7.5 * x) * Math.cos(10.5 * x)),
  /** Rises then falls back to 0: a pulse that peaks at `peak` (0..1). */
  bump: (x, peak = 0.3) => (x <= 0 || x >= 1 ? 0 : x < peak ? E.out2(x / peak) : 1 - E.io2((x - peak) / (1 - peak))),
};

/** Eased 0..1 that starts at `a` and lasts `d` seconds. */
export const tw = (t, a, d, e = E.outE) => e(seg(t, a, a + d));
/** 1 while inside [a, b], with eased edges of `fi` and `fo` seconds. */
export const win = (t, a, b, fi = 0.25, fo = 0.2, ei = E.out3, eo = E.in2) => Math.min(ei(seg(t, a, a + fi)), 1 - eo(seg(t, b - fo, b)));

/**
 * A value that moves between keys. Each key is {t, d, v, e}: the value `v` is reached at time `t` after a move that
 * lasts `d` seconds; until that move starts the previous value holds.
 */
export function track(keys) {
  return (time) => {
    let cur = keys[0].v;
    for (const k of keys) {
      if (time >= k.t) {
        cur = k.v;
        continue;
      }
      const d = k.d ?? 0.5;
      const p = (time - (k.t - d)) / d;
      if (p <= 0) return cur;
      const e = (k.e ?? E.io3)(clamp(p));
      return Array.isArray(cur) ? mixv(cur, k.v, e) : mix(cur, k.v, e);
    }
    return cur;
  };
}

/** Deterministic pseudo-random numbers (mulberry32). */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Smooth 1-D value noise in -1..1, the same for the same (x, seed). */
export function noise1(x, seed = 0) {
  const h = (n) => {
    const s = Math.sin(n * 127.1 + seed * 311.7) * 43758.5453;
    return (s - Math.floor(s)) * 2 - 1;
  };
  const i = Math.floor(x);
  const f = x - i;
  const u = f * f * (3 - 2 * f);
  return mix(h(i), h(i + 1), u);
}

export const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
export const rgb = (c, a = 1) => (a >= 1 ? `rgb(${c[0] | 0} ${c[1] | 0} ${c[2] | 0})` : `rgb(${c[0] | 0} ${c[1] | 0} ${c[2] | 0} / ${a.toFixed(3)})`);
export const mixc = (a, b, k) => [mix(a[0], b[0], k), mix(a[1], b[1], k), mix(a[2], b[2], k)];

// Night theme of web/design/tokens.css.
export const C = {
  bg: hex("#070b14"),
  s1: hex("#0e1626"),
  s2: hex("#16203a"),
  s3: hex("#1f2c4c"),
  border: hex("#2a3757"),
  strong: hex("#5a6c92"),
  text: hex("#f2eee6"),
  muted: hex("#aeb8cc"),
  faint: hex("#8794ae"),
  brand: hex("#3fe0c5"),
  brandHi: hex("#7df0dc"),
  sand: hex("#e7d7b6"),
  danger: hex("#ff8589"),
  dangerSolid: hex("#d42a38"),
  warn: hex("#ffc55c"),
  nws: hex("#a9c0ff"),
};

const SVGNS = "http://www.w3.org/2000/svg";
/** Create an HTML element: h("div.card#id", {attrs}, ...children). */
export function h(spec, attrs = {}, ...kids) {
  const [tagId, ...classes] = spec.split(".");
  const [tag, id] = tagId.split("#");
  const el = document.createElement(tag || "div");
  if (id) el.id = id;
  if (classes.length) el.className = classes.join(" ");
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
/** Create an SVG element. */
export function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

/** Position, scale and fade an element from one call. Hidden elements leave the paint list. */
export function put(el, { x = 0, y = 0, sx = 1, sy, r = 0, o = 1, blur = 0, rx = 0, ry = 0, z = 0, origin } = {}) {
  if (o <= 0.002) {
    if (el.style.visibility !== "hidden") el.style.visibility = "hidden";
    return;
  }
  if (el.style.visibility) el.style.visibility = "";
  const sY = sy ?? sx;
  let tf = `translate3d(${x.toFixed(2)}px,${y.toFixed(2)}px,${z.toFixed(1)}px)`;
  if (rx || ry) tf += ` rotateX(${rx.toFixed(3)}deg) rotateY(${ry.toFixed(3)}deg)`;
  if (r) tf += ` rotate(${r.toFixed(3)}deg)`;
  if (sx !== 1 || sY !== 1) tf += ` scale(${sx.toFixed(4)},${sY.toFixed(4)})`;
  el.style.transform = tf;
  el.style.opacity = o >= 0.998 ? "" : o.toFixed(3);
  el.style.filter = blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : "";
  if (origin) el.style.transformOrigin = origin;
}

/** Split text into word spans (Arabic stays shaped inside each word). */
export function words(el, text, cls = "w") {
  el.textContent = "";
  const out = [];
  text
    .trim()
    .split(/\s+/)
    .forEach((w, i) => {
      if (i) el.append(" ");
      const span = h(`span.${cls}`, { text: w });
      el.append(span);
      out.push(span);
    });
  return out;
}

// Product icons (web/components/Icon.tsx): 24 px grid, 1.9 stroke, round joins.
export const ICONS = {
  mic: ["M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z", "M6 11a6 6 0 0 0 12 0", "M12 17v4"],
  dangerous: ["M8.3 2.6h7.4l5.7 5.7v7.4l-5.7 5.7H8.3l-5.7-5.7V8.3z", "M12 7.4v5.8", "M12 16.6v.1"],
  url: ["M10 14a4.2 4.2 0 0 0 6 0l3-3a4.2 4.2 0 0 0-6-6l-1 1", "M14 10a4.2 4.2 0 0 0-6 0l-3 3a4.2 4.2 0 0 0 6 6l1-1"],
  message: ["M4 5h16v11H9l-5 4z"],
  list: ["M8 6h12M8 12h12M8 18h12", "M4 6v.1M4 12v.1M4 18v.1"],
  globe: ["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z", "M3 12h18", "M12 3c2.5 2.5 3.5 5.5 3.5 9S14.5 18.5 12 21c-2.5-2.5-3.5-5.5-3.5-9S9.5 5.5 12 3z"],
  box: ["M4 8l8-4 8 4v8l-8 4-8-4z", "M4 8l8 4 8-4M12 12v8"],
  spark: ["M12 3v4M12 17v4M3 12h4M17 12h4", "M12 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z"],
  key: ["M14.5 9.5a4 4 0 1 0-3.7 5.5L12 16.2V18h2v2h3v-3l-3.8-3.8a4 4 0 0 0 1.3-3.7z", "M9.5 9.5v.1"],
  tick: ["M5 12.5 10 17.5 19 7"],
  copy: ["M9 9h10v11H9z", "M5 15V4h10"],
  keyboard: ["M3 7h18v10H3z", "M7 10.5v.1M11 10.5v.1M15 10.5v.1M8 14h8"],
  slash: ["M4 4l16 16"],
};
export function icon(name, size = 24, extra = "") {
  const svg = s("svg", { class: `icon ${extra}`.trim(), width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": name === "tick" ? 3 : 1.9, "stroke-linecap": "round", "stroke-linejoin": "round" });
  for (const d of ICONS[name]) svg.append(s("path", { d }));
  return svg;
}
