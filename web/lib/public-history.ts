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
import { arCount, CHECKS, DOMAINS } from "./ar-count";
import { BRAND_NAMES } from "./brand-names";
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

/** A W3C trace id is 32 hex characters and nothing else: safe to pass through (it only opens a trace for an operator who is logged in to Phoenix). */
const traceIdOf = (v: unknown): { trace_id?: string } => (typeof v === "string" && /^[0-9a-f]{32}$/.test(v) ? { trace_id: v } : {});
const VERDICT_ID = /^vd_[0-9A-HJKMNP-TV-Z]{26}$/;
const INCIDENT_ID = /^inc_[0-9A-HJKMNP-TV-Z]{26}$/;
const EVIDENCE_ID = /^ev_[0-9A-Za-z_]{1,64}$/;
const TIERS = ["T0", "T1", "T2", "T3"] as const;
const VERDICTS = ["dangerous", "suspicious", "no_warning_signs"] as const;
const INPUTS = ["url", "message", "email", "image"] as const;
const SOURCES = ["live", "replay", "synthetic", "fixture"] as const;
const ROUTES = ["cloud", "local", "none"] as const;
/** Which client asked (contracts/verdict.schema.json `channel`). A fixed enum: the only client information that is public. */
export const CHANNELS = ["web", "extension", "api", "mcp", "voice"] as const;
export type PublicChannel = (typeof CHANNELS)[number];
const SEVERITIES = ["low", "medium", "high", "critical"] as const;
const INCIDENT_STATUSES = ["open", "triaging", "awaiting_approval", "mitigated", "closed", "false_positive"] as const;
const ACTION_STATUSES = ["proposed", "executed", "awaiting_approval", "approved", "rejected", "reverted", "failed"] as const;
const NODES = ["enrich", "compare", "assess", "summarise", "propose", "act"] as const;
const RUN_STATUSES = ["running", "interrupted", "completed", "failed"] as const;
const MODES = ["read", "internal_auto", "external_draft"] as const;

/* ── Text scrubbing ───────────────────────────────────────────────────── */

