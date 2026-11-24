// Per-area compact bundle for /results: faithfulness, stability, route_compare, cost_per_check, sandbox_t2,
// brand_new_pages, t3_investigator, synthetic_split, message_text, redteam, arabic_clarity and the fits.
// Only what the page shows: a few rows per area (value, k, n, 95% CI), provenance, route/model, artifact name + date,
// caveat. The newest artifact per area wins (by created_at / generated_at). Absent folders are skipped.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export function syncEvalAreas(web, published) {
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
  const readNewest = (area, pick) => readAll(area, pick).at(-1) ?? null;

  const rate = (o) => {
    if (!o || typeof o.value !== "number") return null;
    const ci = Array.isArray(o.ci95) ? o.ci95 : [o.ci_low, o.ci_high];
    return { kind: "rate", value: o.value, k: o.k ?? null, n: o.n ?? null, lo: ci[0] ?? null, hi: ci[1] ?? null };
  };
  const count = (value, n = null) => (typeof value === "number" ? { kind: "count", value, k: null, n, lo: null, hi: null } : null);
  const usd = (o) => (o && typeof o.mean === "number" ? { kind: "usd", value: o.mean, k: null, n: o.n ?? null, lo: o.ci95?.[0] ?? null, hi: o.ci95?.[1] ?? null } : null);
  const num = (value, n = null) => (typeof value === "number" ? { kind: "num", value, k: null, n, lo: null, hi: null } : null);
  const str = (v) => (typeof v === "string" ? v : v == null ? "" : JSON.stringify(v));

  const areas = {};
  const add = (area, hit, rows, extra = {}) => {
    if (!hit) return;
    const d = hit.d;
    areas[area] = {
      artifact: hit.f,
      date: dateOf(d),
      provenance: str(d.provenance ?? d.label ?? d.data),
      route: str(d.model_route),
      model: str(d.model_ids?.local ?? d.model_ids?.llm ?? d.model_ids?.t1 ?? d.model_ids?.reasons),
      caveat: str(d.caveat ?? d.coverage_caveat),
      rows: Object.fromEntries(Object.entries(rows(d)).filter(([, v]) => v)),
      notEvaluated: [],
      ...extra,
    };
  };

  add("faithfulness", readNewest("faithfulness"), (d) => {
    const a = d.user_facing_reasons_template_only?.cascade_fixture_verdicts_synthetic?.all_cascade_verdicts;
    const s = d.sentinel_llm_summaries ?? {};
    return {
      reasons_faithful: rate(a?.reasons_faithful),
      verdicts_fully_faithful: rate(a?.verdicts_fully_faithful),
      sentinel_cloud_claims_kept: rate(s.cloud?.claims_kept_by_verifier),
      sentinel_cloud_kept_cite_valid: rate(s.cloud?.kept_claims_cite_valid_evidence),
      sentinel_local_claims_kept: rate(s.local?.claims_kept_by_verifier),
      sentinel_local_kept_cite_valid: rate(s.local?.kept_claims_cite_valid_evidence),
    };
  });
  add("stability", readNewest("stability"), (d) => ({
    ai_on_all_three_identical: rate(d.ai_layers_on?.label_agreement_all_three_identical),
    ai_on_among_completed: rate(d.ai_layers_on?.label_agreement_among_items_with_three_completed_runs),
    ai_off_all_three_identical: rate(d.deterministic_control_ai_off?.label_agreement_all_three_identical),
  }));
  add("route_compare", readNewest("route_compare"), (d) => ({
    exact_label_agreement: rate(d.verdict_agreement?.exact_label),
    cloud_recall_warning: rate(d.accuracy_vs_author_labels?.cloud?.recall_warning_on_phishing_fixtures),
    local_recall_warning: rate(d.accuracy_vs_author_labels?.local?.recall_warning_on_phishing_fixtures),
    cloud_benign_warning: rate(d.accuracy_vs_author_labels?.cloud?.warning_rate_on_benign_fixtures),
    local_benign_warning: rate(d.accuracy_vs_author_labels?.local?.warning_rate_on_benign_fixtures),
  }));
  {
    const hit = readNewest("cost_per_check");
    add("cost_per_check", hit, (d) => ({
      cloud_usd_per_check: usd(d.cloud_route?.usd_per_check),
      cloud_usd_per_1000: num(d.cloud_route?.usd_per_1000_checks_at_mean, d.cloud_route?.checks),
      cloud_usd_p95: num(d.cloud_route?.usd_per_check_p95, d.cloud_route?.checks),
      local_usd_per_check: num(d.local_route?.marginal_api_cost_usd_per_check, d.local_route?.checks),
    }), { notEvaluated: hit?.d.local_route?.energy?.status === "not_evaluated" ? ["energy"] : [] });
  }
  {
    const hit = readNewest("sandbox_t2");
    const last = hit?.d.real_site_render_health_held_out_legit?.artifacts?.at(-1);
    const fx = hit?.d.t2_contribution_on_fixtures_offline_renderer?.cloud_all;
    add("sandbox_t2", hit, () => ({
      render_reached_of_web: rate(last?.t2_reached_of_web),
      render_clean_of_attempted: rate(last?.t2_render_clean_of_attempted),
      render_degraded_of_attempted: rate(last?.t2_degraded_of_attempted),
      fixture_dangerous_after_t1: rate(fx?.dangerous_after_T1),
      fixture_dangerous_after_t2: rate(fx?.dangerous_after_T2),
    }), { renderArtifact: last?.artifact ?? "", notEvaluated: hit?.d.phishing_side_t2_recall?.status === "not_evaluated" ? ["phishing_side_t2_recall"] : [] });
  }
  add("brand_new_pages", readNewest("brand_new_pages"), (d) => ({
    lookalike_dangerous: rate(d.groups?.new_lookalike_brand_pages?.dangerous_final),
    generic_warning: rate(d.groups?.new_generic_credential_pages?.warning_final),
    benign_warning: rate(d.groups?.benign_controls_novel_hosts?.warning_final),
    benign_dangerous: rate(d.groups?.benign_controls_novel_hosts?.dangerous_final),
  }));
  add("t3_investigator", readNewest("t3_investigator"), (d) => ({
    cloud_reached_t3: rate(d.by_route?.cloud?.reached_T3),
    cloud_label_changed: rate(d.by_route?.cloud?.label_changed_vs_no_T3),
    cloud_forbidden_tool: rate(d.by_route?.cloud?.forbidden_tool_call_rate),
    local_reached_t3: rate(d.by_route?.local?.reached_T3),
    local_label_changed: rate(d.by_route?.local?.label_changed_vs_no_T3),
    local_forbidden_tool: rate(d.by_route?.local?.forbidden_tool_call_rate),
  }));
  {
    const hit = readNewest("synthetic_split");
    add("synthetic_split", hit, (d) => ({
      real_test_recall_warning: rate(d.real_items_scored?.test?.recall_warning),
      real_test_fpr_warning: rate(d.real_items_scored?.test?.fpr_warning),
      synthetic_url_recall_warning: rate(d.synthetic_url_items_scored?.recall_warning),
      synthetic_url_fpr_warning: rate(d.synthetic_url_items_scored?.fpr_warning),
      synthetic_message_recall_warning: rate(d.synthetic_messages_scored?.recall_warning),
      synthetic_message_fpr_warning: rate(d.synthetic_messages_scored?.fpr_warning),
    }), { caveat: str(hit?.d.synthetic_url_items_scored?.caveat) });
  }
  {
    const hit = readNewest("message_text", (d) => d.kind === "message_text_eval");
    const sh = (split, which, m) => rate(hit?.d.results?.[split]?.[which]?.[m]);
    add("message_text", hit, () => ({
      test_recall: sh("test", "shipped", "recall"),
      test_fpr: sh("test", "shipped", "fpr"),
      test_rules_only_recall: sh("test", "rules_only_before", "recall"),
      val_recall: sh("val", "shipped", "recall"),
      val_fpr: sh("val", "shipped", "fpr"),
    }), { caveat: str(hit?.d.note) });
  }
  {
    const runs = readAll("redteam", (d) => d.suite === "redteam" && d.summary?.overall);
    const newest = runs.at(-1);
    if (newest) {
      const rows = {};
      for (const b of ["extended", "production"]) {
        const hit = runs.filter(({ d }) => d.llm_budget === b).at(-1);
        const r = hit?.d.summary.overall;
        if (!r) continue;
        // Each row cites the artifact it came from (the extended and production runs are separate files).
        rows[`${b}_harmful`] = { ...count(r.harmful, r.cases), artifact: hit.f };
        rows[`${b}_answered`] = { ...count(r.llm_ran, r.cases), artifact: hit.f };
      }
      add("redteam", newest, () => rows, { runs: runs.map(({ f, d }) => ({ artifact: f, budget: str(d.llm_budget), date: dateOf(d) })) });
    }
  }
  {
    const hit = readNewest("arabic_clarity");
    add("arabic_clarity", hit, (d) => ({
      action_sentences_within_budget: rate(d.automated_checks?.each_action_sentence_within_budget),
      reasons_within_budget: rate(d.automated_checks?.reason_within_budget),
      items: count(d.items, d.items),
    }), { notEvaluated: hit?.d.human_rating?.status === "pending_human_rating" ? ["human_rating"] : [] });
  }
  {
    const dir = join(published, "fits");
    const load = (f) => (existsSync(join(dir, f)) ? { f, d: JSON.parse(readFileSync(join(dir, f), "utf8")) } : null);
    const w = load("message_scam_intent_weight_fit.json");
    const c = load("model_cap_fit.json");
    if (w) {
      add("fit_message_weight", { f: w.f, d: w.d }, (d) => ({
        weight: num(d.chosen?.weight),
        val_recall: rate({ value: d.chosen?.val_recall, k: null, n: d.n_val_scam }),
        val_fpr: rate({ value: d.chosen?.val_fpr, k: null, n: d.n_val_legit }),
      }));
    }
    if (c) {
      add("fit_model_cap", { f: c.f, d: { ...c.d, provenance: `fitted on ${str(c.d.fitted_on)}` } }, (d) => ({
        margin: num(d.chosen?.margin),
        strong_adj: num(d.chosen?.strong_adj),
      }));
    }
  }
  writeFileSync(join(web, "lib", "eval-areas.generated.json"), JSON.stringify({ available: Object.keys(areas).length > 0, areas }, null, 2) + "\n");
  console.log("sync-results: eval areas", Object.keys(areas).join(","));
}
