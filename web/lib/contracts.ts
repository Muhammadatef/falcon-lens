/**
 * TypeScript mirror of contracts/verdict.schema.json, evidence.schema.json and
 * incident.schema.json, plus runtime guards. Everything that arrives from the network
 * goes through `parseVerdict` / `parseIncident` before it reaches a component, so a
 * malformed or hostile payload can never put a non-string into the tree.
 * tests/unit/contracts.test.ts checks the fixtures against the real JSON schemas.
 */

export type VerdictLabel = "dangerous" | "suspicious" | "no_warning_signs";
export type Tier = "T0" | "T1" | "T2" | "T3";
export type InputType = "url" | "message" | "email" | "image";
export type Polarity = "risk" | "trust" | "neutral";
export type DataSource = "live" | "replay" | "synthetic" | "fixture";
export type Lang = "ar" | "en";

export const TIERS: readonly Tier[] = ["T0", "T1", "T2", "T3"];
export const VERDICTS: readonly VerdictLabel[] = ["dangerous", "suspicious", "no_warning_signs"];

export interface Bilingual {
  ar: string;
  en: string;
}
export interface BilingualList {
  ar: string[];
  en: string[];
}

export interface Evidence {
  id: string;
  signal: string;
  family: string;
  observed: unknown;
  display?: { ar?: string; en?: string };
  weight: number;
  polarity?: Polarity;
  hard_rule?: string | null;
  source: string;
  tier: Tier;
  confidence?: number;
  latency_ms?: number;
  error?: string | null;
}

export interface Reason extends Bilingual {
  evidence_ids: string[];
  generated_by?: "llm" | "template";
}

export interface ReportChannel {
  label_ar: string;
  label_en: string;
  value: string;
  source_url: string;
  retrieved_at: string;
}

export interface TraceStep {
  step: number;
  kind: "tier" | "tool" | "llm" | "rule";
  name?: string;
  summary: string;
  evidence_added?: string[];
  ms?: number;
}

export interface Verdict {
  schema_version: "1.0";
  verdict_id: string;
  input_type: InputType;
  input_fingerprint?: string;
  canonical_url?: string | null;
  verdict: VerdictLabel;
  risk_score: number;
  calibrated_probability: number;
  impersonated_brand?: { brand_id: string; name_ar: string; name_en: string; official_domains?: string[] } | null;
  evidence: Evidence[];
  reasons: Reason[];
  actions: {
    now: BilingualList;
    if_already_acted: BilingualList;
    report: Bilingual & { channels?: ReportChannel[] };
    caution?: BilingualList;
  };
  tier_reached: Tier;
  model_route: "cloud" | "local" | "none";
  degraded: boolean;
  degraded_reasons?: string[];
  final: boolean;
  trace?: TraceStep[];
  screenshot_url?: string | null;
  source?: DataSource;
  latency_ms: number;
  created_at: string;
}

export type Severity = "low" | "medium" | "high" | "critical";
export type IncidentStatus = "open" | "triaging" | "awaiting_approval" | "mitigated" | "closed" | "false_positive";
export type ActionStatus = "proposed" | "executed" | "awaiting_approval" | "approved" | "rejected" | "reverted" | "failed";

export interface IncidentAction {
  action_id: string;
  tool: string;
  mode: "internal_auto" | "external_draft";
  status: ActionStatus;
  draft?: { recipient_kind?: string; subject?: string; body_ar?: string; body_en?: string } | null;
  evidence_ids: string[];
  approved_by?: string | null;
  at?: string;
}

export interface Incident {
  incident_id: string;
  type: string;
  severity: Severity;
  severity_reason?: { ar?: string; en?: string; evidence_ids?: string[] };
  status: IncidentStatus;
  brand_id?: string | null;
  rule_ids: string[];
  correlation_keys?: Record<string, string>;
  indicators: { kind: string; value_defanged: string; first_seen: string; blocked_until?: string | null }[];
  linked_verdicts: string[];
  timeline: { at: string; what: string; event_id?: string }[];
  summary?: { ar?: string; en?: string; generated_by?: string; model_route?: string } | null;
  actions: IncidentAction[];
  source: DataSource;
  created_at: string;
  updated_at: string;
}

