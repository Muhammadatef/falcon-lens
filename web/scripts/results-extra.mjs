// Extra bundle for the /results KPI sections (scripts/sync-results.mjs calls syncResultsExtra):
//  - per-KPI counts for recall / false-alarm / precision on val and test (from synthetic_split, which re-scores the
//    same frozen split and records its agreement with the main artifact),
//  - the real-vs-synthetic view (manifest counts, real re-score, synthetic fixtures, message_text),
//  - every held-out live false-alarm run (fp_regress) by date, with the commits between consecutive runs,
//  - red-team per category (newest run per deadline budget),
//  - extractor accuracy per route and cross-route agreement.
// Only summaries are bundled. Outside the monorepo (Docker context ./web) the sources are absent: no-op, committed copy stays.
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const rate = (o) => {
  if (!o || typeof o.value !== "number") return null;
  const ci = Array.isArray(o.ci95) ? o.ci95 : [o.ci_low, o.ci_high];
  return { value: o.value, k: o.k ?? null, n: o.n ?? null, lo: ci[0] ?? null, hi: ci[1] ?? null };
};
const nonNull = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v));
const text = (v) => (typeof v === "string" ? v : v == null ? "" : JSON.stringify(v));

/** REAL / SYNTHETIC / FIXTURE from the artifact's own provenance text; `fallback` only when the text names none. */
export function badgeOf(provenance, fallback) {
  const p = String(provenance ?? "").replace(/\bnot real\b/gi, "");
  const real = /\breal\b/i.test(p);
  const synth = /fixture|demo bank|synthetic/i.test(p);
  if (real && synth) return "MIXED";
  if (/fixture|demo bank/i.test(p)) return "FIXTURE";
  if (/synthetic/i.test(p)) return "SYNTHETIC";
  if (real) return "REAL";
  return fallback;
}

