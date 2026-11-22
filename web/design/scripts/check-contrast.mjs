#!/usr/bin/env node
// Checks web/design/tokens.css: WCAG 2.x contrast for every text/background pair the
// design system allows, verdict-colour separation under simulated colour-vision
// deficiency, and parity of the two light-theme blocks. No dependencies.
// Usage: node web/design/scripts/check-contrast.mjs [--json]
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "tokens.css"), "utf8");

function block(startMarker) {
  const start = css.indexOf(startMarker);
  if (start < 0) throw new Error(`block not found: ${startMarker}`);
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i);
  }
  throw new Error(`unterminated block: ${startMarker}`);
}
function hexTokens(text) {
  const out = {};
  for (const m of text.matchAll(/(--fl-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) out[m[1]] = m[2].toLowerCase();
  return out;
}

const dark = hexTokens(block(":root {"));
const lightExplicit = hexTokens(block(':root[data-theme="light"]'));
const lightSystem = hexTokens(block(":root:not([data-theme])"));
const light = { ...dark, ...lightExplicit };

const toLin = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lum = (h) => { const [r, g, b] = rgb(h).map(toLin); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

// [foreground, background, minimum ratio]. 4.5 = AA body text, 3 = AA large text / UI component.
const PAIRS = [
  ["text", "bg", 4.5], ["text", "surface-1", 4.5], ["text", "surface-2", 4.5], ["text", "surface-3", 4.5],
  ["text-muted", "bg", 4.5], ["text-muted", "surface-1", 4.5], ["text-muted", "surface-2", 4.5],
  ["text-faint", "bg", 4.5], ["text-faint", "surface-1", 4.5], ["text-faint", "surface-2", 4.5],
  ["brand", "bg", 4.5], ["brand", "surface-1", 4.5], ["brand", "surface-2", 4.5],
  ["brand-ink", "brand", 4.5], ["focus", "bg", 3], ["focus", "surface-1", 3],
  ["border-strong", "bg", 3], ["border-strong", "surface-1", 3], ["border-strong", "surface-2", 3],
  ...["dangerous", "suspicious", "nws"].flatMap((v) => [
    [`${v}-fg`, "bg", 4.5], [`${v}-fg`, "surface-1", 4.5], [`${v}-fg`, "surface-2", 4.5],
    [`${v}-fg`, `${v}-tint`, 4.5], ["text", `${v}-tint`, 4.5], ["text-muted", `${v}-tint`, 4.5],
    [`${v}-on`, `${v}-solid`, 4.5],
  ]),
  ["sev-high", "surface-1", 4.5], ["sev-high", "surface-2", 4.5],
];

// Colour-vision-deficiency simulation, Machado, Oliveira & Fernandes (2009), severity 1.0,
// applied in linear RGB. Used to confirm the three verdict hues stay apart; the real
// guarantee is that colour is never the only carrier (icon shape + word are mandatory).
const CVD = {
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  tritanopia: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
};
const clamp01 = (x) => Math.min(1, Math.max(0, x));
function lab(linRgb) {
  const [r, g, b] = linRgb;
  const xyz = [
    (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047,
    0.2126729 * r + 0.7151522 * g + 0.072175 * b,
    (0.0193339 * r + 0.119192 * g + 0.9503041 * b) / 1.08883,
  ].map((t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116));
  return [116 * xyz[1] - 16, 500 * (xyz[0] - xyz[1]), 200 * (xyz[1] - xyz[2])];
}
function simulate(hex, m) {
  const l = rgb(hex).map(toLin);
  return m ? m.map((row) => clamp01(row[0] * l[0] + row[1] * l[1] + row[2] * l[2])) : l;
}
const deltaE = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); // CIE76
const MIN_DELTA_E = 20;

const results = { contrast: [], cvd: [], parity: [] };
let failed = 0;

for (const [themeName, t] of [["dark", dark], ["light", light]]) {
  for (const [fg, bg, min] of PAIRS) {
    const a = t[`--fl-${fg}`], b = t[`--fl-${bg}`];
    if (!a || !b) { failed++; results.contrast.push({ theme: themeName, fg, bg, error: "missing token" }); continue; }
    const r = ratio(a, b);
    const ok = r >= min;
    if (!ok) failed++;
    results.contrast.push({ theme: themeName, fg, bg, fgHex: a, bgHex: b, ratio: Number(r.toFixed(2)), min, ok });
  }
  for (const role of ["fg", "solid"]) {
    for (const [kind, m] of [["normal", null], ...Object.entries(CVD)]) {
      const c = ["dangerous", "suspicious", "nws"].map((v) => lab(simulate(t[`--fl-${v}-${role}`], m)));
      const pairs = { "dangerous|suspicious": deltaE(c[0], c[1]), "dangerous|nws": deltaE(c[0], c[2]), "suspicious|nws": deltaE(c[1], c[2]) };
      const minDE = Math.min(...Object.values(pairs));
      const ok = minDE >= MIN_DELTA_E;
      if (!ok) failed++;
      results.cvd.push({ theme: themeName, role, vision: kind, minDeltaE: Number(minDE.toFixed(1)), ok });
    }
  }
}

for (const key of new Set([...Object.keys(lightExplicit), ...Object.keys(lightSystem)])) {
  if (lightExplicit[key] !== lightSystem[key]) {
    failed++;
    results.parity.push({ token: key, explicit: lightExplicit[key] ?? null, system: lightSystem[key] ?? null });
  }
}

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(results, null, 2));
} else {
  for (const r of results.contrast) {
    console.log(`${r.ok ? "ok  " : "FAIL"} ${r.theme.padEnd(5)} ${String(r.ratio ?? "-").padStart(5)} (>= ${r.min})  ${r.fg} on ${r.bg}  ${r.fgHex ?? ""} ${r.bgHex ?? r.error}`);
  }
  for (const r of results.cvd) {
    console.log(`${r.ok ? "ok  " : "FAIL"} ${r.theme.padEnd(5)} verdict ${r.role.padEnd(5)} ${r.vision.padEnd(12)} min dE76 ${r.minDeltaE} (>= ${MIN_DELTA_E})`);
  }
  for (const r of results.parity) console.log(`FAIL light-theme blocks differ: ${r.token} ${r.explicit} vs ${r.system}`);
  const worst = (theme) => Math.min(...results.contrast.filter((r) => r.theme === theme && r.min === 4.5).map((r) => r.ratio));
  console.log(`\n${results.contrast.length} contrast pairs, ${results.cvd.length} CVD checks; lowest body-text ratio dark ${worst("dark")}, light ${worst("light")}; failures: ${failed}`);
}
process.exit(failed ? 1 : 0);