/* ── Guards ───────────────────────────────────────────────────────────── */

export const VERDICT_ID_RE = /^vd_[0-9A-HJKMNP-TV-Z]{26}$/;
export const INCIDENT_ID_RE = /^inc_[0-9A-HJKMNP-TV-Z]{26}$/;

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const optStr = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);
const num = (v: unknown, fallback = 0): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): T | null =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;

const bilingualList = (v: unknown): BilingualList =>
  isObj(v) ? { ar: strList(v.ar), en: strList(v.en) } : { ar: [], en: [] };

function parseEvidence(raw: unknown): Evidence | null {
  if (!isObj(raw)) return null;
  const tier = oneOf(raw.tier, TIERS);
  if (typeof raw.id !== "string" || !raw.id.startsWith("ev_") || !tier) return null;
  const display = isObj(raw.display) ? { ar: optStr(raw.display.ar), en: optStr(raw.display.en) } : undefined;
  return {
    id: raw.id,
    signal: str(raw.signal),
    family: str(raw.family),
    observed: raw.observed,
    display,
    weight: num(raw.weight),
    polarity: oneOf(raw.polarity, ["risk", "trust", "neutral"] as const) ?? "neutral",
    hard_rule: optStr(raw.hard_rule) ?? null,
    source: str(raw.source),
    tier,
    confidence: typeof raw.confidence === "number" ? raw.confidence : undefined,
    latency_ms: typeof raw.latency_ms === "number" ? raw.latency_ms : undefined,
    error: optStr(raw.error) ?? null,
  };
}

function parseTrace(raw: unknown): TraceStep[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const out: TraceStep[] = [];
  for (const item of raw) {
    if (!isObj(item)) continue;
    const kind = oneOf(item.kind, ["tier", "tool", "llm", "rule"] as const);
    if (!kind || typeof item.summary !== "string") continue;
    out.push({
      step: num(item.step, out.length),
      kind,
      name: optStr(item.name),
      summary: item.summary,
      evidence_added: strList(item.evidence_added),
      ms: typeof item.ms === "number" ? item.ms : undefined,
    });
  }
  return out.sort((a, b) => a.step - b.step);
}

/**
 * Shown when a `no_warning_signs` verdict arrives without `actions.caution` (contract
 * invariant 3). The UI never shows that verdict without a "stay careful" block.
 */
export const DEFAULT_CAUTION: BilingualList = {
  ar: ["عدم وجود علامات تحذير ليس ضماناً.", "لا تشارك رمز التحقق (OTP) أو كلمة المرور مع أي شخص.", "إذا استعجلك أحد أو طلب تحويل مال، توقّف وتحقق."],
  en: ["Finding no warning signs is not a guarantee.", "Never share a one-time code (OTP) or password with anyone.", "If someone rushes you or asks for a money transfer, stop and verify."],
};

/**
 * Returns a sanitised Verdict, or null when the payload is not a usable verdict.
 *
 * The client enforces two contract invariants itself instead of trusting the API:
 *  - invariant 4: a degraded verdict is never `no_warning_signs`. If one arrives it is shown
 *    as `suspicious` with the "could not complete every check" note (never upgraded to a
 *    reassuring answer on incomplete evidence);
 *  - invariant 3: `no_warning_signs` always carries a caution list (DEFAULT_CAUTION fills
 *    any language that is missing or empty).
 */
