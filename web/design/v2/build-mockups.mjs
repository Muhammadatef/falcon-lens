#!/usr/bin/env node
// Web v2 design mockups (static, self-contained HTML; a design artefact, not app code).
//   node web/design/v2/build-mockups.mjs          writes mockups/*.html and COPY.md
//   node web/design/v2/render-shots.mjs           renders shots/*.png (needs Playwright)
//
// Truthfulness rules this generator enforces, so the mockups cannot drift from them:
//   * every metric is read from web/lib/results.generated.json (no number is typed here);
//   * every Live / In progress badge is read from web/lib/capabilities.generated.json, plus the
//     flags IMPLEMENTATION_TASKS W2-01 adds, probed live from scripts/submission/capabilities.py
//     (a flag that cannot be read counts as "in progress");
//   * reporting channels are read from config/reporting_channels.yaml;
//   * check results and the Sentinel ticker use the invented "Falcon Demo Bank" fixture and wear
//     the DEMO DATA label;
//   * no external request: fonts are the self-hosted files in web/public/fonts, tokens are
//     inlined from web/design/tokens.css.
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "..");
const repo = join(web, "..");
const read = (p) => readFileSync(p, "utf8");

const COPY = JSON.parse(read(join(here, "copy.json")));
const results = JSON.parse(read(join(web, "lib", "results.generated.json")));
const caps = JSON.parse(read(join(web, "lib", "capabilities.generated.json")));
const tokens = read(join(web, "design", "tokens.css"));

// Flags proposed in W2-01 (not yet in capabilities.generated.json): probe them the same way
// web/scripts/sync-results.mjs does. Unreadable = false = "In progress".
const EXTRA = ["sentinel_agent", "rest_api", "mcp", "stix"];
try {
  const py = `
import json, sys
sys.path.insert(0, "scripts/submission")
import capabilities as c
want = ${JSON.stringify(EXTRA)}
print(json.dumps({cap.id: all(c.probe(c.ROOT, s) for s in cap.probes if not s.startswith("gate:")) for cap in c.CAPABILITIES if cap.id in want}))`;
  Object.assign(caps, JSON.parse(execFileSync("python3", ["-c", py], { cwd: repo, encoding: "utf8" })));
} catch {
  for (const id of EXTRA) caps[id] ??= false;
}

