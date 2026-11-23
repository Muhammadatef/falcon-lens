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

// Live held-out false-alarm measurement: the newest evals/results/published/fp_regress/*.json (by created_at)
// that carries the per-web-host split. Only the summary is bundled (not the 200 per-domain items).
const fpDir = join(published, "fp_regress");
if (existsSync(fpDir)) {
  const cands = readdirSync(fpDir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => ({ f, d: JSON.parse(readFileSync(join(fpDir, f), "utf8")) }))
    .filter(({ d }) => d && d.by_serves_web && d.false_positive_rate)
    .sort((a, b) => String(a.d.created_at).localeCompare(String(b.d.created_at)));
  const best = cands.at(-1);
  if (best) {
    const summary = { ...best.d };
    delete summary.items;
    writeFileSync(join(web, "lib", "fp-regress.generated.json"), JSON.stringify({ available: true, artifact: best.f, data: summary }, null, 2) + "\n");
    console.log("sync-results: fp_regress", best.f);
  }
}

const assets = join(repo, "docs", "assets");
if (existsSync(assets)) {
  mkdirSync(join(web, "public", "images"), { recursive: true });
  for (const name of ["how-it-works.svg", "ai-agents.svg", "architecture.svg", "investigator.svg", "sentinel.svg", "agent-investigator-steps.svg", "agent-sentinel-steps.svg"]) {
    if (existsSync(join(assets, name))) copyFileSync(join(assets, name), join(web, "public", "images", name));
  }
}

// DSPy before/after rows (local route only) from evals/results/published/dspy/*.json, kept to the fields the docs table shows.
// Empty when the folder is absent on this tree: the page then shows no table. Outside the monorepo the committed copy stays.
if (existsSync(published)) {
  const dir = join(published, "dspy");
  const rows = [];
  if (existsSync(dir)) {
    for (const f of readdirSync(dir).filter((x) => x.endsWith(".json")).sort()) {
      const d = JSON.parse(readFileSync(join(dir, f), "utf8"));
      if (d.route !== "local" || !d.before_val || !d.after_val) continue;
      rows.push({ artifact: f, role: d.role, model: d.model, synthetic: d.synthetic_data === true, adopted: d.adopted === true, before: d.before_val, after: d.after_val, paired: d.paired_diff ?? null });
    }
  }
  writeFileSync(join(web, "lib", "dspy.generated.json"), JSON.stringify(rows, null, 2) + "\n");
  console.log("sync-results: dspy rows", rows.length);
}

// Capability flags: one source for every "Live / In progress" badge on the judge pages.
// Reuses scripts/submission/capabilities.py probes (the submission's own truthfulness source), minus
// the `gate:` probes (those record L1 sign-off, not whether the code is in the tree). Falls back to the
// committed lib/capabilities.generated.json when the repo or python3 is absent (Docker build context).
const PY = `
import json, sys
sys.path.insert(0, "scripts/submission")
import capabilities as c
want = ["message_check", "email_check", "image_check", "injection_defence", "investigator", "sentinel_agent", "rest_api", "mcp", "stix", "url_check", "brand_check", "pipeline", "audit_log", "sentinel_rules", "observability", "sovereign", "pwa"]
out = {}
for cap in c.CAPABILITIES:
    if cap.id in want:
        out[cap.id] = all(c.probe(c.ROOT, s) for s in cap.probes if not s.startswith("gate:"))
out["t1_measured_model"] = any(c.probe(c.ROOT, s) for s in ("grep:services/worker/src/**/*.py::t1_model", "grep:packages/falcon_core/src/falcon_core/cascade/*.py::t1_model"))
# DSPy compiled prompts: live only when the frozen-prompt loader AND at least one adopted compiled file are in the tree.
out["dspy_compiled_prompts"] = c.probe(c.ROOT, "path:packages/falcon_core/src/falcon_core/prompts/compiled/__init__.py") and c.probe(c.ROOT, "path:packages/falcon_core/src/falcon_core/prompts/compiled/*.json")
# LLM tracing: live only when a service start-up really calls setup_tracing( (not just defines it) and the collector forwards to Phoenix.
out["llm_tracing"] = c.probe(c.ROOT, r"grep:services/*/src/**/*.py::(?<!def )setup_tracing\\(") and c.probe(c.ROOT, "grep:infra/otel/otel-collector.yml::otlphttp/phoenix")
print(json.dumps(out))
`;
if (existsSync(join(repo, "scripts", "submission", "capabilities.py"))) {
  try {
    // `test:` probes run pytest, so they need the repo's uv environment; plain python3 would report them false.
    let out;
    try {
      out = execFileSync("uv", ["run", "--quiet", "python", "-c", PY], { cwd: repo, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 600_000 });
    } catch {
      out = execFileSync("python3", ["-c", PY], { cwd: repo, encoding: "utf8", timeout: 600_000 });
    }
    const flags = JSON.parse(out.trim().split("\n").at(-1));
    writeFileSync(join(web, "lib", "capabilities.generated.json"), JSON.stringify(flags, null, 2) + "\n");
    console.log("sync-results: capabilities", JSON.stringify(flags));
  } catch (error) {
    console.log("sync-results: capability probes unavailable, keeping the committed copy:", String(error).slice(0, 120));
  }
}
