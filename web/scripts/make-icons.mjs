#!/usr/bin/env node
// Renders public/icons/icon.svg to the PNG sizes the manifest needs (run once; PNGs are committed).
//   pnpm exec node scripts/make-icons.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const icons = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");
const svg = readFileSync(join(icons, "icon.svg"), "utf8");
const browser = await chromium.launch();
for (const [name, size] of [["icon-192.png", 192], ["icon-512.png", 512], ["icon-maskable-512.png", 512]]) {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  await page.setContent(`<!doctype html><html><body style="margin:0;background:#070b14">${svg.replace("<svg ", `<svg width="${size}" height="${size}" `)}</body></html>`);
  await page.screenshot({ path: join(icons, name), clip: { x: 0, y: 0, width: size, height: size } });
  await page.close();
}
await browser.close();
console.log("icons written to", icons);
