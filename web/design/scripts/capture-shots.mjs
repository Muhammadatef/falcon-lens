#!/usr/bin/env node
// Renders the prototype in headless Chromium at phone (390) and desktop (1440) widths,
// in Arabic and English, both themes, and writes PNGs to web/design/prototype/shots/.
// Fails if the page logs an error, overflows horizontally, or shows a broken layout
// direction. Needs Playwright (not a repo dependency yet):
//   PLAYWRIGHT_MODULE=/abs/path/to/node_modules/playwright/index.mjs node web/design/scripts/capture-shots.mjs
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const root = join(dirname(fileURLToPath(import.meta.url)), "..", "prototype");
const out = join(root, "shots");
mkdirSync(out, { recursive: true });
const base = pathToFileURL(join(root, "index.html")).href;

const SIZES = { 390: { width: 390, height: 844, deviceScaleFactor: 2 }, 1440: { width: 1440, height: 900, deviceScaleFactor: 1 } };
// name, width, query, what to capture ("viewport" | "full" | selector), options
const SHOTS = [
  ["01-hero-390-ar-dark", 390, "lang=ar&theme=dark&instant=1", "viewport"],
  ["01-hero-1440-ar-dark", 1440, "lang=ar&theme=dark&instant=1", "viewport"],
  ["01-hero-1440-en-light", 1440, "lang=en&theme=light&instant=1", "viewport"],
  ["02-check-stream-390-ar-dark", 390, "lang=ar&theme=dark&scene=danger", "viewport", { waitMs: 2600 }],
  ["03-check-dangerous-390-ar-dark", 390, "lang=ar&theme=dark&scene=danger&instant=1", "#check"],
  ["03-check-dangerous-1440-ar-dark", 1440, "lang=ar&theme=dark&scene=danger&instant=1", "#check"],
  ["03-check-dangerous-1440-en-light", 1440, "lang=en&theme=light&scene=danger&instant=1", "#check"],
  ["04-check-no-warning-signs-390-ar-light", 390, "lang=ar&theme=light&scene=nws&instant=1", "#check"],
  ["04-check-no-warning-signs-1440-ar-dark", 1440, "lang=ar&theme=dark&scene=nws&instant=1", "#check"],
  ["05-board-390-ar-dark", 390, "lang=ar&theme=dark&instant=1", "#board"],
  ["05-board-1440-ar-dark", 1440, "lang=ar&theme=dark&instant=1", "#board"],
  ["06-incident-390-ar-dark", 390, "lang=ar&theme=dark&instant=1", "#ops"],
  ["06-incident-1440-en-light", 1440, "lang=en&theme=light&instant=1", "#ops"],
  ["07-full-390-ar-dark", 390, "lang=ar&theme=dark&scene=danger&instant=1", "full"],
  ["07-full-1440-ar-dark", 1440, "lang=ar&theme=dark&scene=danger&instant=1", "full"],
  ["08-reduced-motion-390-ar-dark", 390, "lang=ar&theme=dark&scene=danger", "#check", { reducedMotion: "reduce", waitMs: 5200 }],
];

// CHROMIUM_PATH lets you reuse an already-downloaded headless shell instead of downloading one.
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
let failures = 0;
for (const [name, width, query, target, opts = {}] of SHOTS) {
  const context = await browser.newContext({ viewport: { width: SIZES[width].width, height: SIZES[width].height }, deviceScaleFactor: SIZES[width].deviceScaleFactor, reducedMotion: opts.reducedMotion ?? "no-preference" });
  const page = await context.newPage();
  const problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.goto(`${base}?${query}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(opts.waitMs ?? 350);

  const facts = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    dir: document.documentElement.dir,
    lang: document.documentElement.lang,
    font: document.fonts.check('16px "Readex Pro"'),
    wide: [...document.querySelectorAll("body *")].filter((n) => n.getBoundingClientRect().right > window.innerWidth + 1 || n.getBoundingClientRect().left < -1)
      .filter((n) => !n.closest(".bg, .lens-stage, .radar-clip, svg")).slice(0, 5).map((n) => n.className || n.tagName),
  }));
  if (facts.overflow > 0) problems.push(`horizontal overflow ${facts.overflow}px`);
  if (facts.wide.length) problems.push(`elements outside viewport: ${facts.wide.join(", ")}`);
  if ((facts.lang === "ar") !== (facts.dir === "rtl")) problems.push(`dir/lang mismatch ${facts.lang}/${facts.dir}`);
  if (!facts.font) problems.push("Readex Pro did not load");

  const path = join(out, `${name}.png`);
  if (target === "viewport") await page.screenshot({ path });
  else if (target === "full") await page.screenshot({ path, fullPage: true });
  else await page.locator(target).screenshot({ path });
  failures += problems.length;
  console.log(`${problems.length ? "FAIL" : "ok  "} ${name}.png${problems.length ? "  " + problems.join("; ") : ""}`);
  await context.close();
}
await browser.close();
process.exit(failures ? 1 : 0);