const SCHEME_URL_RE = /[a-z][a-z0-9+.-]*:\/\/[^\s<>"'«»]*/giu;
const BARE_URL_RE = /(?<![\p{L}\p{N}@._%+-])(?:[\p{L}\p{N}-]+\[?\.\]?)+[\p{L}\p{N}-]+(?::\d{1,5})?(?:[/?#][^\s<>"'«»]*)?/gu;
const EMAIL_RE = /[\p{L}\p{N}._%+'-]+(?:@|\[at\]|\(at\))[\p{L}\p{N}-]+(?:\[?\.\]?[\p{L}\p{N}-]+)+/giu;
const PHONE_RE = /(?<![\p{L}\p{N}])(?:\+|00)?\(?\d[\d\s().-]{5,}\d(?![\p{L}\p{N}])/gu;
const LONG_DIGITS_RE = /\d{6,}/g;
const ARABIC_DIGITS = /[٠-٩۰-۹]/g;
const IPV4 = /^\d{1,3}(?:\.\d{1,3}){3}$/;
/** Anything that still looks like a query, fragment, userinfo or port-plus-path after scrubbing: fail closed. */
const RESIDUE_RE = /:\d{2,5}\//;
export const REMOVED_LINK = "[link removed]";
export const REMOVED_TEXT = "[text removed]";

/**
 * Reduces one link-like token to its defanged HOST: userinfo, port, path, query and fragment are dropped.
 * IPv4 and dotless hosts are kept as hosts; IPv6 or an unparseable authority returns null.
 */
function reduceLink(token: string): string | null {
  const m = /^(?:([a-z][a-z0-9+.-]*):\/\/)?([^/?#\s]*)/i.exec(token);
  if (!m) return null;
  let authority = m[2]!;
  authority = authority.slice(authority.lastIndexOf("@") + 1);
  if (authority.startsWith("[") && !/^[\p{L}\p{N}-]+\[\.\]/u.test(authority)) return null; // IPv6 literal
  const host = authority.replace(/:\d*$/, "").replace(/\[\.\]/g, ".").replace(/\.+$/, "").toLowerCase();
  if (!/^[\p{L}\p{N}][\p{L}\p{N}.-]{0,252}$/u.test(host)) return null;
  const scheme = m[1] ? (/^(?:https|hxxps)$/i.test(m[1]) ? "hxxps://" : "hxxp://") : "";
  return defang(`${scheme}${host}`);
}

/** A bare token (no scheme) is only a link when it has a path/query/port, is an IPv4, or ends in a letter TLD. */
function bareLink(token: string): string | null {
  const hasTail = /[/?#]/.test(token) || /:\d{1,5}(?:[/?#]|$)/.test(token);
  const host = /^[^/?#:]*/.exec(token)![0].replace(/\[\.\]/g, ".").toLowerCase();
  const tld = host.slice(host.lastIndexOf(".") + 1);
  const alphaTld = /^\p{L}{2,}$/u.test(tld) || /^xn--[a-z0-9-]+$/.test(tld);
  if (!hasTail && !IPV4.test(host) && !alphaTld) return null;
  if (!hasTail && !IPV4.test(host) && token === host && !host.includes(".")) return null;
  return reduceLink(token);
}

/** `hxxps://user:pw@a[.]b:8443/path?q=1#f` becomes `hxxps://a[.]b`; null when it is not a link. */
export function hostOf(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 4096) return null;
  const t = value.trim();
  if (!t || /\s/.test(t)) return null;
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(t) ? reduceLink(t) : bareLink(t);
}

export const REMOVED_TEXT_AR = "[أُزيل النص]";
export const REMOVED_NUMBER = "[number removed]";
/** Tokens our own passes emit; they are cut out before the allow-list test (idempotence). */
const OWN_TOKENS = /hxxps?:\/\/|\[\.\]|\[link removed\]|\[email\]|\[number removed\]|\[text removed\]|\[أُزيل النص\]/gu;
const FOUR_DIGITS_RE = /\d(?:[\s-]?\d){3,}/g;
const MIXED_LONG_RE = /(?=[\p{L}\p{N}]*\d)(?=[\p{L}\p{N}]*\p{L})[\p{L}\p{N}]{20,}/gu;
/** Allow-list for public free text: Arabic and Latin letters, Arabic diacritics and punctuation, digits, space and `. , : ; ! ? ( ) « » " ' - – —`. */
const ALLOWED_CHARS = /^(?:(?=\p{Script=Arabic})\p{L}|(?=\p{Script=Latin})\p{L}|[ً-ٰٟـ٠-٩،؛؟0-9 .,:;!?()«»"'–—-])*$/u;

/**
 * Removes links (host only is kept, defanged), emails and phone-like numbers from free text, then fails closed
 * (see the allow-list above): 4+ digit runs and long letter-digit tokens are removed, and any character outside
 * the allow-list replaces the WHOLE string with `generic`. Order matters:
 * links FIRST (so `user:pw@host:8443/p?x#f` never reaches the email pass), then emails, then numbers. Idempotent.
 * Fail closed: if anything shaped like a query, fragment, `@` or port-plus-path survives, the whole text is replaced.
 */
export function scrub(input: unknown, max = 400, generic = REMOVED_TEXT): string {
  if (typeof input !== "string") return "";
  let s = input.normalize("NFKC").replace(CONTROL, " ").replace(ARABIC_DIGITS, (d) => String("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹".indexOf(d) % 10));
  s = s.replace(SCHEME_URL_RE, (t) => reduceLink(t) ?? REMOVED_LINK);
  s = s.replace(BARE_URL_RE, (t) => bareLink(t) ?? t);
  s = s.replace(EMAIL_RE, "[email]");
  s = s.replace(MIXED_LONG_RE, REMOVED_NUMBER).replace(PHONE_RE, REMOVED_NUMBER).replace(FOUR_DIGITS_RE, REMOVED_NUMBER).replace(LONG_DIGITS_RE, REMOVED_NUMBER);
  s = s.replace(/\s+/g, " ").trim();
  const rest = s.replace(OWN_TOKENS, "");
  // Fail closed: any character outside the allow-list (or residue shaped like a query, fragment, userinfo or port) replaces the whole text.
  if (/(?:java|vb)script\s*:/i.test(rest) || RESIDUE_RE.test(rest) || !ALLOWED_CHARS.test(rest.normalize("NFKC"))) return generic;
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** `scrub` with the Arabic generic line. */
export const scrubAr = (input: unknown, max = 400): string => scrub(input, max, REMOVED_TEXT_AR);

const bilingual = (v: unknown, max = 400): { ar: string; en: string } => (isObj(v) ? { ar: scrubAr(v.ar, max), en: scrub(v.en, max) } : { ar: "", en: "" });

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
  channel: PublicChannel | null;
  trace_id?: string;
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
    channel: oneOf(raw.channel, CHANNELS),
    ...traceIdOf(raw.trace_id),
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
    display: { ar: scrubAr(d.ar, 240), en: scrub(d.en, 240) },
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
    impersonated_brand: brand && typeof brand.name_ar === "string" && typeof brand.name_en === "string" ? { brand_id: code(brand.brand_id) ?? "", name_ar: scrubAr(brand.name_ar, 80), name_en: scrub(brand.name_en, 80) } : null,
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
    ...(oneOf(raw.channel, CHANNELS) ? { channel: oneOf(raw.channel, CHANNELS) } : {}),
    ...traceIdOf(raw.trace_id),
    latency_ms: Math.round(num(raw.latency_ms, 0, 1e7)),
    created_at: iso(raw.created_at),
  };
}

/* ── Incidents (Sentinel) ─────────────────────────────────────────────── */

const INCIDENT_TYPES = ["campaign", "kit_reuse", "report_burst", "reputation_flip", "quality"] as const;

/**
 * Public incident title from STRUCTURED fields only: the type enum and the brand display name from the registry
 * (brand_id to {ar, en}). The free-text `summary` is never used. An unknown brand_id or type falls back to the
 * generic line, so no attacker-shaped text can reach the title.
 */
export function publicIncidentTitle(type: unknown, brandId: unknown): { ar: string; en: string } {
  const t = oneOf(type, INCIDENT_TYPES) ?? "campaign";
  const b = typeof brandId === "string" && Object.hasOwn(BRAND_NAMES, brandId) ? BRAND_NAMES[brandId]! : null;
  switch (t) {
    case "report_burst":
      return b ? { ar: `موجة بلاغات عن انتحال ${b.ar}`, en: `Burst of reports about impersonation of ${b.en}` } : { ar: "موجة بلاغات احتيال", en: "Burst of scam reports" };
    case "reputation_flip":
      return b ? { ar: `تغيّر في سمعة نطاق مرتبط بـ${b.ar}`, en: `Reputation change on a domain linked to ${b.en}` } : { ar: "تغيّر في سمعة نطاق مشتبه به", en: "Reputation change on a suspect domain" };
    case "quality":
      return { ar: "ملاحظة جودة على نتائج الفحص", en: "Check quality note" };
    default:
      return b ? { ar: `حملة احتيال تنتحل ${b.ar}`, en: `Suspected scam campaign impersonating ${b.en}` } : { ar: "حملة احتيال مشتبه بها", en: "Suspected scam campaign" };
  }
}

type Line = (n: number) => { ar: string; en: string };
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
/**
 * One fixed sentence per Sentinel rule, worded after the rule's real condition (services/sentinel/rules.yaml).
 * R1/R2 count distinct domains (what the rule counts). R3/R5 count reports and feedback, which the public
 * projection does not carry, so those lines have no number. A count of 0 is omitted.
 */
const RULE_LINES: Readonly<Record<string, Line>> = {
  R1: (d) => ({
    ar: d > 0 ? `رُصدت نطاقات جديدة تشبه علامة واحدة خلال ساعة (العدد: ${d}).` : "رُصدت نطاقات جديدة تشبه علامة واحدة خلال ساعة.",
    en: d > 0 ? `${plural(d, "new lookalike domain", "new lookalike domains")} for one brand within an hour.` : "New lookalike domains for one brand within an hour.",
  }),
  R2: (d) => ({
    ar: d > 0 ? `ظهر ${arCount(d, DOMAINS)} بالبصمة نفسها للصفحة خلال 7 أيام.` : "ظهرت نطاقات بالبصمة نفسها للصفحة خلال 7 أيام.",
    en: d > 0 ? `${plural(d, "domain", "domains")} with the same page fingerprint within 7 days.` : "Domains with the same page fingerprint within 7 days.",
  }),
  R3: () => ({ ar: "وردت عدة بلاغات متشابهة خلال 30 دقيقة.", en: "Several similar scam reports arrived within 30 minutes." }),
  R4: () => ({ ar: "نطاق لم تظهر عليه علامات تحذير سابقًا صار حكمه الآن «خطِر».", en: "A domain that earlier showed no warning signs now has a dangerous verdict." }),
  R5: () => ({ ar: "وردت عدة ملاحظات بأن الإشارة نفسها أعطت إنذارًا خاطئًا خلال ساعة.", en: "Several feedback reports say the same signal raised a false alarm within an hour." }),
};

/** Public severity line from the rule ids and counts only; free text is never used. Unknown rule: generic line. */
export function publicSeverityLine(ruleIds: readonly string[], linked: number, domains: number): { ar: string; en: string } {
  const rule = ruleIds.find((r) => Object.hasOwn(RULE_LINES, r));
  if (rule) return RULE_LINES[rule]!(domains);
  return linked > 0
    ? { ar: `ربط درع ${arCount(linked, CHECKS)} بهذه الحادثة.`, en: `Sentinel linked ${plural(linked, "check", "checks")} to this incident.` }
    : { ar: "سجّل درع هذه الحادثة.", en: "Sentinel recorded this incident." };
}

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
  return {
    incident_id: raw.incident_id,
    type: code(raw.type) ?? "",
    severity,
    severity_reason: publicSeverityLine(codes(raw.rule_ids, 12).filter((r) => Object.hasOwn(RULE_LINES, r)), Array.isArray(raw.linked_verdicts) ? raw.linked_verdicts.filter((v) => typeof v === "string" && VERDICT_ID.test(v)).slice(0, 50).length : 0, new Set(indicators.map((i) => i.value_defanged)).size),
    status,
    brand_id: code(raw.brand_id),
    rule_ids: codes(raw.rule_ids, 12),
    correlation_keys: {},
    indicators,
    linked_verdicts: (Array.isArray(raw.linked_verdicts) ? raw.linked_verdicts : []).filter((v): v is string => typeof v === "string" && VERDICT_ID.test(v)).slice(0, 50),
    // The free-text timeline is not public; the node timeline comes from the trace.
    timeline: [],
    // The free-text summary is never shown: the title comes from the structured type and brand only.
    summary: publicIncidentTitle(raw.type, raw.brand_id),
    actions,
    source: oneOf(raw.source, SOURCES) ?? "live",
    ...((Array.isArray(raw.channels) ? raw.channels : []).some((c) => oneOf(c, CHANNELS)) ? { channels: [...new Set((raw.channels as unknown[]).map((c) => oneOf(c, CHANNELS)).filter((c): c is PublicChannel => c !== null))].sort() } : {}),
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
        ...traceIdOf(r.trace_id),
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
