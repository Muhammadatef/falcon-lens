// Static rules for the extension source (run by `pnpm lint`). Fails on:
//  - HTML-string sinks or dynamic code (innerHTML, outerHTML, insertAdjacentHTML, document.write,
//    eval, new Function, dangerouslySetInnerHTML);
//  - inline script or style in the HTML shells (the extension CSP forbids both);
//  - a remote URL in the HTML or CSS (fonts and styles must be bundled);
//  - the word "safe" or «آمن» as a claim in the user-facing strings (CLAUDE.md: never say "safe").
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const problems = [];
const files = (dir, exts) => readdirSync(join(root, dir)).filter((f) => exts.some((e) => f.endsWith(e))).map((f) => join(dir, f));
const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

const SINKS = /\b(innerHTML|outerHTML|insertAdjacentHTML|dangerouslySetInnerHTML|document\.write|createContextualFragment)\b|\beval\s*\(|new\s+Function\s*\(|setTimeout\s*\(\s*["'`]/;
for (const f of files("src", [".ts"])) {
  strip(readFileSync(join(root, f), "utf8")).split("\n").forEach((line, i) => {
    if (SINKS.test(line)) problems.push(`${f}:${i + 1} HTML-string sink or dynamic code`);
  });
}

for (const f of files("static", [".html"])) {
  const s = readFileSync(join(root, f), "utf8");
  if (/<script(?![^>]*\bsrc=)[^>]*>/i.test(s)) problems.push(`${f} inline <script>`);
  if (/<style\b/i.test(s) || /\sstyle=/i.test(s)) problems.push(`${f} inline style`);
  if (/\son[a-z]+=/i.test(s)) problems.push(`${f} inline event handler`);
  if (/(?:src|href)=["'](?:https?:)?\/\//i.test(s)) problems.push(`${f} remote resource`);
}
for (const f of files("static", [".css"])) {
  if (/url\(\s*["']?(?:https?:)?\/\//i.test(readFileSync(join(root, f), "utf8"))) problems.push(`${f} remote url()`);
  if (/@import/i.test(strip(readFileSync(join(root, f), "utf8")))) problems.push(`${f} @import`);
}

const strings = strip(readFileSync(join(root, "src", "i18n.ts"), "utf8"));
if (/\bsafe(ly|ty)?\b/i.test(strings)) problems.push('src/i18n.ts uses the word "safe"');
if (/(^|[^؀-ۿ])(ال)?آمن(ة)?([^؀-ۿ]|$)/.test(strings)) problems.push("src/i18n.ts uses the word «آمن»");

if (problems.length) {
  console.error("check-static: FAILED\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log("check-static: ok");
