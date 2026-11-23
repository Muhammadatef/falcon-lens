#!/usr/bin/env node
/* eslint-disable no-undef -- document is used inside page.evaluate */
// Screenshots of the v2 part A pages: Home, /agents, /results at phone 390 (Arabic) and desktop 1440 (English).
//   node design/scripts/capture-v2a.mjs   (against a running app + mock gateway; BASE defaults to the e2e mock)
// Output: design/app-shots/v2a/*.jpg. The ticker shows demo campaigns from lib/demo.ts, labelled DEMO DATA.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const base = process.env.BASE_URL ?? "http://127.0.0.1:43210";
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "app-shots", "v2a");
mkdirSync(out, { recursive: true });

const PAGES = [["home", "/"], ["agents", "/agents"], ["results", "/results"]];
const VIEWS = [["390-ar", { width: 390, height: 844 }, "ar"], ["1440-en", { width: 1440, height: 900 }, "en"]];

const campaigns = [
  { campaign_id: "inc_01HZZZZZZZZZZZZZZZZZZZZZZA", title: { ar: "صفحات دخول مزيّفة باسم «بنك الصقر التجريبي»", en: "Fake sign-in pages using the name Falcon Demo Bank" }, severity: "high", count: 14, last_seen: "2026-11-22T09:40:00Z", series: [1, 2, 2, 4, 5], source: "synthetic" },
  { campaign_id: "inc_01HZZZZZZZZZZZZZZZZZZZZZZB", title: { ar: "رسائل رسوم توصيل وهمية", en: "Fake delivery-fee messages" }, severity: "medium", count: 6, last_seen: "2026-11-21T18:10:00Z", series: [0, 1, 2, 3], source: "synthetic" },
];
const key = `shot${Date.now()}`;
await fetch(`${base}/__mock/boards`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key, campaigns }) });

const browser = await chromium.launch();
for (const [tag, viewport, lang] of VIEWS) {
  const context = await browser.newContext({ viewport, reducedMotion: "reduce", isMobile: viewport.width < 800, deviceScaleFactor: 1 });
  await context.addCookies([
    { name: "fl_lang", value: lang, url: base },
    { name: "mock_boards", value: key, url: base },
  ]);
  const page = await context.newPage();
  for (const [name, path] of PAGES) {
    await page.goto(base + path);
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(600);
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.screenshot({ path: join(out, `${name}-${tag}.jpg`), type: "jpeg", quality: 68, fullPage: true, clip: { x: 0, y: 0, width: viewport.width, height: Math.min(h, viewport.width < 800 ? 3200 : 2600) } });
    console.log("shot", name, tag);
  }
  await context.close();
}
await browser.close();