export function parseVerdict(raw: unknown): Verdict | null {
  if (!isObj(raw)) return null;
  const declared = oneOf(raw.verdict, VERDICTS);
  const verdict: VerdictLabel | null = declared === "no_warning_signs" && raw.degraded === true ? "suspicious" : declared;
  const tier = oneOf(raw.tier_reached, TIERS);
  const inputType = oneOf(raw.input_type, ["url", "message", "email", "image"] as const);
  if (typeof raw.verdict_id !== "string" || !VERDICT_ID_RE.test(raw.verdict_id)) return null;
  if (!verdict || !tier || !inputType || typeof raw.final !== "boolean") return null;

  const evidence = (Array.isArray(raw.evidence) ? raw.evidence : []).map(parseEvidence).filter((e): e is Evidence => e !== null);
  const ids = new Set(evidence.map((e) => e.id));

  const reasons: Reason[] = [];
  for (const r of Array.isArray(raw.reasons) ? raw.reasons : []) {
    if (!isObj(r) || typeof r.ar !== "string" || typeof r.en !== "string") continue;
    // Contract invariant 1: a reason may cite only evidence present in this verdict.
    reasons.push({ ar: r.ar, en: r.en, evidence_ids: strList(r.evidence_ids).filter((id) => ids.has(id)) });
    if (reasons.length === 3) break;
  }

  const a = isObj(raw.actions) ? raw.actions : {};
  const report = isObj(a.report) ? a.report : {};
  const channels: ReportChannel[] = [];
  for (const c of Array.isArray(report.channels) ? report.channels : []) {
    if (!isObj(c) || typeof c.value !== "string") continue;
    channels.push({
      label_ar: str(c.label_ar),
      label_en: str(c.label_en),
      value: c.value,
      source_url: str(c.source_url),
      retrieved_at: str(c.retrieved_at),
    });
  }

  const b = raw.impersonated_brand;
  const brand =
    isObj(b) && typeof b.name_ar === "string" && typeof b.name_en === "string"
      ? { brand_id: str(b.brand_id), name_ar: b.name_ar, name_en: b.name_en, official_domains: strList(b.official_domains) }
      : null;

  return {
    schema_version: "1.0",
    verdict_id: raw.verdict_id,
    input_type: inputType,
    input_fingerprint: optStr(raw.input_fingerprint),
    canonical_url: optStr(raw.canonical_url) ?? null,
    verdict,
    risk_score: Math.max(0, Math.min(100, Math.round(num(raw.risk_score)))),
    calibrated_probability: num(raw.calibrated_probability),
    impersonated_brand: brand,
    evidence,
    reasons,
    actions: {
      now: bilingualList(a.now),
      if_already_acted: bilingualList(a.if_already_acted),
      report: { ar: str(report.ar), en: str(report.en), channels },
      caution: cautionFor(verdict, a.caution),
    },
    tier_reached: tier,
    model_route: oneOf(raw.model_route, ["cloud", "local", "none"] as const) ?? "none",
    degraded: raw.degraded === true,
    degraded_reasons: strList(raw.degraded_reasons),
    final: raw.final,
    trace: parseTrace(raw.trace),
    source: oneOf(raw.source, ["live", "replay", "synthetic", "fixture"] as const) ?? "live",
    latency_ms: num(raw.latency_ms),
    created_at: str(raw.created_at),
  };
}

function cautionFor(verdict: VerdictLabel, raw: unknown): BilingualList | undefined {
  const given = isObj(raw) ? bilingualList(raw) : undefined;
  if (verdict !== "no_warning_signs") return given;
  return { ar: given?.ar.length ? given.ar : DEFAULT_CAUTION.ar, en: given?.en.length ? given.en : DEFAULT_CAUTION.en };
}

const SEVERITIES: readonly Severity[] = ["low", "medium", "high", "critical"];
const INCIDENT_STATUSES: readonly IncidentStatus[] = ["open", "triaging", "awaiting_approval", "mitigated", "closed", "false_positive"];
const ACTION_STATUSES: readonly ActionStatus[] = ["proposed", "executed", "awaiting_approval", "approved", "rejected", "reverted", "failed"];

const optBilingual = (v: unknown): { ar?: string; en?: string } | undefined =>
  isObj(v) ? { ar: optStr(v.ar), en: optStr(v.en) } : undefined;

