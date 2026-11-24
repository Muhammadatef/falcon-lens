/**
 * Server-side projections for the PUBLIC, read-only agent history (`/history`, `/checks/[id]`, `/incidents/[id]`).
 *
 * Owner decision 24 Nov: until SSO exists the history is open to anyone, read only. The browser never calls
 * `/v1/verdicts` or `/v1/incidents` itself; the Next.js route handlers under `app/api/public/{checks,incidents}`
 * call the API with the server-only read key and pass every payload through the ALLOW-LISTS below. Only the
 * fields written out here survive, so anything the API adds later (raw input, headers, recipients, draft bodies,
 * approvers, observed values) never reaches a visitor. Free text that the model or the checked input could have
 * shaped is passed through `scrub`, which removes URLs (keeping only a defanged host), email addresses and
 * phone-like numbers.
 *
 * The output keeps the contract shapes (verdict, incident, agent trace) with the private parts emptied, so the
 * existing guards (`parseVerdict`, `parseIncident`, `parseAgentTrace`) and components work unchanged.
 */
import { defang } from "./defang";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): T | null => (typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null);
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f‎‏‪-‮⁦-⁩]/g;
const num = (v: unknown, min = 0, max = 1e9): number => (typeof v === "number" && Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : 0);
const CODE_RE = /^[A-Za-z0-9][\w.:-]{0,63}$/;
const code = (v: unknown): string | null => (typeof v === "string" && CODE_RE.test(v) ? v : null);
const codes = (v: unknown, max = 8): string[] => (Array.isArray(v) ? v.map(code).filter((c): c is string => c !== null).slice(0, max) : []);
const iso = (v: unknown): string => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:?\d{2})?$/.test(v) ? v : "");

const VERDICT_ID = /^vd_[0-9A-HJKMNP-TV-Z]{26}$/;
const INCIDENT_ID = /^inc_[0-9A-HJKMNP-TV-Z]{26}$/;
const EVIDENCE_ID = /^ev_[0-9A-Za-z_]{1,64}$/;
const TIERS = ["T0", "T1", "T2", "T3"] as const;
const VERDICTS = ["dangerous", "suspicious", "no_warning_signs"] as const;
const INPUTS = ["url", "message", "email", "image"] as const;
const SOURCES = ["live", "replay", "synthetic", "fixture"] as const;
const ROUTES = ["cloud", "local", "none"] as const;
const SEVERITIES = ["low", "medium", "high", "critical"] as const;
const INCIDENT_STATUSES = ["open", "triaging", "awaiting_approval", "mitigated", "closed", "false_positive"] as const;
const ACTION_STATUSES = ["proposed", "executed", "awaiting_approval", "approved", "rejected", "reverted", "failed"] as const;
const NODES = ["enrich", "compare", "assess", "summarise", "propose", "act"] as const;
const RUN_STATUSES = ["running", "interrupted", "completed", "failed"] as const;
const MODES = ["read", "internal_auto", "external_draft"] as const;

/* ── Text scrubbing ───────────────────────────────────────────────────── */