// Demo fixture (web/lib/demo.ts): the ticker counts and check latencies shown under the DEMO DATA
// label are read from it, not typed here.
const demoTs = read(join(web, "lib", "demo.ts"));
const demoCampaigns = [...demoTs.matchAll(/campaign_id: "[^"]+", severity: "\w+", count: (\d+)[\s\S]*?title: \{ ar: "([^"]+)", en: "([^"]+)" \}/g)].map((m) => ({ count: Number(m[1]), ar: m[2], en: m[3] }));
const demoLatency = [...demoTs.matchAll(/^  latency_ms: (\d+),/gm)].map((m) => Number(m[1]));
if (demoCampaigns.length === 0 || demoLatency.length < 2) throw new Error("demo fixture not readable");

// Reporting channels (tiny YAML subset: the file is flat and ours).
const channelsYaml = read(join(repo, "config", "reporting_channels.yaml"));
const retrievedAt = /retrieved_at:\s*(\S+)/.exec(channelsYaml)?.[1] ?? "";
const channels = [...channelsYaml.matchAll(/- id: (\w+)\s+label_en: "([^"]+)"\s+label_ar: "([^"]+)"\s+value: "([^"]+)"/g)].map((m) => ({ en: m[2], ar: m[3], value: m[4] }));

// ── helpers ───────────────────────────────────────────────────────────────
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const M = results.available ? results.data.metrics : null;
const pct = (v) => `${(v * 100).toFixed(1)}%`;
const metric = (key) => (M && typeof M[key] === "number" ? M[key] : null);
const ci = (key) => (M && Array.isArray(M[`${key}_ci95`]) ? M[`${key}_ci95`] : null);

function makeT(lang) {
  return (key, vars = {}) => {
    const entry = COPY[key];
    if (!entry) throw new Error(`missing copy key: ${key}`);
    return esc(entry[lang].replace(/\{([\w.]+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`)));
  };
}

const ICONS = {
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  message: '<path d="M4 5h16v11H9l-5 4z"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  image: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM20 14v7M14 20h3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11m0-1V4.5a1.5 1.5 0 0 1 3 0V11m0-4.5a1.5 1.5 0 0 1 3 0V14c0 4-2.5 7-6.5 7-3 0-4.5-1.5-6-4l-2-3.5a1.5 1.5 0 0 1 2.6-1.5L8 13.5"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  flag: '<path d="M5 21V4h13l-2 4.5 2 4.5H5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  scale: '<path d="M12 4v16M6 20h12M5 8h14M5 8l-3 7a3 3 0 0 0 6 0zM19 8l-3 7a3 3 0 0 0 6 0z"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  plug: '<path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2zM4 21a2 2 0 0 0 2 2h14"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  lock: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/>',
  chart: '<path d="M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-8"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12 18.5 5.5"/><circle cx="12" cy="12" r="1" fill="currentColor"/>',
  lens: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/><path d="M12 3v5.5M21 12h-5.5M12 21v-5.5M3 12h5.5"/>',
};
const icon = (name, size = 22, cls = "") => `<svg class="ic ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

const VICON = {
  dangerous: '<path d="M8.2 2.5h7.6l5.7 5.7v7.6l-5.7 5.7H8.2l-5.7-5.7V8.2z"/><path d="M12 7v6M12 16.5v.01"/>',
  suspicious: '<path d="M12 3 22 20H2z"/><path d="M10.3 10.5a1.9 1.9 0 1 1 2.6 1.8c-.6.3-.9.7-.9 1.4M12 16.8v.01"/>',
  nws: '<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="4.5"/><path d="M9.5 12h5"/>',
};
const vicon = (v, size = 44) => `<svg class="ic" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${VICON[v]}</svg>`;

const brandMark = (size = 34) => `<svg width="${size}" height="${size}" viewBox="0 0 36 36" fill="none" aria-hidden="true"><path d="M5 10.5c5-5.5 16-7 26-2.5" stroke="var(--fl-sand)" stroke-width="3" stroke-linecap="round"/><circle cx="18" cy="18" r="9" stroke="var(--fl-brand)" stroke-width="3"/><circle cx="18" cy="18" r="3.6" fill="var(--fl-text)"/><path d="M14.5 28.5c-.6 2.6-2 4.6-4 6" stroke="var(--fl-sand)" stroke-width="3" stroke-linecap="round"/></svg>`;

// The lens (Investigator). Same geometry as web/components/Lens.tsx.
const polar = (r, deg) => [200 + r * Math.sin((deg * Math.PI) / 180), 200 - r * Math.cos((deg * Math.PI) / 180)];
const fx = (n) => n.toFixed(1);
function lens({ state = "idle", verdict = null, tiers = [], cls = "" } = {}) {
  const aperture = { idle: 78, scanning: 50, locked: 66 }[state];
  const arcs = [0, 1, 2, 3].map((i) => {
    const [x0, y0] = polar(170, i * 90 + 7);
    const [x1, y1] = polar(170, i * 90 + 83);
    return `<path class="lens-arc" data-status="${tiers[i] ?? "pending"}" d="M${fx(x0)} ${fx(y0)}A170 170 0 0 1 ${fx(x1)} ${fx(y1)}"/>`;
  });
  const blades = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => {
    const rv = aperture / Math.cos(Math.PI / 8);
    const twist = 34 + (78 - aperture) * 0.9;
    const a0 = i * 45 + 22.5;
    const pts = [polar(rv, a0), polar(rv, a0 + 45), polar(141, a0 + 45 + twist), polar(141, a0 + twist)];
    return `<polygon class="lens-blade" points="${pts.map(([x, y]) => `${fx(x)},${fx(y)}`).join(" ")}"/>`;
  });
  const core = verdict ? `<g class="lens-core" transform="translate(152 152) scale(4)">${VICON[verdict]}</g>` : "";
  return `<svg class="lens ${cls}" data-state="${state}" ${verdict ? `data-verdict="${verdict}"` : ""} viewBox="0 0 400 400" aria-hidden="true">
<defs><radialGradient id="g" cx="42%" cy="38%" r="70%"><stop offset="0" stop-color="#1b2a4a"/><stop offset=".6" stop-color="#070b14"/><stop offset="1" stop-color="#020409"/></radialGradient></defs>
<circle class="lens-halo" cx="200" cy="200" r="200"/><circle class="lens-ticks" cx="200" cy="200" r="190"/>
${arcs.join("")}<circle class="lens-ring" cx="200" cy="200" r="152"/><circle cx="200" cy="200" r="141" fill="url(#g)"/><circle class="lens-tint" cx="200" cy="200" r="141"/>
${blades.join("")}${state !== "locked" ? '<path class="lens-sweep" d="M200 200 200 62A138 138 0 0 1 300 105z"/>' : ""}
<path class="lens-brow" d="M52 86C120 22 262 6 372 78"/>${core}</svg>`;
}

// The radar (Sentinel): the same instrument, turned to watch.
function radar(cls = "") {
  const dots = [[150, 120, 5], [165, 138, 4], [140, 142, 4], [258, 230, 5], [272, 214, 4], [250, 250, 4], [262, 246, 3], [120, 270, 4]];
  return `<svg class="radar ${cls}" viewBox="0 0 400 400" aria-hidden="true">
<circle class="radar-halo" cx="200" cy="200" r="200"/>
${[60, 110, 160].map((r) => `<circle class="radar-ring" cx="200" cy="200" r="${r}"/>`).join("")}
<path class="radar-ring" d="M200 30v340M30 200h340"/>
<path class="radar-sweep" d="M200 200 200 40A160 160 0 0 1 338 120z"/>
<path class="radar-link" d="M150 120 165 138 140 142zM258 230 272 214M258 230 250 250 262 246"/>
${dots.map(([x, y, r]) => `<circle class="radar-dot" cx="${x}" cy="${y}" r="${r}"/>`).join("")}
<circle class="radar-core" cx="200" cy="200" r="7"/></svg>`;
}

const CSS = `
@font-face{font-family:"Readex Pro";src:url("../../../public/fonts/readex-pro-arabic-wght-normal.woff2") format("woff2");font-weight:160 700;unicode-range:U+0600-06FF,U+0750-077F,U+0870-088E,U+0890-0891,U+0898-08E1,U+08E3-08FF,U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FE74,U+FE76-FEFC}
@font-face{font-family:"Readex Pro";src:url("../../../public/fonts/readex-pro-latin-wght-normal.woff2") format("woff2");font-weight:160 700;unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:"JetBrains Mono";src:url("../../../public/fonts/jetbrains-mono-latin-wght-normal.woff2") format("woff2");font-weight:100 800}
*{box-sizing:border-box}
html{color-scheme:dark}
body{margin:0;background:var(--fl-bg);color:var(--fl-text);font-family:var(--fl-font-ui);font-size:var(--fl-text-md);line-height:var(--fl-leading);overflow-x:hidden}
h1,h2,h3,p,ul,ol,dl,dd{margin:0;padding:0}ul,ol{list-style:none}a{color:inherit}
.mono{font-family:var(--fl-font-mono);direction:ltr;unicode-bidi:isolate}
.wrap{max-width:var(--fl-content-max);margin-inline:auto;padding-inline:var(--fl-gutter)}
.ic{flex:none}
[dir=rtl] .flip{transform:scaleX(-1)}
.lattice{position:absolute;inset:0 0 auto 0;height:46rem;pointer-events:none;background:var(--fl-text);opacity:.045;
 -webkit-mask-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='72' height='72' fill='none' stroke='black' stroke-width='1'%3E%3Crect x='22' y='22' width='28' height='28'/%3E%3Crect x='22' y='22' width='28' height='28' transform='rotate(45 36 36)'/%3E%3Cpath d='M36 0v16M36 56v16M0 36h16M56 36h16'/%3E%3C/svg%3E"),linear-gradient(to bottom,black 0,transparent 100%);-webkit-mask-size:72px 72px,100% 100%;-webkit-mask-composite:source-in;mask-composite:intersect}
.glow{position:absolute;inset:0 0 auto 0;height:40rem;pointer-events:none;background:radial-gradient(60rem 28rem at 20% -10%,rgb(63 224 197/.10),transparent 60%),radial-gradient(50rem 26rem at 90% 0,rgb(231 215 182/.06),transparent 60%)}
[dir=ltr] .glow{transform:scaleX(-1)}
main{position:relative}

/* header */
.top{position:sticky;top:0;z-index:5;background:rgb(7 11 20/.92);border-block-end:1px solid var(--fl-border)}
.top-in{display:flex;align-items:center;gap:var(--fl-space-4);min-height:3.75rem}
.brand{white-space:nowrap;display:flex;align-items:center;gap:.6rem;font-weight:650;font-size:1.2rem;text-decoration:none;line-height:1.1}
.brand small{display:block;font-size:.62rem;letter-spacing:.18em;color:var(--fl-text-faint);font-weight:500}
.nav{display:none;gap:.25rem;margin-inline-start:auto}
.nav a{padding:.5rem .8rem;border-radius:var(--fl-radius-pill);text-decoration:none;color:var(--fl-text-muted);font-size:var(--fl-text-sm);white-space:nowrap}
.nav a[aria-current]{color:var(--fl-text);background:var(--fl-surface-2);box-shadow:inset 0 -2px 0 var(--fl-brand)}
.tools{display:flex;gap:.4rem;margin-inline-start:auto}
.tool{display:inline-flex;align-items:center;gap:.4rem;min-height:2.75rem;padding:0 .8rem;border-radius:var(--fl-radius-md);border:1px solid var(--fl-border-strong);background:transparent;color:var(--fl-text);font:inherit;font-size:var(--fl-text-sm)}
.tool.sq{padding:0;width:2.75rem;justify-content:center;display:none}
.ribbon{background:repeating-linear-gradient(-45deg,var(--fl-suspicious-tint) 0 12px,#1f1606 12px 24px);color:var(--fl-suspicious-fg);border-block-end:1px dashed var(--fl-suspicious-line);text-align:center;font-size:var(--fl-text-sm);font-weight:500;padding:.35rem 1rem}

/* shared */
.eyebrow{display:inline-flex;align-items:center;gap:.5rem;color:var(--fl-brand);font-weight:500;font-size:var(--fl-text-sm)}
.eyebrow::before{content:"";width:1.5rem;height:2px;background:currentColor;border-radius:2px}
.h1{font-size:var(--fl-text-3xl);line-height:var(--fl-leading-tight);font-weight:650;text-wrap:balance}
.h2{font-size:clamp(1.6rem,1.2rem + 1.6vw,2.4rem);line-height:var(--fl-leading-tight);font-weight:650;text-wrap:balance}
.h3{font-size:var(--fl-text-lg);line-height:1.4;font-weight:650}
.lead{color:var(--fl-text-muted);font-size:var(--fl-text-md);max-width:var(--fl-read-max)}
.muted{color:var(--fl-text-muted)}.faint{color:var(--fl-text-faint);font-size:var(--fl-text-sm)}
.card{background:var(--fl-surface-1);border:1px solid var(--fl-border);border-radius:var(--fl-radius-lg);padding:var(--fl-space-5)}
.sec{padding-block:var(--fl-space-7)}
.sec-head{display:grid;gap:var(--fl-space-2);margin-block-end:var(--fl-space-5)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.6rem;min-height:3.5rem;padding:0 1.5rem;border-radius:var(--fl-radius-md);background:var(--fl-brand);color:var(--fl-brand-ink);font:inherit;font-size:var(--fl-text-lg);font-weight:650;border:0;text-decoration:none}
.btn.ghost{background:transparent;color:var(--fl-text);border:1px solid var(--fl-border-strong);min-height:3rem;font-size:var(--fl-text-md);font-weight:500}
.more{display:inline-flex;align-items:center;gap:.35rem;color:var(--fl-brand);font-weight:500;text-decoration:underline;text-underline-offset:.3em;min-height:3rem}
.cap{display:inline-flex;align-items:center;gap:.4rem;font-size:.8125rem;font-weight:500;padding:.1rem .6rem;border-radius:var(--fl-radius-pill);white-space:nowrap;line-height:1.7}
.cap i{width:.5rem;height:.5rem;border-radius:50%}
.cap[data-live=true]{color:var(--fl-brand);border:1px solid var(--fl-brand)}.cap[data-live=true] i{background:var(--fl-brand)}
.cap[data-live=false]{color:var(--fl-suspicious-fg);border:1px dashed var(--fl-suspicious-fg)}.cap[data-live=false] i{border:1.5px solid currentColor}
.demo{display:inline-flex;font-size:.75rem;font-weight:500;letter-spacing:.04em;padding:.05rem .5rem;border:1px dashed var(--fl-suspicious-fg);color:var(--fl-suspicious-fg);border-radius:var(--fl-radius-sm);white-space:nowrap}

/* lens + radar */
.lens,.radar{display:block;width:100%;height:auto;overflow:visible;--lens-c:var(--fl-brand)}
.lens[data-verdict=dangerous]{--lens-c:var(--fl-dangerous-fg)}.lens[data-verdict=nws]{--lens-c:var(--fl-nws-fg)}
.lens-halo{fill:var(--lens-c);opacity:.1}.lens[data-state=locked] .lens-halo{opacity:.2}
.lens-ticks{fill:none;stroke:var(--fl-text-faint);stroke-width:5;stroke-dasharray:1.5 8.448;opacity:.55}
.lens-arc{fill:none;stroke:var(--fl-border);stroke-width:7;stroke-linecap:round}
.lens-arc[data-status=done]{stroke:var(--lens-c)}.lens-arc[data-status=running]{stroke:var(--lens-c);opacity:.45}.lens-arc[data-status=skipped]{stroke-dasharray:2 12}
.lens-ring{fill:none;stroke:var(--fl-border-strong);stroke-width:1.5}
.lens-tint{fill:var(--lens-c);opacity:0}.lens[data-state=locked] .lens-tint{opacity:.3}
.lens-blade{fill:var(--fl-surface-2);stroke:var(--fl-border-strong);stroke-width:1.2;stroke-linejoin:round}.lens-blade:nth-of-type(odd){fill:var(--fl-surface-1)}
.lens-sweep{fill:var(--lens-c);opacity:.22}
.lens-brow{fill:none;stroke:var(--fl-sand);stroke-width:9;stroke-linecap:round;opacity:.85}
.lens-core{fill:none;stroke:var(--lens-c);stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.lens.mini .lens-ticks,.lens.mini .lens-brow{display:none}.lens.mini .lens-arc{stroke-width:16}
.radar-halo{fill:var(--fl-sand);opacity:.07}.radar-ring{fill:none;stroke:var(--fl-sand);stroke-width:1.5;opacity:.35}
.radar-sweep{fill:var(--fl-sand);opacity:.16}.radar-dot{fill:var(--fl-sand)}.radar-link{fill:none;stroke:var(--fl-sand);stroke-width:1.5;opacity:.7}.radar-core{fill:var(--fl-sand)}

/* hero */
.hero{padding-block:var(--fl-space-5) var(--fl-space-6)}
.hero-grid{display:grid;gap:var(--fl-space-5)}
.hero-copy{display:grid;gap:var(--fl-space-3)}
.hero-top{display:flex;align-items:center;justify-content:space-between;gap:var(--fl-space-3)}
.hero-top .lens{width:3.5rem}
.sub-d{display:none}
.duo{display:none}
.box{display:grid;gap:var(--fl-space-3);padding:var(--fl-space-4);border-radius:var(--fl-radius-lg);background:var(--fl-surface-1);border:1px solid var(--fl-border-strong);box-shadow:var(--fl-shadow-2)}
.kinds{display:grid;grid-template-columns:repeat(4,1fr);gap:.25rem;padding:.25rem;background:var(--fl-surface-2);border-radius:var(--fl-radius-md)}
.kind{display:flex;flex-direction:column;align-items:center;gap:.1rem;min-height:3.25rem;justify-content:center;border-radius:10px;font-size:.8125rem;color:var(--fl-text-muted);line-height:1.3}
.kind[aria-selected=true]{background:var(--fl-bg);color:var(--fl-text);box-shadow:inset 0 0 0 1px var(--fl-border-strong);font-weight:500}
.field-l{font-weight:500;font-size:var(--fl-text-lg)}
.field{min-height:4.5rem;border-radius:var(--fl-radius-md);background:var(--fl-surface-2);border:1px solid var(--fl-border-strong);padding:.8rem 1rem;color:var(--fl-text-faint);font-family:var(--fl-font-mono);font-size:var(--fl-text-lg);direction:ltr;text-align:start}
.hint{font-size:var(--fl-text-sm);color:var(--fl-text-muted)}
.box .btn{width:100%}
.promise{display:flex;gap:.6rem;align-items:flex-start;color:var(--fl-text-muted);font-size:var(--fl-text-sm)}
.promise .ic{color:var(--fl-brand);margin-block-start:.2rem}
.chips{display:grid;gap:var(--fl-space-2)}
.achip{display:grid;grid-template-columns:2.5rem 1fr auto;align-items:center;gap:.75rem;padding:.6rem .9rem;border-radius:var(--fl-radius-md);background:var(--fl-surface-1);border:1px solid var(--fl-border)}
.achip b{display:block;font-weight:650;line-height:1.3}.achip span.r{font-size:var(--fl-text-sm);color:var(--fl-text-muted);line-height:1.4;display:block}
.achip .sub{grid-column:2/-1;display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;font-size:.8125rem;color:var(--fl-text-muted);border-block-start:1px solid var(--fl-border);padding-block-start:.45rem}
.glyph{width:2.5rem;height:2.5rem;border-radius:50%;display:grid;place-items:center;background:var(--fl-surface-2)}
.glyph.inv{color:var(--fl-brand)}.glyph.sen{color:var(--fl-sand)}

/* ticker */
.ticker{border-block:1px solid var(--fl-border);background:var(--fl-surface-1)}
.ticker-in{display:grid;gap:.35rem;padding-block:.9rem}
.ticker-l{display:flex;align-items:center;flex-wrap:wrap;gap:.5rem;font-weight:650;color:var(--fl-sand)}
.pulse{width:.6rem;height:.6rem;border-radius:50%;background:var(--fl-sand);box-shadow:0 0 0 4px rgb(231 215 182/.18)}
.ticker-t{color:var(--fl-text-muted);font-size:var(--fl-text-sm)}
.ticker-t b{color:var(--fl-text);font-weight:500}

/* grids */
.g4,.g3,.g2{display:grid;gap:var(--fl-space-4)}
.out{display:grid;gap:.4rem;align-content:start}
.out .ic{color:var(--fl-brand)}
.agent{display:grid;gap:var(--fl-space-3);align-content:start;position:relative;overflow:hidden}
.agent.inv{border-block-start:3px solid var(--fl-brand)}.agent.sen{border-block-start:3px solid var(--fl-sand)}
.agent-h{display:flex;align-items:center;gap:.9rem}
.agent-h .viz{width:4.5rem;flex:none}
.agent-k{font-size:var(--fl-text-sm);color:var(--fl-text-muted)}
.agent-n{font-size:var(--fl-text-xl);font-weight:650;line-height:1.3}
.agent-r{font-weight:500}.agent.inv .agent-r{color:var(--fl-brand)}.agent.sen .agent-r{color:var(--fl-sand)}
.statline{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;font-size:var(--fl-text-sm);color:var(--fl-text-muted)}
.principle{display:flex;gap:.75rem;align-items:center;margin-block-start:var(--fl-space-5);padding:var(--fl-space-4) var(--fl-space-5);border-radius:var(--fl-radius-lg);border:1px solid var(--fl-border-strong);font-size:var(--fl-text-lg);font-weight:650}
.principle .ic{color:var(--fl-sand)}

/* proof */
.proof{background:linear-gradient(180deg,var(--fl-surface-1),var(--fl-bg));border-block:1px solid var(--fl-border)}
.stat{display:grid;gap:.15rem;align-content:start;padding:var(--fl-space-5);border-radius:var(--fl-radius-lg);background:var(--fl-bg);border:1px solid var(--fl-border)}
.stat-v{font-family:var(--fl-font-mono);font-size:clamp(2.4rem,1.8rem + 2.4vw,3.5rem);font-weight:650;line-height:1.1;direction:ltr;unicode-bidi:isolate;text-align:start;color:var(--fl-text)}
[dir=rtl] .stat-v{text-align:end}
.stat-l{font-weight:650;font-size:var(--fl-text-lg);line-height:1.4}
.stat-c{font-size:var(--fl-text-sm);color:var(--fl-text-muted)}
.stat-m{font-size:var(--fl-text-sm);color:var(--fl-text-muted);margin-block-start:.3rem}
.src{display:flex;flex-wrap:wrap;gap:.3rem 1rem;align-items:center;margin-block-start:var(--fl-space-4);font-size:var(--fl-text-sm);color:var(--fl-text-muted)}
.bandc{display:grid;gap:var(--fl-space-4);align-items:center;border:1px dashed var(--fl-border-strong);background:var(--fl-surface-1)}
.bandc .ic{color:var(--fl-sand)}

/* footer */
.foot{border-block-start:1px solid var(--fl-border);padding-block:var(--fl-space-6);color:var(--fl-text-muted);font-size:var(--fl-text-sm);display:grid;gap:var(--fl-space-3)}
.foot nav{display:flex;flex-wrap:wrap;gap:.25rem 1.25rem}.foot nav a{min-height:2.5rem;display:inline-flex;align-items:center}

/* check */
.page{padding-block:var(--fl-space-5) var(--fl-space-7)}
.page-h{display:flex;justify-content:space-between;align-items:center;gap:var(--fl-space-3);margin-block-end:var(--fl-space-4)}
.page-h h1{font-size:var(--fl-text-xl);font-weight:650}
.case{display:grid;grid-template-columns:4rem 1fr;gap:var(--fl-space-3);align-items:center;margin-block-end:var(--fl-space-4);padding:var(--fl-space-4)}
.case .url{display:block;padding:.5rem .75rem;border-radius:var(--fl-radius-sm);background:var(--fl-surface-2);border:1px solid var(--fl-border-strong);font-size:var(--fl-text-sm);overflow-wrap:anywhere;text-align:start}
.case .url b{font-weight:650;color:var(--fl-text)}
.cgrid{display:grid;gap:var(--fl-space-4)}
.activity{display:grid;gap:var(--fl-space-3);align-content:start}
.activity-h{display:flex;gap:.75rem;align-items:center}
.activity-h .h3{line-height:1.5}
.steps{display:grid;gap:0;position:relative}
.step{display:grid;grid-template-columns:1.5rem 1fr auto;gap:.75rem;align-items:start;padding-block:.55rem;position:relative}
.step:not(:last-child)::after{content:"";position:absolute;inset-inline-start:.72rem;top:1.9rem;bottom:-.45rem;width:2px;background:var(--fl-border)}
.dot{width:1rem;height:1rem;border-radius:50%;margin:.45rem .25rem 0;border:2px solid var(--fl-border-strong);background:var(--fl-bg)}
.step[data-st=done] .dot{background:var(--fl-brand);border-color:var(--fl-brand)}
.step[data-st=running] .dot{border-color:var(--fl-brand);box-shadow:0 0 0 5px rgb(63 224 197/.2)}
.step[data-st=skipped] .dot{border-style:dashed}
.step[data-st=pending] .st-t,.step[data-st=skipped] .st-t{color:var(--fl-text-muted)}
.st-t{font-weight:500;line-height:1.6}
.st-s{font-size:var(--fl-text-sm);color:var(--fl-text-muted);white-space:nowrap;padding-block-start:.15rem}
.step[data-st=running] .st-s{color:var(--fl-brand)}
.shim{height:.7rem;border-radius:1rem;background:linear-gradient(90deg,var(--fl-surface-2),var(--fl-surface-3),var(--fl-surface-2));margin-block-start:.4rem;width:70%}
.prov{display:flex;gap:.6rem;align-items:center;padding:.7rem 1rem;border-radius:var(--fl-radius-md);background:var(--fl-suspicious-tint);border:1px solid var(--fl-suspicious-line);color:var(--fl-suspicious-fg);font-weight:500}
.wait{display:flex;gap:.6rem;align-items:center;font-size:var(--fl-text-lg);font-weight:650}
.sen-note{display:flex;gap:.6rem;align-items:flex-start;font-size:var(--fl-text-sm);color:var(--fl-text-muted);border-block-start:1px solid var(--fl-border);padding-block-start:var(--fl-space-3)}
.sen-note .ic{color:var(--fl-sand);margin-block-start:.2rem}
.verdict{border-radius:var(--fl-radius-lg);border:1px solid var(--v-line);overflow:hidden;background:var(--fl-surface-1)}
.verdict[data-v=dangerous]{--v-fg:var(--fl-dangerous-fg);--v-solid:var(--fl-dangerous-solid);--v-on:var(--fl-dangerous-on);--v-tint:var(--fl-dangerous-tint);--v-line:var(--fl-dangerous-line)}
.verdict[data-v=nws]{--v-fg:var(--fl-nws-fg);--v-solid:var(--fl-nws-solid);--v-on:var(--fl-nws-on);--v-tint:var(--fl-nws-tint);--v-line:var(--fl-nws-line)}
.plate{display:flex;gap:var(--fl-space-4);align-items:center;padding:var(--fl-space-5);background:var(--v-solid);color:var(--v-on);border-block-end:3px solid var(--v-fg)}
.plate-w{font-size:var(--fl-text-2xl);font-weight:650;line-height:1.25}
.plate-s{font-size:var(--fl-text-lg);font-weight:500;line-height:1.5}
.vbody{display:grid;gap:var(--fl-space-5);padding:var(--fl-space-5);background:linear-gradient(to bottom,var(--v-tint),transparent 14rem)}
.imp{display:flex;gap:.5rem;align-items:center;color:var(--v-fg);font-weight:500}
.reasons{display:grid;gap:var(--fl-space-3);counter-reset:r}
.reason{display:grid;grid-template-columns:2.25rem 1fr;gap:.75rem;align-items:start;font-size:var(--fl-text-lg);line-height:1.6;padding:var(--fl-space-3) var(--fl-space-4);border-radius:var(--fl-radius-md);background:var(--fl-surface-1);border:1px solid var(--fl-border)}
.reason::before{counter-increment:r;content:counter(r);display:grid;place-items:center;width:2.1rem;height:2.1rem;border-radius:50%;border:1.5px solid var(--v-fg);color:var(--v-fg);font-family:var(--fl-font-mono);font-size:1rem}
.caution{display:grid;grid-template-columns:auto 1fr;gap:.75rem;padding:var(--fl-space-4);border-radius:var(--fl-radius-md);border:1px dashed var(--fl-suspicious-line);background:var(--fl-suspicious-tint)}
.caution .ic{color:var(--fl-suspicious-fg)}
.acts{display:grid;gap:var(--fl-space-4)}
.act{padding:var(--fl-space-4) var(--fl-space-5);border-radius:var(--fl-radius-md);background:var(--fl-surface-1);border:1px solid var(--fl-border);display:grid;gap:.6rem;align-content:start}
.act.now{border-inline-start:4px solid var(--fl-brand)}
.act h3{display:flex;gap:.6rem;align-items:center;font-size:var(--fl-text-lg);font-weight:650;line-height:1.4}
.act.now h3 .ic{color:var(--fl-brand)}
.act li{position:relative;padding-inline-start:1.25rem;font-size:var(--fl-text-lg);line-height:1.6}
.act li::before{content:"";position:absolute;inset-inline-start:0;top:.75em;width:.45rem;height:.45rem;transform:rotate(45deg);background:var(--fl-text-faint)}
.chan{display:flex;justify-content:space-between;gap:1rem;align-items:center;flex-wrap:wrap;padding:.65rem .9rem;border-radius:var(--fl-radius-sm);background:var(--fl-surface-2)}
.chan .mono{font-weight:650;font-size:var(--fl-text-lg)}
.tech{border-block-start:1px solid var(--fl-border);padding:var(--fl-space-4) var(--fl-space-5);display:grid;grid-template-columns:auto 1fr auto;gap:.75rem;align-items:center}
.tech b{display:block;font-weight:500}.tech .faint{display:block;line-height:1.5}

/* agents page */
.phero{padding-block:var(--fl-space-6) var(--fl-space-5);display:grid;gap:var(--fl-space-3)}
.flow{display:grid;gap:var(--fl-space-4);align-items:stretch}
.lane{display:grid;gap:var(--fl-space-4);align-content:start}
.lane-h{display:grid;grid-template-columns:5.5rem 1fr;gap:var(--fl-space-4);align-items:center}
.nstep{display:grid;grid-template-columns:2.25rem 1fr;gap:.75rem;align-items:start}
.nstep .n{display:grid;place-items:center;width:2.1rem;height:2.1rem;border-radius:50%;font-family:var(--fl-font-mono);border:1.5px solid currentColor}
.lane.inv .n{color:var(--fl-brand)}.lane.sen .n{color:var(--fl-sand)}
.nstep p{color:var(--fl-text-muted)}
.handoff{display:flex;gap:.75rem;align-items:center;justify-content:center;text-align:center;padding:var(--fl-space-3);color:var(--fl-text-muted);font-size:var(--fl-text-sm)}
.handoff::before,.handoff::after{content:"";flex:1;height:0;border-block-start:2px dashed var(--fl-border-strong)}
.cta-row{display:flex;flex-wrap:wrap;gap:var(--fl-space-3);align-items:center;margin-block-start:var(--fl-space-6)}

/* results */
table{width:100%;border-collapse:collapse;font-size:var(--fl-text-md)}
th,td{text-align:start;padding:.7rem .5rem;border-block-end:1px solid var(--fl-border)}
th{font-weight:500;color:var(--fl-text-muted);font-size:var(--fl-text-sm)}
td.mono{font-weight:500}
.tags{display:flex;flex-wrap:wrap;gap:.5rem}
.tag{padding:.25rem .8rem;border-radius:var(--fl-radius-pill);border:1px dashed var(--fl-border-strong);font-size:var(--fl-text-sm);color:var(--fl-text-muted)}
.kv{display:grid;gap:.5rem}.kv div{display:flex;flex-wrap:wrap;gap:.25rem .75rem;justify-content:space-between}
.kv .mono{font-size:var(--fl-text-sm);color:var(--fl-text-muted);overflow-wrap:anywhere}
.callout{display:grid;grid-template-columns:auto 1fr;gap:.75rem;align-items:start}
.callout .ic{color:var(--fl-sand);margin-block-start:.25rem}

/* docs */
.dgrid{display:grid;gap:var(--fl-space-4)}
.doc{display:grid;gap:.35rem;align-content:start;text-decoration:none;position:relative}
.doc .ic{color:var(--fl-brand)}
.doc-n{font-family:var(--fl-font-mono);font-size:.8125rem;color:var(--fl-text-faint);position:absolute;inset-block-start:var(--fl-space-4);inset-inline-end:var(--fl-space-5)}
.doc .more{min-height:2rem}
.dside{display:none}

@media (min-width:720px){
 .g4{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:repeat(2,1fr)}
 .dgrid{grid-template-columns:repeat(2,1fr)}.acts{grid-template-columns:1fr 1fr}
}
@media (min-width:1024px){
 :root{--fl-gutter:2rem;--fl-text-2xl:2.5rem}
 .nav{display:flex}.tool.sq{display:inline-flex}.tools{margin-inline-start:var(--fl-space-3)}.menu{display:none}
 .hero{padding-block:var(--fl-space-8)}
 .hero-grid{grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);gap:var(--fl-space-7);align-items:center}
 .hero-top .lens{display:none}.sub-p{display:none}.sub-d{display:block;font-size:var(--fl-text-lg)}
 .hero .chips{display:none}
 .duo{display:block;position:relative;aspect-ratio:1/1.02}
 .duo .lens{position:absolute;inset-block-start:0;inset-inline-start:0;width:78%}
 .duo .radar{position:absolute;inset-block-end:0;inset-inline-end:0;width:44%}
 .duo .tagc{position:absolute;display:grid;gap:.15rem;padding:.6rem .9rem;border-radius:var(--fl-radius-md);background:rgb(14 22 38/.94);border:1px solid var(--fl-border-strong);box-shadow:var(--fl-shadow-1);min-width:13rem}
 .duo .tagc b{font-weight:650;line-height:1.3;display:flex;gap:.5rem;align-items:center;justify-content:space-between}
 .duo .tagc span.r{font-size:var(--fl-text-sm);color:var(--fl-text-muted)}
 .duo .tagc .sub{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;font-size:.8125rem;color:var(--fl-text-muted)}
 .duo .t-inv{inset-block-start:-3%;inset-inline-end:-2%;border-inline-start:3px solid var(--fl-brand)}
 .duo .t-sen{inset-block-end:2%;inset-inline-start:6%;border-inline-start:3px solid var(--fl-sand)}
 .box{padding:var(--fl-space-5)}.kind{flex-direction:row;gap:.5rem;font-size:var(--fl-text-sm)}
 .ticker-in{grid-template-columns:auto 1fr auto;align-items:center;gap:var(--fl-space-5)}
 .g4{grid-template-columns:repeat(4,1fr)}
 .sec{padding-block:var(--fl-space-8)}
 .bandc{grid-template-columns:auto 1fr auto;padding:var(--fl-space-6)}
 .cgrid{grid-template-columns:minmax(0,1.35fr) minmax(0,.65fr);align-items:start}
 .cgrid.one{grid-template-columns:minmax(0,46rem);justify-content:center}
 .activity.side{position:sticky;top:5rem}
 .flow{grid-template-columns:1fr auto 1fr}
 .handoff{flex-direction:column;max-width:11rem}
 .handoff::before,.handoff::after{flex:1;width:0;border-block-start:0;border-inline-start:2px dashed var(--fl-border-strong)}
 .dlayout{display:grid;grid-template-columns:15rem 1fr;gap:var(--fl-space-7);align-items:start}
 .dside{display:grid;gap:.15rem;position:sticky;top:5rem;border-inline-end:1px solid var(--fl-border);padding-inline-end:var(--fl-space-4)}
 .dside a{padding:.45rem .75rem;border-radius:var(--fl-radius-sm);text-decoration:none;color:var(--fl-text-muted);font-size:var(--fl-text-sm)}
 .dside a[aria-current]{background:var(--fl-surface-2);color:var(--fl-text)}
 .rgrid{display:grid;grid-template-columns:1.2fr .8fr;gap:var(--fl-space-5);align-items:start}
}
`;

// ── page chrome ───────────────────────────────────────────────────────────
function page({ lang, current, title, body, ribbon = false }) {
  const t = makeT(lang);
  const dir = lang === "ar" ? "rtl" : "ltr";
  const nav = [["check", "home"], ["agents", "agents"], ["results", "results"], ["authorities", "authorities"], ["docs", "docs"], ["privacy", "privacy"]];
  const brand = lang === "ar" ? "عدسة الصقر" : "Falcon Lens";
  return `<!doctype html>
<html lang="${lang}" dir="${dir}" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · ${brand} · design mockup v2</title>
<style>${tokens}${CSS}</style>
</head>
<body>
<header class="top"><div class="wrap top-in">
<a class="brand" href="#">${brandMark()}<span>${brand}<small>${lang === "ar" ? "FALCON LENS" : "عدسة الصقر"}</small></span></a>
<nav class="nav" aria-label="site">${nav.map(([k, id]) => `<a href="#"${id === current ? ' aria-current="page"' : ""}>${t(`nav.${k}`)}</a>`).join("")}</nav>
<div class="tools"><span class="tool">${icon("globe", 18)}${lang === "ar" ? "English" : "العربية"}</span><span class="tool sq">${icon("sun", 18)}</span><span class="tool menu">${icon("menu", 18)}${t("nav.menu")}</span></div>
</div></header>
${ribbon ? `<div class="ribbon">${t("demo.ribbon")}</div>` : ""}
<main><div class="lattice"></div><div class="glow"></div>
${body}
</main>
<footer class="wrap foot">
<nav>${nav.map(([k]) => `<a href="#">${t(`nav.${k}`)}</a>`).join("")}<a href="#">${t("nav.live")}</a><a href="#">${t("nav.ops")}</a></nav>
<p>${t("foot.indep")} ${t("auth.band.title")}</p>
</footer>
</body></html>`;
}

const cap = (t, live) => `<span class="cap" data-live="${live ? "true" : "false"}"><i></i>${t(live ? "cap.live" : "cap.progress")}</span>`;

function agentChip(t, which) {
  const inv = which === "inv";
  // Investigator: the check itself is live (URL check is the complete path today); its AI
  // second-look step carries its own flag. Sentinel: the sentinel_agent flag.
  const sub = inv ? `<span class="sub">${t("agent.inv.aistep")} ${cap(t, caps.investigator)}</span>` : "";
  return `<li class="achip"><span class="glyph ${which}">${icon(inv ? "lens" : "radar", 24)}</span><span><b>${t(`agent.${which}.name`)} · ${t("agent.kind")}</b><span class="r">${t(`agent.${which}.role`)}</span></span>${cap(t, inv ? true : caps.sentinel_agent)}${sub}</li>`;
}

function proofStats(t, withMeaning = false) {
  if (!M) return `<p class="card">${t("proof.pending")}</p>`;
  const rc = ci("test.recall");
  const fc = ci("test.fpr");
  const stat = (v, label, c, mean) => `<div class="stat"><span class="stat-v">${v}</span><span class="stat-l">${label}</span>${c ? `<span class="stat-c">${t("proof.ci")}: <span class="mono">${pct(c[0])} – ${pct(c[1])}</span></span>` : ""}${withMeaning ? `<span class="stat-m">${mean}</span>` : ""}</div>`;
  return `<div class="g3">
${stat(pct(metric("test.recall")), t("proof.recall"), rc, t("results.recall.mean"))}
${stat(pct(metric("test.fpr")), t("proof.fpr"), fc, t("results.fpr.mean"))}
${stat(String(metric("test.official_false_dangerous")), t("proof.official"), null, t("results.official.mean"))}
</div>`;
}
const provenance = (t) => `<p class="src">${icon("chart", 18)}<span>${t("proof.scope", { "test.n": metric("test.n") })}</span><span class="mono">${esc(results.artifact)}</span></p>`;

// ── Home ──────────────────────────────────────────────────────────────────
function home(lang) {
  const t = makeT(lang);
  const kinds = [["url", "link", true], ["message", "message", caps.message_check], ["email", "mail", caps.email_check], ["image", "image", caps.image_check]];
  const demoCampaign = demoCampaigns[0][lang];
  const body = `
<section class="hero"><div class="wrap hero-grid">
 <div class="hero-copy">
  <div class="hero-top"><span class="eyebrow">${t("home.eyebrow")}</span>${lens({ state: "idle", cls: "mini" })}</div>
  <h1 class="h1">${t("home.title")}</h1>
  <p class="lead sub-p">${t("home.sub.phone")}</p>
  <p class="lead sub-d">${t("home.sub")}</p>
  <div class="box">
   <div class="kinds" role="tablist" aria-label="${t("home.kind.label")}">${kinds.map(([k, ic, live], i) => `<span class="kind" role="tab" aria-selected="${i === 0}">${icon(ic, 20)}<span>${t(`home.kind.${k}`)}</span>${live ? "" : cap(t, false)}</span>`).join("")}</div>
   <span class="field-l">${t("home.input.label")}</span>
   <div class="field">hxxps://…</div>
   <span class="hint">${t("home.input.hint")}</span>
   <span class="btn">${icon("search", 24)}${t("home.cta")}</span>
  </div>
  <p class="promise">${icon("hand", 20)}<span>${t("home.promise")}</span></p>
  <ul class="chips">${agentChip(t, "inv")}${agentChip(t, "sen")}</ul>
 </div>
 <div class="duo" aria-hidden="true">
  ${lens({ state: "idle" })}${radar()}
  <div class="tagc t-inv"><b>${t("agent.inv.name")} ${cap(t, true)}</b><span class="r">${t("agent.kind")} · ${t("agent.inv.role")}</span><span class="sub">${t("agent.inv.aistep")} ${cap(t, caps.investigator)}</span></div>
  <div class="tagc t-sen"><b>${t("agent.sen.name")} ${cap(t, caps.sentinel_agent)}</b><span class="r">${t("agent.kind")} · ${t("agent.sen.role")}</span></div>
 </div>
</div></section>

<section class="ticker" aria-label="${t("ticker.label")}"><div class="wrap ticker-in">
 <span class="ticker-l"><i class="pulse"></i>${t("ticker.label")} <span class="demo">${t("demo.badge")}</span></span>
 <span class="ticker-t">${t("ticker.count", { campaigns: demoCampaigns.length, checks: demoCampaigns.reduce((a, c) => a + c.count, 0) })} · ${t("ticker.latest")} <b>${esc(demoCampaign)}</b></span>
 <a class="more" href="#">${t("ticker.cta")}${icon("chevron", 18, "flip")}</a>
</div></section>

<section class="sec"><div class="wrap">
 <div class="sec-head"><h2 class="h2">${t("out.title")}</h2></div>
 <div class="g4">${[["clock", 1], ["list", 2], ["flag", 3], ["hand", 4]].map(([ic, n]) => `<div class="card out">${icon(ic, 28)}<h3 class="h3">${t(`out.${n}.title`)}</h3><p class="muted">${t(`out.${n}.text`)}</p></div>`).join("")}</div>
</div></section>

<section class="sec" style="padding-block-start:0"><div class="wrap">
 <div class="sec-head"><h2 class="h2">${t("meet.title")}</h2></div>
 <div class="g2">
  <article class="card agent inv"><div class="agent-h"><div class="viz">${lens({ state: "scanning", tiers: ["done", "done", "running"], cls: "mini" })}</div><div><span class="agent-k">${t("agent.kind")}</span><h3 class="agent-n">${t("agent.inv.name")}</h3><span class="agent-r">${t("agent.inv.role")}</span></div></div>
   <p class="muted">${t("meet.inv.text")}</p>
   <p class="statline">${cap(t, true)}<span>·</span><span>${t("agent.inv.aistep")}</span>${cap(t, caps.investigator)}</p></article>
  <article class="card agent sen"><div class="agent-h"><div class="viz">${radar()}</div><div><span class="agent-k">${t("agent.kind")}</span><h3 class="agent-n">${t("agent.sen.name")}</h3><span class="agent-r">${t("agent.sen.role")}</span></div></div>
   <p class="muted">${t("meet.sen.text")}</p>
   <p class="statline">${cap(t, caps.sentinel_agent)}</p></article>
 </div>
 <p class="principle">${icon("scale", 26)}<span>${t("meet.principle")}</span></p>
 <a class="more" href="#">${t("meet.cta")}${icon("chevron", 18, "flip")}</a>
</div></section>

<section class="sec proof"><div class="wrap">
 <div class="sec-head"><h2 class="h2">${t("proof.title")}</h2><p class="lead">${t("proof.lead")}</p></div>
 ${proofStats(t)}
 ${M ? provenance(t) : ""}
 <a class="more" href="#">${t("proof.cta")}${icon("chevron", 18, "flip")}</a>
</div></section>

<section class="sec"><div class="wrap">
 <div class="card bandc">${icon("plug", 36)}<div><h2 class="h2">${t("auth.band.title")}</h2><p class="muted">${t("auth.band.text")}</p></div><a class="btn ghost" href="#">${t("auth.band.cta")}${icon("chevron", 18, "flip")}</a></div>
</div></section>`;
  return page({ lang, current: "home", title: lang === "ar" ? "الرئيسية" : "Home", body });
}

// ── Check (3 states). Fixture text is the Falcon Demo Bank demo from web/lib/demo.ts. ──
const FIX = {
  url: 'hxxp://<b>falcon-demo-bank-secure[.]test</b>/login',
  urlOk: 'hxxps://<b>falcondemobank[.]test</b>/',
  brand: { ar: "بنك الصقر التجريبي", en: "Falcon Demo Bank" },
  danger: {
    reasons: ["الصفحة تنتحل اسم «بنك الصقر التجريبي» وعنوانها ليس من عناوين البنك الرسمية.", "تطلب كلمة المرور ورمز التحقق وترسلهما إلى خادم آخر.", "العنوان جديد جداً: سُجّل قبل يومين."],
    now: ["لا تفتح الرابط ولا تُدخل أي بيانات.", "احذف الرسالة واحظر المرسل.", "ادخل إلى حسابك من تطبيق البنك الرسمي فقط."],
    acted: ["اتصل ببنكك فوراً على الرقم المطبوع على بطاقتك واطلب إيقافها.", "غيّر كلمة المرور من التطبيق الرسمي.", "راقب حسابك وبلّغ البنك عن أي عملية لا تعرفها."],
  },
  nws: {
    reasons: ["العنوان ضمن النطاقات الرسمية الموثّقة لبنك الصقر التجريبي.", "النطاق قديم وليس في قوائم الحظر المعروفة."],
    caution: "عدم وجود علامات تحذير لا يعني أن الرابط مضمون. لا تشارك رمز التحقق أو كلمة المرور مع أي أحد.",
    now: ["تأكد أن العنوان في متصفحك يطابق هذا العنوان حرفاً بحرف."],
    acted: ["إذا طُلب منك شيء غير معتاد بعد الدخول، توقّف واتصل بالبنك."],
  },
};

function activity(t, states, { title, side = true, extra = "" }) {
  const keys = ["known", "address", "visit", "ai"];
  return `<aside class="card activity ${side ? "side" : ""}">
 <div class="activity-h"><span class="glyph inv">${icon("lens", 24)}</span><h2 class="h3">${title}</h2></div>
 <ol class="steps">${keys.map((k, i) => `<li class="step" data-st="${states[i]}"><i class="dot"></i><span><span class="st-t">${t(`act.step.${k}`)}</span>${k === "ai" && !caps.investigator ? ` ${cap(t, false)}` : ""}${states[i] === "running" ? '<i class="shim" style="display:block"></i>' : ""}</span><span class="st-s">${t(`act.st.${states[i]}`)}</span></li>`).join("")}</ol>
 ${extra}
 <p class="sen-note">${icon("radar", 20)}<span>${t("act.sentinel")} ${cap(t, caps.sentinel_agent)}</span></p>
</aside>`;
}

const caseHead = (t, lensSvg, url) => `<div class="page-h"><h1>${t("check.title")}</h1><span class="btn ghost">${icon("refresh", 18)}${t("check.new")}</span></div>
<div class="card case">${lensSvg}<div><span class="url mono">${url}</span><span class="faint">${t("check.url.note")}</span></div></div>`;

function report(t, lang) {
  return `<div class="act"><h3>${icon("flag", 22)}${t("res.report")}</h3><p class="muted">${t("res.report.lead")}</p>
${channels.map((c) => `<div class="chan"><span>${esc(c[lang])}</span><span class="mono">${esc(c.value)}</span></div>`).join("")}
<p class="faint">${t("res.report.source", { retrieved_at: retrievedAt })}</p></div>`;
}
const tech = (t) => `<div class="tech">${icon("cpu", 22)}<span><b>${t("tech.toggle")}</b><span class="faint">${t("tech.summary")} <u>${t("tech.docs")}</u></span></span>${icon("down", 22)}</div>`;
const ul = (items) => `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;

function checkChecking() {
  const t = makeT("ar");
  const body = `<div class="wrap page">
${caseHead(t, lens({ state: "scanning", tiers: ["done", "running"], cls: "mini" }), FIX.url)}
<div class="cgrid one">
${activity(t, ["done", "running", "pending", "pending"], { title: t("act.title"), side: false, extra: `<p class="prov">${vicon("suspicious", 24)}<span>${t("act.prov.suspicious")}</span></p><p class="wait">${icon("hand", 24)}<span>${t("act.wait")}</span></p>` })}
</div></div>`;
  return page({ lang: "ar", current: "home", title: "الفحص جارٍ", body, ribbon: true });
}

function checkFinal(kind) {
  const t = makeT("ar");
  const f = FIX[kind === "dangerous" ? "danger" : "nws"];
  const v = kind === "dangerous" ? "dangerous" : "nws";
  const states = kind === "dangerous" ? ["done", "done", "done", "skipped"] : ["done", "done", "skipped", "skipped"];
  const body = `<div class="wrap page">
${caseHead(t, lens({ state: "locked", verdict: v, tiers: states.slice(), cls: "mini" }), kind === "dangerous" ? FIX.url : FIX.urlOk)}
<div class="cgrid">
<article class="verdict" data-v="${v}">
 <div class="plate">${vicon(v, 56)}<div><h2 class="plate-w">${t(`v.${v}`)}</h2><p class="plate-s">${t(`v.${v}.sub`)}</p></div></div>
 <div class="vbody">
  ${kind === "dangerous" ? `<p class="imp">${icon("eye", 22)}<span>${t("res.imp")} <b>${FIX.brand.ar}</b></span></p>` : ""}
  <section><h3 class="h3" style="margin-block-end:.75rem">${t("res.why")}</h3><ol class="reasons">${f.reasons.map((r) => `<li class="reason"><span>${esc(r)}</span></li>`).join("")}</ol></section>
  ${f.caution ? `<div class="caution">${vicon("suspicious", 26)}<div><b>${t("res.caution")}</b><p>${esc(f.caution)}</p></div></div>` : ""}
  <div class="acts"><div class="act now"><h3>${icon("hand", 22)}${t("res.now")}</h3>${ul(f.now)}</div><div class="act"><h3>${icon("undo", 22)}${t("res.acted")}</h3>${ul(f.acted)}</div></div>
  ${report(t, "ar")}
 </div>
 ${tech(t)}
</article>
${activity(t, states, { title: t("act.done", { latency_s: (demoLatency[kind === "dangerous" ? 0 : 1] / 1000).toFixed(1) }) })}
</div></div>`;
  return page({ lang: "ar", current: "home", title: t(`v.${v}`), body, ribbon: true });
}

// ── AI agents ─────────────────────────────────────────────────────────────
function agents(lang) {
  const t = makeT(lang);
  const lane = (w, viz, live, capOn) => `<article class="card lane ${w} agent ${w}">
 <div class="lane-h"><div>${viz}</div><div><span class="agent-k">${t("agent.kind")} · ${t(`agents.${w}.tag`)}</span><h2 class="agent-n">${t(`agent.${w}.name`)}</h2><p class="statline">${cap(t, live)}</p></div></div>
 ${[1, 2, 3].map((n) => `<div class="nstep"><span class="n">${n}</span><div><h3 class="h3">${t(`agents.${w}.${n}.title`)}${capOn === n ? ` ${cap(t, caps.investigator)}` : ""}</h3><p>${t(`agents.${w}.${n}.text`)}</p></div></div>`).join("")}
</article>`;
  const body = `<div class="wrap">
<section class="phero"><span class="eyebrow">${t("nav.agents")}</span><h1 class="h1">${t("agents.title")}</h1><p class="lead" style="font-size:var(--fl-text-lg)">${t("agents.lead")}</p></section>
<section class="flow">
 ${lane("inv", lens({ state: "scanning", tiers: ["done", "done", "running"], cls: "mini" }), true, 2)}
 <p class="handoff"><span>${t("agents.handoff")}</span></p>
 ${lane("sen", radar(), caps.sentinel_agent, 0)}
</section>
<section class="sec">
 <div class="sec-head"><h2 class="h2">${t("agents.promises.title")}</h2></div>
 <div class="g3">${[["scale", 1], ["user", 2], ["list", 3]].map(([ic, n]) => `<div class="card out">${icon(ic, 28)}<h3 class="h3">${t(`agents.p${n}.title`)}</h3><p class="muted">${t(`agents.p${n}.text`)}</p></div>`).join("")}</div>
 <div class="cta-row"><a class="btn" href="#">${icon("search", 22)}${t("agents.cta")}</a><a class="more" href="#">${icon("book", 18)}${t("agents.docs")}</a></div>
</section></div>`;
  return page({ lang, current: "agents", title: t("agents.title"), body });
}

// ── Results ───────────────────────────────────────────────────────────────
function resultsPage(lang) {
  const t = makeT(lang);
  const rows = (split) => ["precision", "recall", "f1", "fpr", "pr_auc", "ece"].map((k) => {
    const v = metric(`${split}.${k}`);
    if (v === null) return "";
    const c = ci(`${split}.${k}`);
    const f = k === "ece" ? (x) => x.toFixed(3) : pct;
    return `<tr><td>${t(`metric.${k}`)}</td><td class="mono">${f(v)}</td><td class="mono">${c ? `${f(c[0])} – ${f(c[1])}` : ""}</td></tr>`;
  }).join("");
  const table = (split) => `<div class="card"><h3 class="h3">${t(`results.split.${split}`)}</h3><p class="faint">${t("results.n", { n: metric(`${split}.n`) })}</p><table><thead><tr><th>${t("results.col.metric")}</th><th>${t("results.col.value")}</th><th>${t("results.col.ci")}</th></tr></thead><tbody>${rows(split)}</tbody></table></div>`;
  const d = results.data;
  const body = `<div class="wrap">
<section class="phero"><span class="eyebrow">${t("nav.results")}</span><h1 class="h1">${t("results.title")}</h1><p class="lead">${t("results.lead")}</p></section>
${proofStats(t, true)}
${provenance(t)}
<section class="sec rgrid">
 <div style="display:grid;gap:var(--fl-space-4)"><h2 class="h2">${t("results.all.title")}</h2>${table("test")}${table("val")}</div>
 <div style="display:grid;gap:var(--fl-space-4)">
  <div class="card callout">${icon("scale", 24)}<div><h3 class="h3">${t("results.scope.title")}</h3><p class="muted">${t("results.scope.text")}</p></div></div>
  <div class="card" style="display:grid;gap:.75rem"><h3 class="h3">${t("results.ne.title")}</h3><p class="muted">${t("results.ne.lead")}</p><ul class="tags">${d.not_evaluated.map((k) => `<li class="tag">${COPY[`ne.${k}`] ? t(`ne.${k}`) : esc(k)}</li>`).join("")}</ul></div>
  <div class="card" style="display:grid;gap:.75rem"><h3 class="h3">${t("results.prov.title")}</h3><div class="kv"><div><span>${t("results.prov.artifact")}</span><span class="mono">${esc(results.artifact)}</span></div><div><span>${t("results.prov.date")}</span><span class="mono">${esc(d.created_at)}</span></div><div><span>${t("results.prov.dataset")}</span><span class="mono">${esc(d.dataset_hash.slice(0, 16))}</span></div></div>
  <a class="more" href="#">${icon("book", 18)}${t("results.docs")}</a></div>
 </div>
</section></div>`;
  return page({ lang, current: "results", title: t("results.title"), body });
}

// ── Docs landing ──────────────────────────────────────────────────────────
function docs(lang) {
  const t = makeT(lang);
  const items = [["architecture", "layers"], ["agents", "cpu"], ["cascade", "list"], ["arbiter", "scale"], ["security", "lock", "injection_defence"], ["evals", "chart"], ["integration", "plug"], ["privacy", "eye"]];
  const body = `<div class="wrap">
<section class="phero"><span class="eyebrow">${t("docs.eyebrow")}</span><h1 class="h1">${t("docs.title")}</h1><p class="lead" style="font-size:var(--fl-text-lg)">${t("docs.lead")}</p></section>
<div class="dlayout">
 <nav class="dside" aria-label="docs"><a href="#" aria-current="page">${t("docs.title")}</a>${items.map(([k]) => `<a href="#">${t(`docs.${k}.title`)}</a>`).join("")}</nav>
 <div>
  <div class="dgrid">${items.map(([k, ic, flag], i) => `<a class="card doc" href="#"><span class="doc-n">${String(i + 1).padStart(2, "0")}</span>${icon(ic, 28)}<h2 class="h3">${t(`docs.${k}.title`)}</h2><p class="muted">${t(`docs.${k}.text`)}</p>${flag ? `<p class="statline">${lang === "ar" ? "التصدي لحقن التعليمات" : "Prompt-injection defence"} ${cap(t, caps[flag])}</p>` : ""}<span class="more">${t("docs.read")}${icon("chevron", 18, "flip")}</span></a>`).join("")}</div>
  <p class="principle" style="font-size:var(--fl-text-md);font-weight:500">${icon("lens", 24)}<a href="#">${t("docs.back")}</a></p>
 </div>
</div>
<div style="height:var(--fl-space-7)"></div></div>`;
  return page({ lang, current: "docs", title: t("docs.title"), body });
}

// ── write ─────────────────────────────────────────────────────────────────
const out = join(here, "mockups");
mkdirSync(out, { recursive: true });
const PAGES = {
  "home-ar": home("ar"),
  "home-en": home("en"),
  "check-checking-ar": checkChecking(),
  "check-dangerous-ar": checkFinal("dangerous"),
  "check-no-warning-signs-ar": checkFinal("nws"),
  "agents-ar": agents("ar"),
  "results-ar": resultsPage("ar"),
  "docs-ar": docs("ar"),
};
for (const [name, html] of Object.entries(PAGES)) {
  if (/\b(https?:)?\/\/(?!www\.w3\.org)[a-z0-9.-]+\.[a-z]{2,}/i.test(html.replace(/hxxps?:\/\/[^<\s]*/g, "").replace(/xmlns='http:\/\/www\.w3\.org[^']*'/g, ""))) {
    throw new Error(`${name}: an external URL slipped into a mockup`);
  }
  if (/\bsafe\b|آمن(?!ة)/i.test(html.replace(/<style>[\s\S]*?<\/style>/, ""))) throw new Error(`${name}: forbidden word "safe" / «آمن»`);
  writeFileSync(join(out, `${name}.html`), html);
}

// COPY.md: the copy table builders read (generated; edit copy.json, not this file).
const lines = ["# Web v2 copy (generated from `copy.json` by `build-mockups.mjs`; do not edit by hand)", "", "`cap` = capability flag that must be true before the string appears without an \"In progress\" badge.", "", "| Key | English | العربية | cap |", "|---|---|---|---|"];
for (const [k, v] of Object.entries(COPY)) {
  if (k.startsWith("_")) continue;
  lines.push(`| \`${k}\` | ${v.en.replace(/\|/g, "\\|")} | ${v.ar.replace(/\|/g, "\\|")} | ${v.cap ? `\`${v.cap}\`` : ""} |`);
}
writeFileSync(join(here, "COPY.md"), lines.join("\n") + "\n");
console.log("mockups:", Object.keys(PAGES).join(", "));
console.log("capabilities used:", JSON.stringify(caps));
