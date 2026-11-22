/**
 * DOM helpers shared by the warning page, popup and options page.
 * Every string reaches the page through a text node. There is no innerHTML anywhere in the extension.
 */
import { dirOf, t, type Lang, type StringKey, type VerdictWord } from "./i18n";

const NS = "http://www.w3.org/2000/svg";
type Attrs = Record<string, string | number | boolean | undefined>;
type Kid = Node | string | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...kids: Kid[]): HTMLElementTagNameMap[K] {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === false) continue;
    if (k === "text") n.textContent = String(v);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids) if (c) n.append(c);
  return n;
}

export function svg(tag: string, attrs: Attrs = {}, ...kids: Node[]): SVGElement {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== false) n.setAttribute(k, String(v));
  n.append(...kids);
  return n;
}

/* Verdicts differ by outline shape, never by colour alone (docs/DESIGN.md §4):
   octagon = dangerous, triangle = suspicious, lens with a dash = no warning signs. No tick marks. */
const ICONS: Record<string, string[]> = {
  dangerous: ["M8.3 2.6h7.4l5.7 5.7v7.4l-5.7 5.7H8.3l-5.7-5.7V8.3z", "M12 7.4v5.8", "M12 16.6v.1"],
  suspicious: ["M12 3.1 21.8 20.4H2.2z", "M10.1 11.3a2 2 0 1 1 3 1.7c-.7.4-1.1.9-1.1 1.6", "M12 17.4v.1"],
  no_warning_signs: ["M10.5 3.5a7 7 0 1 1 0 14 7 7 0 0 1 0-14z", "M15.6 15.6 21 21", "M7.6 10.5h5.8"],
  undo: ["M9 7 4.5 11.5 9 16", "M4.5 11.5H14a5.5 5.5 0 0 1 0 11h-2"],
  globe: ["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z", "M3 12h18", "M12 3c2.5 2.5 3.5 5.5 3.5 9S14.5 18.5 12 21c-2.500-2.500-3.500-5.500-3.500-9S9.500 5.500 12 3z"],
  gear: ["M12 8.500a3.500 3.500 0 1 1 0 7 3.500 3.500 0 0 1 0-7z", "M12 2.500v3M12 18.500v3M2.500 12h3M18.500 12h3M5.300 5.300l2.100 2.100M16.600 16.600l2.100 2.100M5.300 18.700l2.100-2.100M16.600 7.400l2.100-2.100"],
  open: ["M14 4h6v6", "M20 4l-9 9", "M18 14v6H4V6h6"],
  eye: ["M2.500 12s3.500-6.500 9.500-6.500S21.500 12 21.500 12s-3.500 6.500-9.500 6.500S2.500 12 2.500 12z", "M12 9.500a2.500 2.500 0 1 1 0 5 2.500 2.500 0 0 1 0-5z"],
};

export function icon(name: keyof typeof ICONS | string, size = 24): SVGElement {
  const s = svg("svg", {
    class: "icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 1.9, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
  });
  for (const d of ICONS[name] ?? []) s.append(svg("path", { d }));
  return s;
}

/** The mark: ring, pupil, brow stroke and the falcon's malar stripe. Original; no crest, no shield. */
export function mark(size = 32): SVGElement {
  return svg(
    "svg",
    { class: "mark", width: size, height: size, viewBox: "0 0 36 36", fill: "none", "aria-hidden": "true" },
    svg("path", { class: "mark-sand", d: "M5 10.5c5-5.5 16-7 26-2.5", "stroke-width": 3, "stroke-linecap": "round" }),
    svg("circle", { class: "mark-ring", cx: 18, cy: 18, r: 9, "stroke-width": 3 }),
    svg("circle", { class: "mark-pupil", cx: 18, cy: 18, r: 3.6 }),
    svg("path", { class: "mark-sand", d: "M14.5 28.500c-.6 2.600-2 4.600-4 6", "stroke-width": 3, "stroke-linecap": "round" }),
  );
}

export type LensState = "scanning" | "locked" | "idle";
export interface Lens {
  node: HTMLElement;
  set(state: LensState, verdict?: VerdictWord): void;
}

const APERTURE: Record<LensState, number> = { idle: 78, scanning: 50, locked: 66 };
const fx = (n: number): string => n.toFixed(2);
const polar = (r: number, deg: number): [number, number] => {
  const a = ((deg - 90) * Math.PI) / 180;
  return [200 + r * Math.cos(a), 200 + r * Math.sin(a)];
};

/**
 * The lens instrument from docs/DESIGN.md §7, reduced to what the extension needs: it narrows and
 * sweeps while the deeper check runs, then locks and takes the verdict's colour and shape.
 * One SVG plus one rotating layer; blades are redrawn only during the 420 ms state change.
 */
