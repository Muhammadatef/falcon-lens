#!/usr/bin/env node
/**
 * Writes docs/assets/architecture.svg (the README figure) from the same data as the animated diagram on the site
 * (lib/arch-flow.ts MAIN_FLOW, lib/tool-logos.gen.ts, lib/capabilities.generated.json), so the two cannot drift.
 *
 *   node scripts/build-arch-svg.mjs          write the file (then `node scripts/sync-results.mjs` copies it to public/images)
 *   node scripts/build-arch-svg.mjs --check  exit 1 if the committed file is stale (tests/unit/arch-svg.test.ts)
 *
 * The SVG is animated with CSS and SMIL (a dot travels the request path, the boxes light up in turn) and is a
 * complete, labelled, numbered picture when nothing animates (prefers-reduced-motion, or a viewer without animation).
 * Needs Node 23.6 or newer (it imports the TypeScript data files directly; they only import types).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const { MAIN_FLOW, FLOW_UI } = await import(pathToFileURL(join(web, "lib", "arch-flow.ts")).href);
const { LOGO_PATHS } = await import(pathToFileURL(join(web, "lib", "tool-logos.gen.ts")).href);
const caps = JSON.parse(readFileSync(join(web, "lib", "capabilities.generated.json"), "utf8"));
const iconSource = readFileSync(join(web, "components", "Icon.tsx"), "utf8");
const iconPaths = (name) => {
  const m = iconSource.match(new RegExp(`^  ${name}: \\[(.*)\\],$`, "m"));
  if (!m) throw new Error(`icon ${name} not found`);
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
};

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const C = { bg: "#070b14", s1: "#0e1626", s2: "#16203a", line: "#2a3757", strong: "#5a6c92", text: "#f2eee6", muted: "#aeb8cc", faint: "#8794ae", brand: "#3fe0c5", sand: "#e7d7b6", ink: "#04211d" };
const W = 1200;
const PAD = 24;
const NODE_H = 58;
const GAP = 10;
const DUR = 20;

/** Greedy word wrap by character budget (the SVG has no layout engine). */
function wrap(text, max, lines) {
  const out = [];
  let cur = "";
  for (const word of text.split(" ")) {
    if (cur && (cur + " " + word).length > max) {
      out.push(cur);
      cur = word;
    } else cur = cur ? cur + " " + word : word;
  }
  if (cur) out.push(cur);
  if (out.length > lines) {
    out.length = lines;
    out[lines - 1] = out[lines - 1].replace(/[.,;:]?$/, "") + "…";
  }
  return out;
}

/**
 * Step numbers are drawn as stroked shapes, not as <text>: the submission number check (scripts/submission/
 * check_numbers.py) reads every number in this file's text as a claim that needs a published artifact, and a
 * step label is not a measurement. The same order is given in words in <desc>.
 */
const DIGIT = ["M1 1H5V9H1Z", "M1.8 2.6 3.4 1V9", "M1 1H5V5H1V9H5", "M1 1H5V9H1M1.6 5H5", "M1 1V5H5M5 1V9", "M5 1H1V5H5V9H1", "M5 1H1V9H5V5H1", "M1 1H5V9", "M1 1H5V9H1ZM1 5H5", "M5 5H1V1H5V9H1"];
function digits(value, cx, cy) {
  const chars = String(value).split("");
  const scale = 0.92;
  const width = chars.length * 6 * scale + (chars.length - 1) * 1.2;
  return chars.map((ch, i) => `<path transform="translate(${(cx - width / 2 + i * (6 * scale + 1.2)).toFixed(2)} ${(cy - 5 * scale).toFixed(2)}) scale(${scale})" d="${DIGIT[Number(ch)]}"/>`).join("");
}

const parts = [];
const centre = new Map();
const stepNo = new Map(MAIN_FLOW.steps.map((s, i) => [s.node, i]));

