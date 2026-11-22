#!/usr/bin/env node
// Copies web/design/tokens.css into the single-file prototype, between the
// "tokens:start" and "tokens:end" markers, so the prototype stays self-contained
// without drifting from the source of truth.
// Usage: node web/design/scripts/sync-prototype-tokens.mjs [--check]
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const tokens = readFileSync(join(root, "tokens.css"), "utf8").trim();
const file = join(root, "prototype", "index.html");
const html = readFileSync(file, "utf8");
const START = "/* tokens:start (generated from ../tokens.css by scripts/sync-prototype-tokens.mjs) */";
const END = "/* tokens:end */";
const a = html.indexOf(START);
const b = html.indexOf(END);
if (a < 0 || b < a) {
  console.error("token markers not found in prototype/index.html");
  process.exit(2);
}
const next = `${html.slice(0, a + START.length)}\n${tokens}\n${html.slice(b)}`;
if (process.argv.includes("--check")) {
  if (next !== html) {
    console.error("prototype tokens are out of date: run node web/design/scripts/sync-prototype-tokens.mjs");
    process.exit(1);
  }
  console.log("prototype tokens match tokens.css");
} else {
  writeFileSync(file, next);
  console.log(next === html ? "prototype tokens already current" : "prototype tokens updated");
}