const EMAIL_RE = /[\p{L}\p{N}._%+'-]+(?:@|\[at\]|\(at\))[\p{L}\p{N}-]+(?:\[?\.\]?[\p{L}\p{N}-]+)+/giu;
const URLISH_RE = /(?:[a-z][a-z0-9+.-]*:\/\/)?(?:[^\s/@]+@)?[\p{L}\p{N}-]+(?:\[?\.\]?[\p{L}\p{N}-]+)+(?::\d{1,5})?(?:[/?#][^\s]*)?/giu;
const PHONE_RE = /(?<![\p{L}\p{N}])\+?\(?\d[\d\s().-]{5,}\d(?![\p{L}\p{N}])/gu;
const LONG_DIGITS_RE = /\d{6,}/g;
const ARABIC_DIGITS = /[٠-٩۰-۹]/g;

/** Host (and nothing else) of a link-like token, defanged; null when the token is not a link (v1.2, e.g.). */
function hostToken(token: string): string | null {
  const m = /^((?:[a-z][a-z0-9+.-]*):\/\/)?(?:[^\s/@]+@)?([\p{L}\p{N}-]+(?:\[?\.\]?[\p{L}\p{N}-]+)+)/iu.exec(token);
  if (!m) return null;
  const host = m[2]!.replace(/\[\.\]/g, ".").toLowerCase();
  const tld = host.slice(host.lastIndexOf(".") + 1);
  if (!/^\p{L}{2,}$/u.test(tld) && !/^xn--[a-z0-9-]+$/.test(tld)) return null;
  const secure = /^(?:https|hxxps):/i.test(m[1] ?? "");
  const scheme = m[1] ? (secure ? "hxxps://" : "hxxp://") : "";
  return defang(`${scheme}${host}`);
}

/** Removes emails, phone-like numbers and everything after the host of any link. Idempotent. */
export function scrub(input: unknown, max = 400): string {
  if (typeof input !== "string") return "";
  let s = input.replace(CONTROL, " ").replace(ARABIC_DIGITS, (d) => String("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹".indexOf(d) % 10));
  s = s.replace(EMAIL_RE, "[email]");
  s = s.replace(URLISH_RE, (token) => hostToken(token) ?? token);
  s = s.replace(PHONE_RE, "[number]").replace(LONG_DIGITS_RE, "[number]");
  s = s.replace(/\s+/g, " ").trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

const bilingual = (v: unknown, max = 400): { ar: string; en: string } => (isObj(v) ? { ar: scrub(v.ar, max), en: scrub(v.en, max) } : { ar: "", en: "" });

/** `hxxps://user:pw@a[.]b/path?q=1` becomes `hxxps://a[.]b`; null when it is not a link. */
export function hostOf(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 4096) return null;
  return hostToken(value.trim());
}

/* ── Checks (Investigator) ────────────────────────────────────────────── */

export interface PublicCheckSummary {
  verdict_id: string;
  created_at: string;
  input_type: (typeof INPUTS)[number];
  /** Defanged host for links; null for messages, emails and images. */
  display: string | null;
  verdict: (typeof VERDICTS)[number];
  risk_score: number;
  degraded: boolean;
  degraded_reasons: string[];
  tier_reached: (typeof TIERS)[number];
  model_route: (typeof ROUTES)[number];
  source: (typeof SOURCES)[number];
  agent: { tiers_run: (typeof TIERS)[number][]; extractor_ran: boolean; investigator_ran: boolean; tool_calls: number; llm_calls: number };
}

const count = (v: unknown) => Math.round(num(v, 0, 9999));

/** Exactly the redacted summary the API returns for `/v1/verdicts`, re-checked field by field. */
export function toPublicCheckSummary(raw: unknown): PublicCheckSummary | null {
  if (!isObj(raw)) return null;
  const verdict = oneOf(raw.verdict, VERDICTS);
  const tier = oneOf(raw.tier_reached, TIERS);
  const inputType = oneOf(raw.input_type, INPUTS);
  if (typeof raw.verdict_id !== "string" || !VERDICT_ID.test(raw.verdict_id) || !verdict || !tier || !inputType) return null;
  const a = isObj(raw.agent) ? raw.agent : {};
  const tiers = (Array.isArray(a.tiers_run) ? a.tiers_run : []).map((t) => oneOf(t, TIERS)).filter((t): t is (typeof TIERS)[number] => t !== null);
  const degraded = raw.degraded === true;
  return {
    verdict_id: raw.verdict_id,
    created_at: iso(raw.created_at),
    input_type: inputType,
    // Only a defanged host, and only for links: nothing at all for messages, emails and images.
    display: inputType === "url" ? hostOf(raw.display) : null,
    verdict: verdict === "no_warning_signs" && degraded ? "suspicious" : verdict,
    risk_score: Math.round(num(raw.risk_score, 0, 100)),
    degraded,
    degraded_reasons: codes(raw.degraded_reasons),
    tier_reached: tier,
    model_route: oneOf(raw.model_route, ROUTES) ?? "none",
    source: oneOf(raw.source, SOURCES) ?? "live",
    agent: {
      tiers_run: tiers.length ? tiers : TIERS.slice(0, TIERS.indexOf(tier) + 1),
      extractor_ran: a.extractor_ran === true,
      investigator_ran: a.investigator_ran === true,
      tool_calls: count(a.tool_calls),
      llm_calls: count(a.llm_calls),
    },
  };
}

export function toPublicCheckPage(raw: unknown): { items: PublicCheckSummary[]; next_cursor: string | null } {
  const list = isObj(raw) && Array.isArray(raw.items) ? raw.items : Array.isArray(raw) ? raw : [];
  const cursor = isObj(raw) && typeof raw.next_cursor === "string" && /^\d{1,20}-\d{1,20}$/.test(raw.next_cursor) ? raw.next_cursor : null;
  return { items: list.map(toPublicCheckSummary).filter((c): c is PublicCheckSummary => c !== null).slice(0, 100), next_cursor: cursor };
}

function publicEvidence(raw: unknown): Obj | null {
  if (!isObj(raw)) return null;
  const tier = oneOf(raw.tier, TIERS);
  if (typeof raw.id !== "string" || !EVIDENCE_ID.test(raw.id) || !tier) return null;
  const d = isObj(raw.display) ? raw.display : {};
  return {
    id: raw.id,
    signal: code(raw.signal) ?? "",
    family: code(raw.family) ?? "",
    // `observed` can hold the user's own input (a quoted phrase, a number, a URL): never exposed.
    observed: null,
    display: { ar: scrub(d.ar, 240), en: scrub(d.en, 240) },
    weight: num(raw.weight, -100, 100),
    polarity: oneOf(raw.polarity, ["risk", "trust", "neutral"] as const) ?? "neutral",
    hard_rule: code(raw.hard_rule),
    source: typeof raw.source === "string" && /^[a-z0-9_.:-]{1,64}$/i.test(raw.source) ? raw.source : "",
    tier,
    ...(typeof raw.confidence === "number" && Number.isFinite(raw.confidence) ? { confidence: num(raw.confidence, 0, 1) } : {}),
    ...(typeof raw.latency_ms === "number" ? { latency_ms: Math.round(num(raw.latency_ms, 0, 1e7)) } : {}),
    error: raw.error ? (code(raw.error) ?? "error") : null,
  };
}

/** A verdict document for the public trace page: verdict, score, tiers, evidence codes and texts, reasons, tool names and latency. */
export function toPublicCheck(raw: unknown): Obj | null {
  if (!isObj(raw)) return null;
  const verdict = oneOf(raw.verdict, VERDICTS);
  const tier = oneOf(raw.tier_reached, TIERS);
  const inputType = oneOf(raw.input_type, INPUTS);
  if (typeof raw.verdict_id !== "string" || !VERDICT_ID.test(raw.verdict_id) || !verdict || !tier || !inputType || typeof raw.final !== "boolean") return null;
  const evidence = (Array.isArray(raw.evidence) ? raw.evidence : []).map(publicEvidence).filter((e): e is Obj => e !== null).slice(0, 80);
  const ids = new Set(evidence.map((e) => e.id as string));
  const reasons = (Array.isArray(raw.reasons) ? raw.reasons : [])
    .filter(isObj)
    .slice(0, 3)
    .map((r) => ({
      ...bilingual(r, 320),
      evidence_ids: (Array.isArray(r.evidence_ids) ? r.evidence_ids : []).filter((id): id is string => typeof id === "string" && ids.has(id)).slice(0, 12),
    }));
  const degraded = raw.degraded === true;
  const brand = isObj(raw.impersonated_brand) ? raw.impersonated_brand : null;
  const trace = (Array.isArray(raw.trace) ? raw.trace : [])
    .filter(isObj)
    .map((s, i) => ({ step: Math.round(num(s.step, 0, 9999)) || i, kind: oneOf(s.kind, ["tier", "tool", "llm", "rule"] as const), name: code(s.name) ?? undefined, ms: typeof s.ms === "number" ? Math.round(num(s.ms, 0, 1e7)) : undefined }))
    .filter((s) => s.kind !== null)
    .slice(0, 60)
    // Step summaries are free text that may quote the input: only the kind, the tool name and the latency are public.
    .map((s) => ({ ...s, summary: "" }));
  return {
    schema_version: "1.0",
    verdict_id: raw.verdict_id,
    input_type: inputType,
    // Host only; never the full URL, path, query or userinfo.
    canonical_url: inputType === "url" ? hostOf(raw.canonical_url) : null,
    verdict: verdict === "no_warning_signs" && degraded ? "suspicious" : verdict,
    risk_score: Math.round(num(raw.risk_score, 0, 100)),
    calibrated_probability: num(raw.calibrated_probability, 0, 1),
    impersonated_brand: brand && typeof brand.name_ar === "string" && typeof brand.name_en === "string" ? { brand_id: code(brand.brand_id) ?? "", name_ar: scrub(brand.name_ar, 80), name_en: scrub(brand.name_en, 80) } : null,
    evidence,
    reasons,
    actions: { now: { ar: [], en: [] }, if_already_acted: { ar: [], en: [] }, report: { ar: "", en: "" } },
    tier_reached: tier,
    model_route: oneOf(raw.model_route, ROUTES) ?? "none",
    degraded,
    degraded_reasons: codes(raw.degraded_reasons),
    final: raw.final,
    trace,
    source: oneOf(raw.source, SOURCES) ?? "live",
    latency_ms: Math.round(num(raw.latency_ms, 0, 1e7)),
    created_at: iso(raw.created_at),
  };
}

/* ── Incidents (Sentinel) ─────────────────────────────────────────────── */

const INDICATOR_KINDS = new Set(["domain", "url", "host"]);

/** Incident for the public board and trace header: titles, severity, counts, defanged domains, action TYPES and status only. */
export function toPublicIncident(raw: unknown): Obj | null {
  if (!isObj(raw)) return null;
  const severity = oneOf(raw.severity, SEVERITIES);
  const status = oneOf(raw.status, INCIDENT_STATUSES);
  if (typeof raw.incident_id !== "string" || !INCIDENT_ID.test(raw.incident_id) || !severity || !status) return null;
  const indicators = (Array.isArray(raw.indicators) ? raw.indicators : [])
    .filter(isObj)
    .filter((i) => typeof i.kind === "string" && INDICATOR_KINDS.has(i.kind))
    .map((i) => ({ kind: "domain", value_defanged: hostOf(i.value_defanged), first_seen: iso(i.first_seen) }))
    .filter((i): i is { kind: string; value_defanged: string; first_seen: string } => i.value_defanged !== null)
    .slice(0, 8);
  const actions = (Array.isArray(raw.actions) ? raw.actions : [])
    .filter(isObj)
    .map((a) => ({
      action_id: typeof a.action_id === "string" && /^act_[0-9A-Za-z_-]{1,64}$/.test(a.action_id) ? a.action_id : "",
      tool: code(a.tool) ?? "",
      mode: a.mode === "external_draft" ? "external_draft" : "internal_auto",
      status: oneOf(a.status, ACTION_STATUSES),
      // Draft bodies, subjects, recipients, approver names and decision times are operator-only.
      draft: null,
      evidence_ids: [] as string[],
      approved_by: null,
    }))
    .filter((a) => a.action_id && a.tool && a.status !== null)
    .slice(0, 20);
  const summary = isObj(raw.summary) ? raw.summary : {};
  const reason = isObj(raw.severity_reason) ? raw.severity_reason : {};
  return {
    incident_id: raw.incident_id,
    type: code(raw.type) ?? "",
    severity,
    severity_reason: { ar: scrub(reason.ar, 300), en: scrub(reason.en, 300) },
    status,
    brand_id: code(raw.brand_id),
    rule_ids: codes(raw.rule_ids, 12),
    correlation_keys: {},
    indicators,
    linked_verdicts: (Array.isArray(raw.linked_verdicts) ? raw.linked_verdicts : []).filter((v): v is string => typeof v === "string" && VERDICT_ID.test(v)).slice(0, 50),
    // The free-text timeline is not public; the node timeline comes from the trace.
    timeline: [],
    summary: { ar: scrub(summary.ar, 240), en: scrub(summary.en, 240) },
    actions,
    source: oneOf(raw.source, SOURCES) ?? "live",
    created_at: iso(raw.created_at),
    updated_at: iso(raw.updated_at),
  };
}

export function toPublicIncidentPage(raw: unknown): { items: Obj[]; next_cursor: string | null } {
  const list = isObj(raw) && Array.isArray(raw.items) ? raw.items : Array.isArray(raw) ? raw : [];
  const cursor = isObj(raw) && typeof raw.next_cursor === "string" && /^[\w=-]{1,200}$/.test(raw.next_cursor) ? raw.next_cursor : null;
  return { items: list.map(toPublicIncident).filter((i): i is Obj => i !== null).slice(0, 100), next_cursor: cursor };
}

/** Sentinel run trace: node names, timestamps, durations, tool names and counts. Step summaries are free text and are dropped. */
export function toPublicTrace(raw: unknown): Obj | null {
  if (!isObj(raw) || typeof raw.incident_id !== "string" || !INCIDENT_ID.test(raw.incident_id)) return null;
  const runs = (Array.isArray(raw.runs) ? raw.runs : [])
    .filter(isObj)
    .slice(0, 20)
    .map((r) => {
      const intr = isObj(r.interrupt) ? r.interrupt : null;
      return {
        run_id: typeof r.run_id === "string" && /^[\w.:-]{1,80}$/.test(r.run_id) ? r.run_id : "run",
        started_at: iso(r.started_at),
        finished_at: iso(r.finished_at) || null,
        status: oneOf(r.status, RUN_STATUSES) ?? "completed",
        steps: (Array.isArray(r.steps) ? r.steps : []).filter(isObj).slice(0, 60).map(publicStep).filter((s): s is Obj => s !== null),
        interrupt: intr
          ? {
              action_id: typeof intr.action_id === "string" && /^[\w.:-]{1,80}$/.test(intr.action_id) ? intr.action_id : "",
              tool: code(intr.tool) ?? "",
              waiting_since: iso(intr.waiting_since),
              ...(typeof intr.pending_count === "number" ? { pending_count: Math.max(1, Math.round(num(intr.pending_count, 1, 99))) } : {}),
            }
          : null,
      };
    });
  return { incident_id: raw.incident_id, thread_id: raw.incident_id, runs };
}

function publicStep(s: Obj): Obj | null {
  const node = oneOf(s.node, NODES);
  if (!node) return null;
  const tools = (Array.isArray(s.tools) ? s.tools : [])
    .filter(isObj)
    .slice(0, 12)
    .map((t) => ({ name: code(t.name), mode: oneOf(t.mode, MODES), status: t.status === "error" ? "error" : "ok", evidence_ids: [] as string[], duration_ms: Math.round(num(t.duration_ms, 0, 1e7)), ...(t.origin === "rule_fallback" || t.origin === "model" ? { origin: t.origin } : {}) }))
    .filter((t) => t.name !== null && t.mode !== null);
  const llm = isObj(s.llm) ? s.llm : null;
  const b = isObj(s.budget) ? s.budget : {};
  return {
    seq: Math.round(num(s.seq, 0, 1e6)),
    node,
    started_at: iso(s.started_at),
    duration_ms: Math.round(num(s.duration_ms, 0, 1e7)),
    status: oneOf(s.status, RUN_STATUSES) ?? "completed",
    summary_en: "",
    summary_ar: "",
    tools,
    llm: llm ? { route: oneOf(llm.route, ROUTES) ?? "none", model: code(llm.model) ?? "", tokens_in: count(llm.tokens_in), tokens_out: count(llm.tokens_out), cost_usd: num(llm.cost_usd, 0, 1e4), repaired: llm.repaired === true, fallback_template: llm.fallback_template === true } : null,
    generated_by: oneOf(s.generated_by, ["llm", "template", "rule"] as const),
    budget: { steps_used: count(b.steps_used), tokens_used: Math.round(num(b.tokens_used, 0, 1e9)), elapsed_ms: Math.round(num(b.elapsed_ms, 0, 1e9)) },
    error_code: code(s.error_code),
  };
}

/* ── SSE frames ───────────────────────────────────────────────────────── */

/** Re-frames one upstream SSE block through `project`; `event` is the only event name that passes. */
export function filterFrameWith(block: string, event: string, project: (raw: unknown) => unknown): string | null {
  let name = "message";
  const data: string[] = [];
  let id: string | null = null;
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    else if (line.startsWith("id:")) id = line.slice(3).trim().replace(/[^\w.-]/g, "").slice(0, 64);
  }
  if (data.length === 0 || (name !== event && name !== "message")) return null;
  try {
    const out = project(JSON.parse(data.join("\n")));
    if (!out) return null;
    return `${id ? `id: ${id}\n` : ""}event: ${event}\ndata: ${JSON.stringify(out)}\n\n`;
  } catch {
    return null;
  }
}