export function parseIncident(raw: unknown): Incident | null {
  if (!isObj(raw)) return null;
  const severity = oneOf(raw.severity, SEVERITIES);
  const status = oneOf(raw.status, INCIDENT_STATUSES);
  if (typeof raw.incident_id !== "string" || !INCIDENT_ID_RE.test(raw.incident_id) || !severity || !status) return null;

  const keys: Record<string, string> = {};
  if (isObj(raw.correlation_keys)) {
    for (const [k, v] of Object.entries(raw.correlation_keys)) {
      if (typeof v === "string" || typeof v === "number") keys[k] = String(v);
    }
  }
  const indicators: Incident["indicators"] = [];
  for (const i of Array.isArray(raw.indicators) ? raw.indicators : []) {
    if (!isObj(i) || typeof i.value_defanged !== "string") continue;
    indicators.push({ kind: str(i.kind), value_defanged: i.value_defanged, first_seen: str(i.first_seen), blocked_until: optStr(i.blocked_until) ?? null });
  }
  const timeline: Incident["timeline"] = [];
  for (const t of Array.isArray(raw.timeline) ? raw.timeline : []) {
    if (!isObj(t) || typeof t.what !== "string") continue;
    timeline.push({ at: str(t.at), what: t.what, event_id: optStr(t.event_id) });
  }
  const actions: IncidentAction[] = [];
  for (const x of Array.isArray(raw.actions) ? raw.actions : []) {
    if (!isObj(x) || typeof x.action_id !== "string") continue;
    const actionStatus = oneOf(x.status, ACTION_STATUSES);
    if (!actionStatus) continue;
    const d = x.draft;
    actions.push({
      action_id: x.action_id,
      tool: str(x.tool),
      mode: x.mode === "external_draft" ? "external_draft" : "internal_auto",
      status: actionStatus,
      draft: isObj(d) ? { recipient_kind: optStr(d.recipient_kind), subject: optStr(d.subject), body_ar: optStr(d.body_ar), body_en: optStr(d.body_en) } : null,
      evidence_ids: strList(x.evidence_ids),
      approved_by: optStr(x.approved_by) ?? null,
      at: optStr(x.at),
    });
  }
  const sr = raw.severity_reason;
  return {
    incident_id: raw.incident_id,
    type: str(raw.type),
    severity,
    severity_reason: isObj(sr) ? { ar: optStr(sr.ar), en: optStr(sr.en), evidence_ids: strList(sr.evidence_ids) } : undefined,
    status,
    brand_id: optStr(raw.brand_id) ?? null,
    rule_ids: strList(raw.rule_ids),
    correlation_keys: keys,
    indicators,
    linked_verdicts: strList(raw.linked_verdicts),
    timeline,
    summary: optBilingual(raw.summary) ?? null,
    actions,
    source: oneOf(raw.source, ["live", "replay", "synthetic", "fixture"] as const) ?? "live",
    created_at: str(raw.created_at),
    updated_at: str(raw.updated_at),
  };
}

/** A list endpoint may answer with a bare array or wrap it; accept the common wrappers. */
export function unwrapList(raw: unknown): unknown[] {
  if (Array.isArray(raw)) return raw;
  if (isObj(raw)) {
    for (const key of ["items", "data", "campaigns", "incidents", "results"]) {
      const v = raw[key];
      if (Array.isArray(v)) return v;
    }
  }
  return [];
}

/**
 * Resident-facing campaign card. `/v1/campaigns` has no contract yet (see DECISIONS.md),
 * so this accepts either a small campaign object or an Incident of type "campaign".
 */
export interface Campaign {
  id: string;
  title: { ar?: string; en?: string };
  advice?: { ar?: string; en?: string };
  severity: Severity;
  count: number;
  lastSeen: string | null;
  series: number[];
  source: DataSource;
}

export function parseCampaign(raw: unknown): Campaign | null {
  if (!isObj(raw)) return null;
  const id = optStr(raw.campaign_id) ?? optStr(raw.incident_id) ?? optStr(raw.id);
  if (!id) return null;
  const linked = strList(raw.linked_verdicts).length;
  const count = [raw.count, raw.linked_count, raw.checks].find((v): v is number => typeof v === "number") ?? linked;
  const series = Array.isArray(raw.series) ? raw.series.filter((v): v is number => typeof v === "number" && v >= 0).slice(-24) : [];
  return {
    id,
    title: optBilingual(raw.title) ?? optBilingual(raw.summary) ?? {},
    advice: optBilingual(raw.advice),
    severity: oneOf(raw.severity, SEVERITIES) ?? "low",
    count: Math.max(0, Math.round(count)),
    lastSeen: optStr(raw.last_seen) ?? optStr(raw.updated_at) ?? null,
    series,
    source: oneOf(raw.source, ["live", "replay", "synthetic", "fixture"] as const) ?? "live",
  };
}
