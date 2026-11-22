// Renders the Falcon Lens mark (ring, pupil, brow, malar stripe) to static/icons/icon-<n>.png.
// Run by hand when the mark changes: `node scripts/make-icons.mjs`. The PNGs are committed
// because Chrome does not accept SVG icons in the manifest. The mark is original artwork.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const out = join(dirname(fileURLToPath(import.meta.url)), "..", "static", "icons");
mkdirSync(out, { recursive: true });

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" fill="none">
  <rect width="36" height="36" rx="8" fill="#070b14"/>
  <path d="M6.500 11c4.600-4.800 14-6.200 23-2.200" stroke="#e7d7b6" stroke-width="2.800" stroke-linecap="round"/>
  <circle cx="18" cy="18.500" r="8" stroke="#3fe0c5" stroke-width="3"/>
  <circle cx="18" cy="18.500" r="3.300" fill="#f2eee6"/>
  <path d="M15 27.500c-.5 2.200-1.700 3.900-3.400 5.100" stroke="#e7d7b6" stroke-width="2.800" stroke-linecap="round"/>
</svg>`;

const browser = await chromium.launch();
for (const size of [16, 32, 48, 128]) {
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`);
  await page.screenshot({ path: join(out, `icon-${size}.png`), omitBackground: true });
  await page.close();
}
await browser.close();
console.log("icons written to", out);
