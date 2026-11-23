#!/usr/bin/env node
// Renders public/icons/icon.svg to the PNG sizes the manifest needs, plus the apple-touch-icon,
// app/favicon.ico (PNG-in-ICO) and the Open Graph card. Run once; outputs are committed.
//   pnpm exec node scripts/make-icons.mjs
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const icons = join(root, "public", "icons");
const svg = readFileSync(join(icons, "icon.svg"), "utf8");
const browser = await chromium.launch();

const shot = async (size, markup) => {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  await page.setContent(`<!doctype html><html><body style="margin:0;background:#070b14">${markup.replace("<svg ", `<svg width="${size}" height="${size}" `)}</body></html>`);
  const buf = await page.screenshot({ clip: { x: 0, y: 0, width: size, height: size } });
  await page.close();
  return buf;
};

for (const [name, size] of [["icon-192.png", 192], ["icon-512.png", 512], ["icon-maskable-512.png", 512], ["apple-touch-icon.png", 180]]) {
  writeFileSync(join(icons, name), await shot(size, svg));
}

const png48 = await shot(48, svg);
const ico = Buffer.alloc(22 + png48.length);
ico.writeUInt16LE(0, 0); ico.writeUInt16LE(1, 2); ico.writeUInt16LE(1, 4);
ico.writeUInt8(48, 6); ico.writeUInt8(48, 7); ico.writeUInt16LE(1, 10); ico.writeUInt16LE(32, 12);
ico.writeUInt32LE(png48.length, 14); ico.writeUInt32LE(22, 18);
png48.copy(ico, 22);
writeFileSync(join(root, "public", "favicon.ico"), ico);

const font = (f) => readFileSync(join(root, "public", "fonts", f)).toString("base64");
const html = `<!doctype html><html><head><style>
@font-face{font-family:R;font-weight:100 900;src:url(data:font/woff2;base64,${font("readex-pro-arabic-wght-normal.woff2")}) format("woff2");unicode-range:U+0600-06FF,U+FB50-FDFF,U+FE70-FEFC}
@font-face{font-family:R;font-weight:100 900;src:url(data:font/woff2;base64,${font("readex-pro-latin-wght-normal.woff2")}) format("woff2");unicode-range:U+0000-00FF,U+2000-206F}
body{margin:0;width:1200px;height:630px;background:radial-gradient(900px 500px at 85% -10%,#12333a,transparent 60%),#070b14;color:#f2eee6;font-family:R,sans-serif;display:flex;align-items:center;gap:64px;padding:0 90px;box-sizing:border-box;position:relative}
.t{flex:1}.n{font-size:92px;font-weight:700;line-height:1.2}.e{font-size:44px;letter-spacing:.14em;color:#8794ae;font-weight:500;margin-top:6px;direction:ltr;text-align:right}
.s{font-size:34px;color:#aeb8cc;margin-top:34px;line-height:1.6}.f{position:absolute;bottom:34px;left:90px;right:90px;font-size:22px;color:#8794ae;display:flex;justify-content:space-between}
</style></head><body dir="rtl"><div style="width:300px;height:300px;flex:none">${svg.replace("<svg ", '<svg width="300" height="300" ')}</div>
<div class="t"><div class="n">عدسة الصقر</div><div class="e">FALCON LENS</div>
<div class="s">افحص قبل أن تضغط<br><span dir="ltr" style="color:#e7d7b6">Check before you tap</span></div></div>
<div class="f"><span>مشروع مستقل · غير تابع لأي جهة</span><span dir="ltr">Independent project · not affiliated</span></div></body></html>`;
const og = await browser.newPage({ viewport: { width: 1200, height: 630 } });
await og.setContent(html);
// eslint-disable-next-line no-undef -- runs inside the page
await og.evaluate(() => document.fonts.ready);
mkdirSync(join(root, "public", "og"), { recursive: true });
writeFileSync(join(root, "public", "og", "falcon-lens-og.png"), await og.screenshot());
await browser.close();
console.log("icons, favicon.ico and og card written");