export function createLens(): Lens {
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const node = el("div", { class: "lens", "data-state": "idle", "aria-hidden": "true" });
  const s = svg("svg", { class: "lens-svg", viewBox: "0 0 400 400" });
  s.append(
    svg("circle", { class: "lens-halo", cx: 200, cy: 200, r: 200 }),
    svg("circle", { class: "lens-ticks", cx: 200, cy: 200, r: 190 }),
    svg("circle", { class: "lens-majors", cx: 200, cy: 200, r: 190 }),
    svg("circle", { class: "lens-ring", cx: 200, cy: 200, r: 168 }),
    svg("circle", { class: "lens-pupil", cx: 200, cy: 200, r: 152 }),
    svg("circle", { class: "lens-pupil-tint", cx: 200, cy: 200, r: 152 }),
  );
  const blades = Array.from({ length: 8 }, () => svg("polygon", { class: "lens-blade" }));
  s.append(svg("g", {}, ...blades));
  s.append(
    svg("ellipse", { class: "lens-glint", cx: 168, cy: 166, rx: 9, ry: 5, transform: "rotate(-35 168 166)" }),
    svg("path", { class: "lens-brow", d: "M52 86C120 22 262 6 372 78" }),
  );
  const core = el("div", { class: "lens-core" });
  node.append(s, el("div", { class: "lens-sweep" }), core);

  let aperture = APERTURE.idle;
  let raf = 0;
  const draw = (a: number): void => {
    const R = 152, n = 8, rv = a / Math.cos(Math.PI / n), twist = 34 + (78 - a) * 0.9;
    blades.forEach((p, i) => {
      const a0 = i * 45 + 22.5, a1 = a0 + 45;
      const pts = [polar(rv, a0), polar(rv, a1), polar(R, a1 + twist), polar(R, a0 + twist)];
      p.setAttribute("points", pts.map(([x, y]) => `${fx(x)},${fx(y)}`).join(" "));
    });
  };
  const tween = (to: number): void => {
    cancelAnimationFrame(raf);
    if (still) {
      aperture = to;
      draw(to);
      return;
    }
    const from = aperture, t0 = performance.now();
    const step = (now: number): void => {
      const k = Math.min(1, (now - t0) / 420), e = 1 - Math.pow(1 - k, 4);
      aperture = from + (to - from) * e;
      draw(aperture);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  };
  draw(aperture);

  return {
    node,
    set(state, verdict) {
      node.dataset["state"] = state;
      if (verdict) node.dataset["verdict"] = verdict;
      else delete node.dataset["verdict"];
      core.replaceChildren();
      if (state === "locked" && verdict) core.append(icon(verdict, 24));
      tween(APERTURE[state]);
    },
  };
}

/** A URL or host for display: monospace, LTR-isolated, already defanged, never a link. */
export function techText(value: string, cls = "tech"): HTMLElement {
  return el("bdi", { class: cls, dir: "ltr", text: value });
}

export function applyLang(lang: Lang): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = dirOf(lang);
}

/** Header shared by every page: mark, bilingual name, language switch. */
export function header(lang: Lang, onToggle: (next: Lang) => void): HTMLElement {
  const next: Lang = lang === "ar" ? "en" : "ar";
  const btn = el("button", {
    class: "btn-ghost lang", type: "button", id: "lang-toggle", lang: next, "aria-label": t("lang_switch_label", lang),
    text: t("lang_switch", lang),
  });
  btn.addEventListener("click", () => onToggle(next));
  return el(
    "header",
    { class: "top" },
    el("div", { class: "brand" }, mark(32), el("span", { class: "brand-name" }, el("strong", { text: "عدسة الصقر", lang: "ar" }), el("small", { text: "FALCON LENS", lang: "en" }))),
    btn,
  );
}

export function plate(verdict: VerdictWord, word: string, lead: string, extra?: Node): HTMLElement {
  return el(
    "section",
    { class: "plate", "data-verdict": verdict, role: "status", "aria-live": "assertive", id: "plate" },
    icon(verdict, 56),
    el("div", { class: "plate-text" }, el("h1", { class: "plate-word", id: "verdict-word", text: word }), el("p", { class: "plate-lead", text: lead })),
    extra,
  );
}

export function listBlock(titleKey: StringKey, lang: Lang, items: string[], id: string, cls = ""): HTMLElement | null {
  if (items.length === 0) return null;
  const ul = el("ul", { class: "rows" });
  items.forEach((text, i) => {
    const li = el("li", { class: "row", text });
    li.style.setProperty("--i", String(Math.min(i, 8)));
    ul.append(li);
  });
  return el("section", { class: `block ${cls}`.trim(), id }, el("h2", { class: "block-title", text: t(titleKey, lang) }), ul);
}

export const demoBadge = (lang: Lang): HTMLElement => el("span", { class: "demo-badge", id: "demo-badge", text: t("demo_data", lang) });
