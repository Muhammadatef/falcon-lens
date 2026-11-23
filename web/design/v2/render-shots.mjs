#!/usr/bin/env node
// Renders web/design/v2/mockups/*.html to shots/*.png at phone 390 and desktop 1440.
//   node web/design/v2/build-mockups.mjs && node web/design/v2/render-shots.mjs
// Needs Playwright (the web workspace has @playwright/test; PLAYWRIGHT_MODULE may point elsewhere).
// Fails if any mockup makes a non-file request (the mockups must be self-contained).
import { mkdirSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "@playwright/test");
const src = join(here, "mockups");
const out = join(here, "shots");
mkdirSync(out, { recursive: true });

// The English Home is a variant: desktop only. Everything else: phone + desktop, Arabic.
const VIEWS = [["390", { width: 390, height: 844 }], ["1440", { width: 1440, height: 900 }]];
const MAX_H = { 390: 3000, 1440: 2400 };

const browser = await chromium.launch();
let external = 0;
for (const file of readdirSync(src).filter((f) => f.endsWith(".html")).sort()) {
  const name = file.replace(/\.html$/, "");
  for (const [tag, viewport] of VIEWS) {
    if (name === "home-en" && tag === "390") continue;
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: "reduce", isMobile: tag === "390", colorScheme: "dark" });
    const page = await context.newPage();
    page.on("request", (r) => {
      if (!r.url().startsWith("file:") && !r.url().startsWith("data:")) {
        external += 1;
        console.error("external request:", name, r.url());
      }
    });
    await page.goto(pathToFileURL(join(src, file)).href);
    await page.evaluate(() => document.fonts.ready);
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 0) console.error(`horizontal overflow ${overflow}px: ${name} @${tag}`);
    await page.screenshot({ path: join(out, `${name}-${tag}.png`), fullPage: true, clip: { x: 0, y: 0, width: viewport.width, height: Math.min(h, MAX_H[tag]) } });
    await context.close();
  }
}
await browser.close();
const total = readdirSync(out).reduce((a, f) => a + statSync(join(out, f)).size, 0);
console.log(`shots: ${readdirSync(out).length} files, ${(total / 1e6).toFixed(2)} MB`);
if (external > 0 || total > 2e6) process.exit(1);
