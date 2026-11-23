#!/usr/bin/env node
/* eslint-disable no-undef -- document is used inside page.evaluate */
// Committee screenshots of every page: phone 390 in Arabic and desktop 1440 in English, against a running stack.
//   LIVE_BASE_URL=https://localhost:48843 node design/scripts/capture-committee.mjs
// Output: design/app-shots/committee/*.jpg (kept under 2 MB in total).
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const base = process.env.LIVE_BASE_URL ?? "https://localhost:8443";
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "app-shots", "committee");
mkdirSync(out, { recursive: true });

const PAGES = [
  ["home", "/"],
  ["how-it-works", "/how-it-works"],
  ["architecture-agents", "/architecture/agents"],
  ["results", "/results"],
  ["authorities", "/authorities"],
  ["privacy", "/privacy"],
  ["campaigns", "/campaigns"],
  ["ops", "/ops"],
  ["not-found", "/no-such-page"],
];
const VIEWS = [
  ["390-ar", { width: 390, height: 844 }, "ar", 1],
  ["1440-en", { width: 1440, height: 900 }, "en", 1],
];

// Full page, capped in height so the set stays small (long pages show their first screens).
const clip = async (page) => {
  const h = await page.evaluate(() => document.documentElement.scrollHeight);
  const vp = page.viewportSize();
  return { fullPage: true, clip: { x: 0, y: 0, width: vp.width, height: Math.min(h, vp.width < 800 ? 2200 : 1500) } };
};

const browser = await chromium.launch();
for (const [tag, viewport, lang, scale] of VIEWS) {
  const context = await browser.newContext({ viewport, ignoreHTTPSErrors: true, deviceScaleFactor: scale, reducedMotion: "reduce", isMobile: viewport.width < 800 });
  await context.addCookies([{ name: "fl_lang", value: lang, url: base }, { name: "fl_theme", value: "dark", url: base }]);
  const page = await context.newPage();
  for (const [name, path] of PAGES) {
    await page.goto(base + path);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: join(out, `${name}-${tag}.jpg`), type: "jpeg", quality: 42, ...(await clip(page)) });
  }
  // A real verdict from the running stack (reserved .test fixture name only).
  await page.goto(base + "/");
  await page.getByTestId("check-input").fill("http://falcon-demo-bank-secure.test/login");
  await page.getByTestId("check-submit").click();
  await page.getByTestId("result").and(page.locator('[data-phase="final"]')).waitFor({ timeout: 60_000 });
  await page.waitForTimeout(1500);
  await page.getByTestId("result").screenshot({ path: join(out, `check-dangerous-${tag}.jpg`), type: "jpeg", quality: 42 });
  await context.close();
}
await browser.close();
console.log("written to", out);
