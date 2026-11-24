/**
 * Operator history of Investigator checks: client mirror of `VerdictSummary` (services/api history.py,
 * contracts/openapi.yaml `GET /v1/verdicts`). Everything from the network goes through `parseSummary`, so a hostile
 * payload can never put a non-string into the tree. The summary carries no raw input and no personal data.
 */
import { CHANNEL_VALUES, TIERS, VERDICTS, VERDICT_ID_RE, type Channel, type DataSource, type InputType, type Tier, type VerdictLabel } from "./contracts";

export interface AgentSummary {
  tiers_run: Tier[];
  extractor_ran: boolean;
  investigator_ran: boolean;
  tool_calls: number;
  llm_calls: number;
}

export interface VerdictSummary {
  verdict_id: string;
  created_at: string;
  input_type: InputType;
  /** Defanged host for links; null for messages, emails and images. */
  display: string | null;
  verdict: VerdictLabel;
  risk_score: number;
  degraded: boolean;
  degraded_reasons: string[];
  tier_reached: Tier;
  model_route: "cloud" | "local" | "none";
  source: DataSource;
  /** Which client asked; absent when the check did not say. */
  channel?: Channel;
  agent: AgentSummary;
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): T | null => (typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null);
const count = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.min(Math.round(v), 9999) : 0);

export function parseSummary(raw: unknown): VerdictSummary | null {
  if (!isObj(raw)) return null;
  const declared = oneOf(raw.verdict, VERDICTS);
  const tier = oneOf(raw.tier_reached, TIERS);
  const inputType = oneOf(raw.input_type, ["url", "message", "email", "image"] as const);
  if (typeof raw.verdict_id !== "string" || !VERDICT_ID_RE.test(raw.verdict_id) || !declared || !tier || !inputType) return null;
  const a = isObj(raw.agent) ? raw.agent : {};
  const tiers = (Array.isArray(a.tiers_run) ? a.tiers_run : []).map((t) => oneOf(t, TIERS)).filter((t): t is Tier => t !== null);
  const degraded = raw.degraded === true;
  return {
    verdict_id: raw.verdict_id,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    input_type: inputType,
    display: typeof raw.display === "string" && raw.display.length <= 300 ? raw.display : null,
    // Same client-side invariant as parseVerdict: a degraded check is never shown as "no warning signs".
    verdict: declared === "no_warning_signs" && degraded ? "suspicious" : declared,
    risk_score: Math.max(0, Math.min(100, Math.round(typeof raw.risk_score === "number" && Number.isFinite(raw.risk_score) ? raw.risk_score : 0))),
    degraded,
    degraded_reasons: (Array.isArray(raw.degraded_reasons) ? raw.degraded_reasons : []).filter((r): r is string => typeof r === "string" && /^[a-z0-9][a-z0-9_.:-]{0,63}$/.test(r)).slice(0, 8),
    tier_reached: tier,
    model_route: oneOf(raw.model_route, ["cloud", "local", "none"] as const) ?? "none",
    source: oneOf(raw.source, ["live", "replay", "synthetic", "fixture"] as const) ?? "live",
    ...(oneOf(raw.channel, CHANNEL_VALUES) ? { channel: oneOf(raw.channel, CHANNEL_VALUES) as Channel } : {}),
    agent: {
      tiers_run: tiers.length ? tiers : TIERS.slice(0, TIERS.indexOf(tier) + 1),
      extractor_ran: a.extractor_ran === true,
      investigator_ran: a.investigator_ran === true,
      tool_calls: count(a.tool_calls),
      llm_calls: count(a.llm_calls),
    },
  };
}

/** Newest first; an update to a known check replaces it in place. */
export function upsertSummary(current: VerdictSummary[], incoming: VerdictSummary, max = 200): VerdictSummary[] {
  const without = current.filter((s) => s.verdict_id !== incoming.verdict_id);
  return [incoming, ...without].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, max);
}

export const checkHref = (id: string, demo = false): string => `/checks/${id}${demo ? "?demo=1" : ""}`;

/** `hxxps://user:pw@a[.]b/p?q` becomes `hxxps://a[.]b`: host only, for display of a verdict's input on operator pages. */
export function hostOnly(canonical: string | null | undefined): string | null {
  if (!canonical) return null;
  const m = /^(hxxps?|https?):\/\/(?:[^/?#@]*@)?([^/?#:\s]+)/i.exec(canonical.trim());
  if (!m) return null;
  const scheme = m[1]!.toLowerCase().startsWith("hxxp") ? m[1]!.toLowerCase() : m[1]!.toLowerCase().replace("http", "hxxp");
  return `${scheme}://${m[2]!.replace(/\[\.\]/g, ".").replace(/\./g, "[.]")}`;
}