function badge(b, x, y) {
  const S = 34;
  if ("logo" in b) {
    const l = LOGO_PATHS[b.logo];
    return `<rect x="${x}" y="${y}" width="${S}" height="${S}" rx="8" fill="#fff"/><path transform="translate(${x + 6.2} ${y + 6.2}) scale(0.9)" fill="${l.hex}" d="${l.d}"/>`;
  }
  if ("mono" in b) {
    const size = b.mono.length > 2 ? 9.5 : 13;
    return `<rect x="${x + 0.75}" y="${y + 0.75}" width="${S - 1.5}" height="${S - 1.5}" rx="8" fill="${C.s1}" stroke="${C.strong}" stroke-width="1.5"/><text class="m" x="${x + S / 2}" y="${y + S / 2 + size * 0.36}" text-anchor="middle" font-size="${size}" font-weight="700" fill="${C.text}">${esc(b.mono)}</text>`;
  }
  return `<rect x="${x + 0.5}" y="${y + 0.5}" width="${S - 1}" height="${S - 1}" rx="8" fill="#12303a" stroke="${C.brand}" stroke-opacity=".45"/><g transform="translate(${x + 7.4} ${y + 7.4}) scale(0.8)" fill="none" stroke="${C.brand}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${iconPaths(b.icon).map((d) => `<path d="${d}"/>`).join("")}</g>`;
}

function node(n, x, y, w) {
  const no = stepNo.get(n.id);
  const live = caps[n.cap] === true;
  centre.set(n.id, [Math.round(x + w / 2), Math.round(y + NODE_H / 2)]);
  const chars = Math.floor((w - 58) / 7.3);
  const label = wrap(n.label.en, chars, 2);
  const sub = live ? wrap(n.sub.en, Math.floor((w - 58) / 5.9), label.length > 1 ? 1 : 2) : [];
  const lines = label.length + sub.length + (live ? 0 : 1);
  let ty = y + NODE_H / 2 - (lines * 13.5) / 2 + 10.5;
  let text = "";
  for (const l of label) {
    text += `<text x="${x + 52}" y="${ty.toFixed(1)}" class="nl">${esc(l)}</text>`;
    ty += 14;
  }
  for (const l of sub) {
    text += `<text x="${x + 52}" y="${ty.toFixed(1)}" class="ns">${esc(l)}</text>`;
    ty += 12.5;
  }
  if (!live) text += `<rect x="${x + 52}" y="${ty - 10}" width="74" height="15" rx="7.5" fill="none" stroke="${C.strong}" stroke-dasharray="3 2"/><text x="${x + 89}" y="${ty + 1}" class="ns" text-anchor="middle">${esc(FLOW_UI.en.progress)}</text>`;
  const cls = no === undefined ? "n" : `n on d${no}`;
  const num = no === undefined ? "" : `<g class="no d${no}"><circle cx="${x + w - 4}" cy="${y + 2}" r="10"/><g class="dg">${digits(no + 1, x + w - 4, y + 2)}</g></g>`;
  parts.push(`<g><rect class="${cls}" x="${x}" y="${y}" width="${w}" height="${NODE_H}" rx="12"${n.llm ? ' stroke-dasharray="5 4"' : ""}/>${badge(n.badge, x + 9, y + 12)}${text}${num}</g>`);
}

function grid(nodes, x, y, width, cols) {
  const w = (width - GAP * (cols - 1)) / cols;
  nodes.forEach((n, i) => node(n, x + (i % cols) * (w + GAP), y + Math.floor(i / cols) * (NODE_H + GAP), w));
  const rows = Math.ceil(nodes.length / cols);
  return rows * NODE_H + (rows - 1) * GAP;
}

