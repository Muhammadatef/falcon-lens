import { DEMO_DANGEROUS, DEMO_NWS } from "./demo";
import type { Verdict } from "./contracts";
import { hostOnly, type VerdictSummary } from "./history";

/* Synthetic rows for /history?demo=1, built from the built-in demo verdicts ("Falcon Demo Bank"). Never real checks. */
const rowOf = (v: Verdict, extra: Partial<VerdictSummary["agent"]> = {}): VerdictSummary => ({
  verdict_id: v.verdict_id,
  created_at: v.created_at,
  input_type: v.input_type,
  display: v.input_type === "url" ? hostOnly(v.canonical_url) : null,
  verdict: v.verdict,
  risk_score: v.risk_score,
  degraded: v.degraded,
  degraded_reasons: v.degraded_reasons ?? [],
  tier_reached: v.tier_reached,
  model_route: v.model_route,
  source: "synthetic",
  agent: {
    tiers_run: (["T0", "T1", "T2", "T3"] as const).slice(0, ["T0", "T1", "T2", "T3"].indexOf(v.tier_reached) + 1),
    extractor_ran: false,
    investigator_ran: false,
    tool_calls: (v.trace ?? []).filter((s) => s.kind === "tool").length,
    llm_calls: (v.trace ?? []).filter((s) => s.kind === "llm").length,
    ...extra,
  },
});

export const DEMO_CHECK_ROWS: VerdictSummary[] = [rowOf(DEMO_NWS), rowOf(DEMO_DANGEROUS)].sort((a, b) => b.created_at.localeCompare(a.created_at));
export const DEMO_CHECKS: Record<string, Verdict> = { [DEMO_DANGEROUS.verdict_id]: DEMO_DANGEROUS, [DEMO_NWS.verdict_id]: DEMO_NWS };
