#!/usr/bin/env node
// Copies the newest PUBLISHED evaluation artifact (evals/results/published/*.json) into
// lib/results.generated.json, and the two explainer SVGs from docs/assets into public/images.
// The Results page renders only what this file holds: no number is typed into the web app.
// Outside the monorepo (the Docker build context is ./web) the sources are absent, so this is a
// no-op and the committed copies are used. Run: node scripts/sync-results.mjs
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(web, "..");

const published = join(repo, "evals", "results", "published");
if (existsSync(published)) {
  const files = readdirSync(published).filter((f) => f.endsWith(".json")).sort();
  const newest = files.at(-1);
  if (newest) {
    const data = JSON.parse(readFileSync(join(published, newest), "utf8"));
    writeFileSync(join(web, "lib", "results.generated.json"), JSON.stringify({ available: true, artifact: newest, data }, null, 2) + "\n");
    console.log("sync-results: wrote", newest);
  }
} else {
  console.log("sync-results: no published artifacts here; keeping the committed copy");
}

const assets = join(repo, "docs", "assets");
if (existsSync(assets)) {
  mkdirSync(join(web, "public", "images"), { recursive: true });
  for (const name of ["how-it-works.svg", "ai-agents.svg"]) {
    if (existsSync(join(assets, name))) copyFileSync(join(assets, name), join(web, "public", "images", name));
  }
}