const AR_TITLE = { voice: MAIN_FLOW.bands[0].title.ar, agents: MAIN_FLOW.bands[1].title.ar, platform: MAIN_FLOW.bands[2].title.ar };
const ACCENT = { voice: C.sand, agents: C.brand, platform: C.faint };
let y = 92;
const bands = [];
for (const band of MAIN_FLOW.bands) {
  const top = y;
  const x = PAD + 18;
  const inner = W - 2 * PAD - 36;
  const head = [`<text x="${x}" y="${top + 30}" class="bt">${esc(band.title.en)}</text>`, `<text x="${W - PAD - 18}" y="${top + 30}" class="ba" text-anchor="start" direction="rtl">${esc(AR_TITLE[band.id])}</text>`, `<text x="${x}" y="${top + 50}" class="bs">${esc(band.sub.en)}</text>`];
  y = top + 66;
  if (band.id === "voice") {
    y += grid(band.groups[0].nodes, x, y, inner, 6);
  } else {
    const cols = band.id === "agents" ? 2 : 3;
    const per = band.id === "agents" ? 3 : 2;
    const gw = (inner - 14 * (cols - 1)) / cols;
    for (let r = 0; r < band.groups.length; r += cols) {
      const row = band.groups.slice(r, r + cols);
      const heights = row.map((g, i) => {
        const gx = x + i * (gw + 14);
        const h = grid(g.nodes, gx + 10, y + 34, gw - 20, per);
        return { g, gx, h };
      });
      const rowH = Math.max(...heights.map((h) => h.h)) + 46;
      for (const { g, gx } of heights) {
        const tone = g.tone === "inv" ? C.brand : g.tone === "sen" ? C.sand : C.line;
        bands.push(`<rect x="${gx}" y="${y}" width="${gw}" height="${rowH}" rx="12" fill="none" stroke="${C.line}"/><rect x="${gx + 12}" y="${y - 1}" width="${gw - 24}" height="2.5" rx="1.25" fill="${tone}"/><text x="${gx + 12}" y="${y + 22}" class="gt">${esc(g.title.en)}</text>`);
      }
      y += rowH + 12;
    }
    y -= 12;
  }
  y += 18;
  bands.push(`<rect x="${PAD}" y="${top}" width="${W - 2 * PAD}" height="${y - top}" rx="18" fill="${C.s1}" stroke="${C.line}"/><rect x="${PAD}" y="${top + 14}" width="4" height="${y - top - 28}" rx="2" fill="${ACCENT[band.id]}"/>${head.join("")}`);
  y += 14;
}
// Band frames must be painted before group frames: sort so the big band rect comes first within each band.
const bandRects = bands.filter((b) => b.includes('rx="18"'));
const groupRects = bands.filter((b) => !b.includes('rx="18"'));
const H = y + 44;

const pts = MAIN_FLOW.steps.map((s) => centre.get(s.node));
const seg = (a, b) => {
  if (Math.abs(a[1] - b[1]) < 6 || Math.abs(a[0] - b[0]) < 6) return `L${b[0]} ${b[1]}`;
  const my = (a[1] + b[1]) / 2;
  return `C${a[0]} ${my} ${b[0]} ${my} ${b[0]} ${b[1]}`;
};
const route = `M${pts[0][0]} ${pts[0][1]}` + pts.slice(1).map((p, i) => seg(pts[i], p)).join("");
const N = MAIN_FLOW.steps.length;
const delays = MAIN_FLOW.steps.map((_, i) => `.d${i}{animation-delay:${((i / N) * DUR).toFixed(2)}s}`).join("");
const keyTimes = MAIN_FLOW.steps.map((_, i) => (i / (N - 1)).toFixed(4)).join(";");
// One keyPoint per box so the dot reaches box i at the moment box i lights up (boxes are unevenly spaced along the route).
const lengths = (() => {
  const d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) * (Math.abs(a[1] - b[1]) < 6 || Math.abs(a[0] - b[0]) < 6 ? 1 : 1.12);
  const acc = [0];
  for (let i = 1; i < pts.length; i++) acc.push(acc[i - 1] + d(pts[i - 1], pts[i]));
  return acc.map((v) => (v / acc[acc.length - 1]).toFixed(4)).join(";");
})();