export function syncResultsExtra(web, published, repo) {
  if (!existsSync(published)) return;
  const readAll = (area, pick = () => true) => {
    const dir = join(published, area);
    if (!existsSync(dir)) return [];
    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => ({ f, d: JSON.parse(readFileSync(join(dir, f), "utf8")) }))
      .filter(({ d }) => pick(d))
      .sort((a, b) => dateOf(a.d).localeCompare(dateOf(b.d)));
  };
  const dateOf = (d) => String(d.created_at ?? d.generated_at ?? "");
  const out = { available: true };

  // The main artifact's own provenance: its scope line ("real data only").
  const topFiles = readdirSync(published).filter((f) => f.endsWith(".json")).sort();
  const main = topFiles.length ? JSON.parse(readFileSync(join(published, topFiles.at(-1)), "utf8")) : null;
  out.main = main ? { artifact: topFiles.at(-1), badge: badgeOf(main.scope, "REAL"), scope: text(main.scope) } : null;

  const sp = readAll("synthetic_split").at(-1);
  if (sp) {
    const d = sp.d;
    const side = (s) => s && nonNull({
      nLegit: s.n_legit ?? null,
      nPhishing: s.n_phishing ?? null,
      recallWarning: rate(s.recall_warning),
      fprWarning: rate(s.fpr_warning),
      precisionWarning: rate(s.precision_warning),
      recallDangerous: rate(s.recall_dangerous),
      fprDangerous: rate(s.fpr_dangerous),
    });
    const real = {};
    for (const split of ["val", "test"]) real[split] = side(d.real_items_scored?.[split]);
    const manifest = d.manifest_counts_by_kind_split_label?.real ?? {};
    out.realSynthetic = {
      artifact: sp.f,
      date: dateOf(d),
      provenance: text(d.provenance),
      separationRule: text(d.separation_rule),
      manifest: { real: d.manifest_totals?.real ?? null, synthetic: d.manifest_totals?.synthetic ?? null, realBySplit: Object.fromEntries(Object.entries(manifest).filter(([, v]) => v && typeof v === "object").map(([k, v]) => [k, { legit: v.legit ?? 0, phishing: v.phishing ?? 0 }])) },
      matchesMain: ["val", "test"].every((s) => d.consistency_with_main_artifact?.[s]?.recall_matches_main_artifact === true && d.consistency_with_main_artifact?.[s]?.fpr_matches_main_artifact === true),
      real,
      syntheticUrls: side(d.synthetic_url_items_scored),
      syntheticUrlsCaveat: text(d.synthetic_url_items_scored?.caveat),
      syntheticMessages: side(d.synthetic_messages_scored),
      badges: { real: badgeOf("real (manifest items)", "REAL"), syntheticUrls: badgeOf("synthetic (Falcon Demo Bank fixtures)", "FIXTURE"), syntheticMessages: badgeOf("synthetic messages written for this suite", "SYNTHETIC") },
    };
  }

  const mt = readAll("message_text", (d) => d.kind === "message_text_eval").at(-1);
  if (mt) {
    const split = (s) => {
      const r = mt.d.results?.[s]?.shipped;
      return r && nonNull({ n: r.n ?? null, nScam: r.n_scam ?? null, nLegit: r.n_legit ?? null, recall: rate(r.recall), fpr: rate(r.fpr) });
    };
    out.messageText = { artifact: mt.f, date: dateOf(mt.d), provenance: text(mt.d.provenance), badge: badgeOf(mt.d.provenance, "SYNTHETIC"), val: split("val"), test: split("test") };
  }

  // Held-out live false alarms, every run by date, with the commits between consecutive runs.
  const fp = readAll("fp_regress", (d) => d.kind === "fp_regress" && d.false_positive_rate);
  const git = (args) => {
    try {
      return execFileSync("git", ["-C", repo, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    } catch {
      return null;
    }
  };
  const runs = fp.map(({ f, d }, i) => {
    const prev = i > 0 ? fp[i - 1].d.git_sha : null;
    let changes = null;
    if (prev && d.git_sha && prev !== d.git_sha) {
      const log = git(["log", "--no-merges", "--format=%s", `${prev}..${d.git_sha}`]);
      if (log !== null) {
        const subjects = log.split("\n").filter(Boolean);
        changes = { count: subjects.length, subjects: subjects.slice(0, 4) };
      }
    }
    const web_ = d.by_serves_web?.serves_web_page;
    const noweb = d.by_serves_web?.no_web_host;
    const fpr = rate(d.false_positive_rate);
    const wilson = Array.isArray(d.wilson95) ? d.wilson95 : null;
    const hay = JSON.stringify([d.note, d.caveat, d.notes]);
    return {
      artifact: f,
      date: dateOf(d),
      set: text(d.set),
      sha: String(d.git_sha ?? "").slice(0, 7),
      n: d.n ?? null,
      all: fpr && { ...fpr, k: null, n: d.n ?? null },
      web: web_ && rate({ ...web_.false_positive_rate, n: web_.n }),
      noWeb: noweb && rate({ ...noweb.false_positive_rate, n: noweb.n }),
      wilson,
      falseDangerous: typeof d.false_dangerous === "number" ? d.false_dangerous : null,
      partialReads: typeof d.partial_reads === "number" ? d.partial_reads : null,
      postHoc: d.post_hoc === true || /post.?hoc/i.test(hay),
      changes,
      badge: badgeOf("real held-out legitimate domains", "REAL"),
    };
  });
  // Rate rows need k = round(rate * n) only when the artifact gives counts; keep value/ci/n as published.
  out.fpHistory = runs;

  // Red-team per category, newest run per deadline budget.
  const rt = readAll("redteam", (d) => d.suite === "redteam" && d.summary?.by_category);
  out.redteam = {};
  for (const b of ["extended", "production"]) {
    const hit = rt.filter(({ d }) => d.llm_budget === b).at(-1);
    if (!hit) continue;
    const cats = {};
    for (const [c, v] of Object.entries(hit.d.summary.by_category)) cats[c] = { cases: v.cases, harmful: v.harmful, answered: v.llm_ran, lo: v.ci95?.[0] ?? null, hi: v.ci95?.[1] ?? null };
    const o = hit.d.summary.overall;
    out.redteam[b] = { artifact: hit.f, date: dateOf(hit.d), provenance: text(hit.d.data), badge: badgeOf(hit.d.data, "FIXTURE"), overall: { cases: o.cases, harmful: o.harmful, answered: o.llm_ran, lo: o.ci95?.[0] ?? null, hi: o.ci95?.[1] ?? null }, categories: cats };
  }

  // Extractor accuracy per route, and cross-route agreement.
  const rc = readAll("route_compare").at(-1);
  if (rc) {
    const route = (r) => r && { model: text(r.model), n: r.n ?? null, rows: nonNull({ all_four: rate(r.field_accuracy?.all_four_fields_exact), brand: rate(r.field_accuracy?.claimed_brand_exact), language: rate(r.field_accuracy?.language_exact), script: rate(r.field_accuracy?.script_category_exact), no_extraction: rate(r.no_extraction) }) };
    const agree = rc.d.extractor_route_agreement ?? {};
    out.extractor = { artifact: rc.f, date: dateOf(rc.d), provenance: text(rc.d.provenance), badge: badgeOf(rc.d.provenance, "FIXTURE"), cloud: route(rc.d.extractor_field_accuracy?.cloud), local: route(rc.d.extractor_field_accuracy?.local), agreement: nonNull({ brand: rate(agree.brand), language: rate(agree.language), requested_data: rate(agree.requested_data), script: rate(agree.script_category) }) };
  }

  writeFileSync(join(web, "lib", "results-extra.generated.json"), JSON.stringify(out, null, 2) + "\n");
  console.log("sync-results: results-extra", Object.keys(out).join(","));
}
