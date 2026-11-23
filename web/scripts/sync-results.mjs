#!/usr/bin/env node
// Copies the newest PUBLISHED evaluation artifact (evals/results/published/*.json) into
// lib/results.generated.json, and the two explainer SVGs from docs/assets into public/images.
// The Results page renders only what this file holds: no number is typed into the web app.
// Outside the monorepo (the Docker build context is ./web) the sources are absent, so this is a
// no-op and the committed copies are used. Run: node scripts/sync-results.mjs
import { execFileSync } from "node:child_process";
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
  for (const name of ["how-it-works.svg", "ai-agents.svg", "architecture.svg", "investigator.svg", "sentinel.svg", "agent-investigator-steps.svg", "agent-sentinel-steps.svg"]) {
    if (existsSync(join(assets, name))) copyFileSync(join(assets, name), join(web, "public", "images", name));
  }
}

// Capability flags: one source for every "Live / In progress" badge on the judge pages.
// Reuses scripts/submission/capabilities.py probes (the submission's own truthfulness source), minus
// the `gate:` probes (those record L1 sign-off, not whether the code is in the tree). Falls back to the
// committed lib/capabilities.generated.json when the repo or python3 is absent (Docker build context).
const PY = `
import json, sys
sys.path.insert(0, "scripts/submission")
import capabilities as c
want = ["message_check", "email_check", "image_check", "injection_defence", "investigator"]
out = {}
for cap in c.CAPABILITIES:
    if cap.id in want:
        out[cap.id] = all(c.probe(c.ROOT, s) for s in cap.probes if not s.startswith("gate:"))
out["t1_measured_model"] = any(c.probe(c.ROOT, s) for s in ("grep:services/worker/src/**/*.py::t1_model", "grep:packages/falcon_core/src/falcon_core/cascade/*.py::t1_model"))
print(json.dumps(out))
`;
if (existsSync(join(repo, "scripts", "submission", "capabilities.py"))) {
  try {
    const flags = JSON.parse(execFileSync("python3", ["-c", PY], { cwd: repo, encoding: "utf8" }));
    writeFileSync(join(web, "lib", "capabilities.generated.json"), JSON.stringify(flags, null, 2) + "\n");
    console.log("sync-results: capabilities", JSON.stringify(flags));
  } catch (error) {
    console.log("sync-results: capability probes unavailable, keeping the committed copy:", String(error).slice(0, 120));
  }
}