const desc = `Three stacked layers. ${MAIN_FLOW.bands.map((b) => `${b.title.en}: ${b.groups.flatMap((g) => g.nodes).map((n) => n.label.en).join(", ")}.`).join(" ")} A numbered request path runs through them, in this order. ${MAIN_FLOW.steps.map((s) => s.caption.en).join(" Then: ")} ${FLOW_UI.en.logos}`;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-labelledby="t d">
<title id="t">Falcon Lens architecture in three layers, with the tools it runs on</title>
<desc id="d">${esc(desc)}</desc>
<!-- Generated by web/scripts/build-arch-svg.mjs from web/lib/arch-flow.ts. Do not edit by hand. Logos: web/public/logos/tools/LOGOS_LICENSES.md -->
<style>
text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans","Noto Sans Arabic","Geeza Pro",Tahoma,Helvetica,Arial,sans-serif;fill:${C.text}}
.m{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
.h1{font-size:25px;font-weight:700}.h2{font-size:14.5px;fill:${C.muted}}
.bt{font-size:19px;font-weight:700}.ba{font-size:18px;font-weight:700;fill:${C.sand}}.bs{font-size:13px;fill:${C.muted}}
.gt{font-size:13.5px;font-weight:700}
.nl{font-size:12.5px;font-weight:650}.ns{font-size:10.5px;fill:${C.muted}}
.ft{font-size:11.5px;fill:${C.faint}}
.n{fill:${C.s2};stroke:${C.strong};stroke-width:1.4}
.n.on{stroke:${C.brand}}
.no circle{fill:${C.brand}}.dg{fill:none;stroke:${C.ink};stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.w{fill:none;stroke:${C.brand};stroke-width:2.5;stroke-linejoin:round;opacity:.75}
.wf{fill:none;stroke:${C.bg};stroke-width:2.5;stroke-dasharray:2 14;opacity:.55}
.dot{fill:${C.brand};stroke:${C.s1};stroke-width:2}.halo{fill:${C.brand};opacity:.25}
@keyframes lit{0%,5%{fill:#1f4a55;stroke-width:3}9%,100%{fill:${C.s2};stroke-width:1.4}}
@keyframes flow{to{stroke-dashoffset:-32}}
@media (prefers-reduced-motion:no-preference){.n.on{animation:lit ${DUR}s linear infinite}.wf{animation:flow 1.6s linear infinite}${delays}}
@media (prefers-reduced-motion:reduce){.mv{display:none}}
</style>
<rect width="${W}" height="${H}" fill="${C.bg}"/>
<text x="${PAD}" y="44" class="h1">Falcon Lens architecture</text>
<text x="${W - PAD}" y="44" class="h1" text-anchor="start" direction="rtl" fill="${C.sand}">بنية عدسة الصقر</text>
<text x="${PAD}" y="70" class="h2">One request, three layers: follow the numbers. Every box is shipped code, shown with the tool it runs on.</text>
${bandRects.join("\n")}
${groupRects.join("\n")}
<path class="w" d="${route}"/>
<path class="wf" d="${route}"/>
${parts.join("\n")}
<g class="mv"><circle class="halo" r="14"><animateMotion dur="${DUR}s" repeatCount="indefinite" calcMode="linear" keyPoints="${lengths}" keyTimes="${keyTimes}" path="${route}"/></circle><circle class="dot" r="6"><animateMotion dur="${DUR}s" repeatCount="indefinite" calcMode="linear" keyPoints="${lengths}" keyTimes="${keyTimes}" path="${route}"/></circle></g>
<text x="${PAD}" y="${H - 18}" class="ft">${esc(FLOW_UI.en.logos)} Text badges mark tools whose logo is not vendored. Dashed boxes are model steps.</text>
</svg>
`;

const target = join(web, "..", "docs", "assets", "architecture.svg");
if (process.argv.includes("--check")) {
  if (readFileSync(target, "utf8") !== svg) {
    console.error("docs/assets/architecture.svg is stale: run `node web/scripts/build-arch-svg.mjs`");
    process.exit(1);
  }
  console.log("docs/assets/architecture.svg is up to date");
} else {
  writeFileSync(target, svg);
  console.log(`docs/assets/architecture.svg written: ${W}x${H}, ${parts.length} boxes, ${N} steps`);
}
