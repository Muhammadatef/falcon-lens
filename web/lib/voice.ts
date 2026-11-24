/**
 * Pure logic for the hands-free voice assistant (/voice): the /api/voice contract, the clipboard
 * splitter, the spoken-summary builder and the "what to do now" pick. No DOM, no network, so it is unit-tested.
 *
 * Product rules honoured here: never the word "safe"; the lowest verdict is "no warning signs" plus a caution;
 * nothing asks for personal, banking or ID details. All spoken and shown strings come from lib/i18n-voice.ts.
 */
import type { Lang, Verdict, VerdictLabel } from "./contracts";
import { looksLikeSingleUrl, refang } from "./defang";
import { pick } from "./i18n";
import { voiceText, type VoiceKey } from "./i18n-voice";
import { FAQ_KEYS } from "./voice-script";
/** Set to true only once the backend PR confirms: audio recognised by a local model on our own server and deleted. */
export const PRIVACY_LINE_CONFIRMED = false;

/** End-of-speech silence in ms: 800 by default; set NEXT_PUBLIC_FL_VAD_SILENCE_MS (400-1500) to try 650 (see vad_silence_*.json). */
export function vadSilenceMs(raw: string | undefined): number {
  const n = Number.parseInt(raw ?? "", 10);
  return Number.isFinite(n) && n >= 400 && n <= 1500 ? n : 800;
}

export const VOICE_LIMITS = { maxBytes: 1_000_000, maxMs: 12_000, minMs: 400, silenceMs: vadSilenceMs(process.env.NEXT_PUBLIC_FL_VAD_SILENCE_MS), maxItems: 10, maxItemChars: 3500 } as const;

export type VoiceIntent = "check_clipboard" | "check_text" | "help" | "stop" | "faq" | "off_topic" | "none";
export interface VoiceReply {
  transcript: string;
  lang: "ar" | "en" | "other";
  wake: boolean;
  intent: VoiceIntent;
  command: string;
  /** Clip key of the pre-written FAQ answer (`faq.<name>`), only for intent "faq" and only if the script has it. */
  answerId: string | null;
  duration_ms: number;
  model: string;
}

const INTENTS: readonly VoiceIntent[] = ["check_clipboard", "check_text", "help", "stop", "faq", "off_topic", "none"];

/** Everything from the network is validated: unknown intents collapse to "none", text is capped. */
export function parseVoiceReply(raw: unknown): VoiceReply | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.wake !== "boolean") return null;
  let intent = INTENTS.find((i) => i === r.intent) ?? "none";
  // An answer id is only trusted when the script has that exact line: anything else is a redirect, never invented speech.
  const answerId = typeof r.answer_id === "string" && FAQ_KEYS.includes(r.answer_id) ? r.answer_id : null;
  if (intent === "faq" && !answerId) intent = "off_topic";
  const lang = r.lang === "ar" || r.lang === "en" ? r.lang : "other";
  const str = (v: unknown, max: number) => (typeof v === "string" ? v.slice(0, max) : "");
  return {
    transcript: str(r.transcript, 1000),
    lang,
    wake: r.wake,
    intent,
    command: str(r.command, 1000),
    answerId: intent === "faq" ? answerId : null,
    duration_ms: typeof r.duration_ms === "number" && Number.isFinite(r.duration_ms) ? r.duration_ms : 0,
    model: str(r.model, 80),
  };
}

/* ── Clipboard splitter ───────────────────────────────────────────────── */

export interface ClipItem {
  /** `url` when the item is only a link (refanged for submission); otherwise a message. */
  kind: "url" | "message";
  text: string;
}
export interface Split {
  items: ClipItem[];
  /** True when more than the cap were found and the rest were dropped. */
  truncated: boolean;
}

const MARKER = /^\s*(?:[0-9٠-٩]{1,2}\s*[.)\]:\-–]|[-•*▪●◦·])\s+/u;
const HAS_URL = /(?:https?:\/\/|hxxps?:\/\/|\bwww\.)\S+|\b[\p{L}\p{N}-]+(?:\[?\.\]?[\p{L}\p{N}-]+)*\.(?:com|net|org|ae|co|info|xyz|top|click|link|online|site|me|app|shop|vip|help|support)\b\S*/iu;

// eslint-disable-next-line no-control-regex
const clean = (s: string): string => s.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "").trim();

function splitByMarkers(block: string): string[] {
  const lines = block.split("\n");
  if (lines.filter((l) => MARKER.test(l)).length < 2) return [block];
  const out: string[] = [];
  for (const line of lines) {
    if (MARKER.test(line) || out.length === 0) out.push(line.replace(MARKER, ""));
    else out[out.length - 1] += `\n${line}`;
  }
  return out;
}

/** No blank lines and no markers: each URL-bearing line closes one message (a text line before a link belongs to it). */
function splitByUrlLines(block: string): string[] {
  const lines = block.split("\n").filter((l) => l.trim());
  if (lines.filter((l) => HAS_URL.test(l)).length < 2) return [block];
  const out: string[] = [];
  let buf: string[] = [];
  for (const line of lines) {
    buf.push(line);
    if (HAS_URL.test(line)) {
      out.push(buf.join("\n"));
      buf = [];
    }
  }
  if (buf.length) out.push(buf.join("\n"));
  return out;
}

export function splitMessages(raw: string): Split {
  const text = raw.replace(/\r\n?/g, "\n").trim();
  if (!text) return { items: [], truncated: false };
  const blocks = text.split(/\n[ \t]*\n+/).map((b) => b.trim()).filter(Boolean);
  let parts = blocks.flatMap(splitByMarkers);
  if (blocks.length === 1 && parts.length === 1) parts = splitByUrlLines(blocks[0]!);
  const seen = new Set<string>();
  const items: ClipItem[] = [];
  for (const part of parts) {
    const body = clean(part).replace(/[ \t]+/g, " ").slice(0, VOICE_LIMITS.maxItemChars);
    if (body.length < 3) continue;
    const key = body.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    items.push(looksLikeSingleUrl(body) ? { kind: "url", text: refang(body) } : { kind: "message", text: body });
  }
  return { items: items.slice(0, VOICE_LIMITS.maxItems), truncated: items.length > VOICE_LIMITS.maxItems };
}

/* ── Results and the spoken summary ───────────────────────────────────── */

export interface Outcome {
  id: string | null;
  /** null when the check could not be completed. */
  verdict: Verdict | null;
}

export interface Counts {
  total: number;
  dangerous: number;
  suspicious: number;
  clear: number;
  failed: number;
}

export function countOutcomes(outcomes: readonly Outcome[]): Counts {
  const c: Counts = { total: outcomes.length, dangerous: 0, suspicious: 0, clear: 0, failed: 0 };
  for (const o of outcomes) {
    const v: VerdictLabel | undefined = o.verdict?.verdict;
    if (v === "dangerous") c.dangerous += 1;
    else if (v === "suspicious") c.suspicious += 1;
    else if (v === "no_warning_signs") c.clear += 1;
    else c.failed += 1;
  }
  return c;
}

const AR_FEM = ["", "واحدة", "اثنتان", "ثلاث", "أربع", "خمس", "ست", "سبع", "ثمانٍ", "تسع", "عشر"];
const AR_FEM_OBL = ["", "واحدة", "اثنتين", "ثلاث", "أربع", "خمس", "ست", "سبع", "ثماني", "تسع", "عشر"];
const EN_NUM = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "ثلاث رسائل", "رسالتين", "three messages": numbers are spoken as words, never as digits. */
function totalPhrase(lang: Lang, n: number): string {
  if (lang === "ar") return n === 1 ? "رسالة واحدة" : n === 2 ? "رسالتين" : `${AR_FEM_OBL[n] ?? n} رسائل`;
  return n === 1 ? "one message" : `${EN_NUM[n] ?? n} messages`;
}

const countWord = (lang: Lang, n: number): string => (lang === "ar" ? (AR_FEM[n] ?? String(n)) : cap(EN_NUM[n] ?? String(n)));

const vt = (lang: Lang, key: VoiceKey, vars?: Record<string, string>) => voiceText(lang, key, vars);

/** The short spoken summary (the "what to do now" line is read after it). Never says "safe". */
export function buildSummary(lang: Lang, c: Counts): string {
  if (c.total === 0) return vt(lang, "voice.sum.none");
  const parts: string[] = [vt(lang, "voice.sum.checked", { total: totalPhrase(lang, c.total) })];
  if (c.total === 1) {
    if (c.dangerous) parts.push(vt(lang, "voice.sum.one.dangerous"));
    else if (c.suspicious) parts.push(vt(lang, "voice.sum.one.suspicious"));
    else if (c.clear) parts.push(vt(lang, "voice.sum.one.clear"));
    else parts.push(vt(lang, "voice.sum.failed.one"));
    return parts.join(" ");
  }
  if (c.dangerous) parts.push(vt(lang, c.dangerous === 1 ? "voice.sum.d.one" : "voice.sum.d.many", { n: countWord(lang, c.dangerous) }));
  if (c.suspicious) parts.push(vt(lang, c.suspicious === 1 ? "voice.sum.s.one" : "voice.sum.s.many", { n: countWord(lang, c.suspicious) }));
  if (c.clear) parts.push(vt(lang, c.clear === 1 ? "voice.sum.c.one" : "voice.sum.c.many", { n: countWord(lang, c.clear) }));
  if (c.failed) parts.push(vt(lang, c.failed === 1 ? "voice.sum.f.one" : "voice.sum.f.many", { n: countWord(lang, c.failed) }));
  return parts.join(" ");
}

const SEVERITY: Record<VerdictLabel, number> = { dangerous: 3, suspicious: 2, no_warning_signs: 1 };

/** The first "do this now" line of the most severe verdict, in the reader's language; "" when there is none. */
export function topAction(lang: Lang, outcomes: readonly Outcome[]): string {
  let best: Verdict | null = null;
  for (const o of outcomes) if (o.verdict && SEVERITY[o.verdict.verdict] > (best ? SEVERITY[best.verdict] : 0)) best = o.verdict;
  if (!best) return "";
  const now = best.actions.now;
  const [first, other] = lang === "ar" ? [now.ar, now.en] : [now.en, now.ar];
  return (first[0] ?? other[0] ?? "").trim();
}

/** The full utterance: summary, then the single most important next step. */
export function buildSpeech(lang: Lang, outcomes: readonly Outcome[], agents?: { sentinelFound: boolean }): string {
  const base = buildSummary(lang, countOutcomes(outcomes));
  const summary = agents && outcomes.length ? `${base} ${vt(lang, "voice.sum.inv")} ${vt(lang, agents.sentinelFound ? "voice.sum.sen.found" : "sentinel.watching")}` : base;
  const action = topAction(lang, outcomes);
  return action ? `${summary} ${vt(lang, "voice.sum.now")} ${action}` : summary;
}

/** The top reason line for a card (first reason, reader's language). */
export const topReason = (lang: Lang, v: Verdict): string => pick(lang, v.reasons[0]);

/**
 * "The Sentinel is linking these into a campaign" is shown only when the data says so:
 * at least two dangerous verdicts name the same impersonated brand.
 */
export function sharedBrandCampaign(outcomes: readonly Outcome[]): boolean {
  const byBrand = new Map<string, number>();
  for (const o of outcomes) {
    const v = o.verdict;
    if (v?.verdict !== "dangerous" || !v.impersonated_brand?.brand_id) continue;
    byBrand.set(v.impersonated_brand.brand_id, (byBrand.get(v.impersonated_brand.brand_id) ?? 0) + 1);
  }
  return [...byBrand.values()].some((n) => n >= 2);
}

/** Picks the speaking language from the API's detected language, falling back to the page language. */
export const speechLang = (detected: VoiceReply["lang"], page: Lang): Lang => (detected === "ar" || detected === "en" ? detected : page);

/* ── Live steps and narration ─────────────────────────────────────────── */

const AR_ORD = ["", "الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة", "السادسة", "السابعة", "الثامنة", "التاسعة", "العاشرة"];
const EN_ORD = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"];
const ordinal = (lang: Lang, n: number): string => (lang === "ar" ? AR_ORD[n] : EN_ORD[n]) ?? String(n);

/** "three messages" / «ثلاث رسائل»: the number of items as words, for speech and the first step. */
export const totalWords = (lang: Lang, n: number): string => totalPhrase(lang, n);

export type ProgressStep = "lists" | "lookalike" | "wording" | "browser" | "ai";
const RANK = { T0: 0, T1: 1, T2: 2, T3: 3 } as const;

/**
 * Plain-language steps that a progressive verdict snapshot proves have happened. A step appears only when its
 * tier produced evidence (or, for the AI second look, an LLM trace step), so nothing is narrated that did not run.
 */
export function newProgressSteps(v: Verdict, kind: "url" | "message", seen: Set<ProgressStep>): ProgressStep[] {
  const reached = RANK[v.tier_reached];
  const tiers = new Set(v.evidence.map((e) => e.tier));
  const ran = (t: keyof typeof RANK) => reached >= RANK[t] && (t === "T0" || tiers.has(t) || (t === "T3" && (v.trace ?? []).some((s) => s.kind === "llm")));
  const wanted: ProgressStep[] = [];
  if (ran("T0")) wanted.push("lists");
  if (ran("T1")) wanted.push(kind === "url" ? "lookalike" : "wording");
  if (kind === "url" && ran("T2")) wanted.push("browser");
  if (ran("T3")) wanted.push("ai");
  const fresh = wanted.filter((s) => !seen.has(s));
  fresh.forEach((s) => seen.add(s));
  return fresh;
}

export const stepKey = (s: ProgressStep): VoiceKey =>
  s === "lists" ? "investigator.lists" : s === "lookalike" ? "investigator.address" : s === "browser" ? "investigator.page" : s === "wording" ? "voice.step.wording" : "investigator.ai_second_look";

export const narStart = (lang: Lang, total: number): string => vt(lang, "voice.nar.start", { total: totalPhrase(lang, total) });
export const narMessage = (lang: Lang, i: number): string => vt(lang, "investigator.start", { ord: ordinal(lang, i) });
export const narResult = (lang: Lang, i: number, v: Verdict | null): string =>
  v ? vt(lang, `investigator.nar.${v.verdict}` as VoiceKey, { ord: ordinal(lang, i) }) : vt(lang, "voice.nar.res.failed", { ord: ordinal(lang, i) });

/** The AI second look is named only when a model actually answered; the route says where. */
export function aiStepText(lang: Lang, v: Verdict): string | null {
  if (v.model_route === "none") return null;
  return vt(lang, "investigator.ai_second_look", { route: vt(lang, v.model_route === "local" ? "investigator.route.local" : "investigator.route.cloud") });
}

/* ── Sentinel hand-over ───────────────────────────────────────────────── */

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

export interface SentinelIncident {
  id: string;
  severity: "low" | "medium" | "high" | "critical";
  linked: number;
  summary: { ar?: string; en?: string };
  /** The incident holds an external takedown draft (from its action types). */
  drafted: boolean;
  /** That draft is awaiting an officer's approval (from the action status). */
  awaiting: boolean;
}

/** The first public incident whose linked verdict ids include any of ours; null when none does. Opaque ids only. */
export function findIncident(list: unknown, verdictIds: readonly string[]): SentinelIncident | null {
  const items = isObj(list) && Array.isArray(list.items) ? list.items : [];
  const mine = new Set(verdictIds);
  for (const raw of items) {
    if (!isObj(raw) || typeof raw.incident_id !== "string" || !/^inc_[0-9A-HJKMNP-TV-Z]{26}$/.test(raw.incident_id)) continue;
    const linked = (Array.isArray(raw.linked_verdicts) ? raw.linked_verdicts : []).filter((x): x is string => typeof x === "string");
    if (!linked.some((id) => mine.has(id))) continue;
    const sev = (["low", "medium", "high", "critical"] as const).find((x) => x === raw.severity);
    const sum = isObj(raw.summary) ? raw.summary : {};
    const cut = (x: unknown) => (typeof x === "string" ? x.slice(0, 240) : undefined);
    const drafts = (Array.isArray(raw.actions) ? raw.actions : []).filter(isObj).filter((a) => a.mode === "external_draft" && a.status !== "rejected" && a.status !== "failed");
    return {
      id: raw.incident_id,
      severity: sev ?? "low",
      linked: linked.length,
      summary: { ar: cut(sum.ar), en: cut(sum.en) },
      drafted: drafts.length > 0,
      awaiting: drafts.some((a) => a.status === "awaiting_approval"),
    };
  }
  return null;
}

export type SentinelStep = "linked" | "summary" | "draft" | "awaiting_approval";

/**
 * Plain-words steps, each proven by data: linking and the summary by the incident's real LangGraph trace,
 * the takedown draft and the approval wait by the incident's own action types and status.
 */
export function sentinelSteps(trace: unknown, incident: Pick<SentinelIncident, "drafted" | "awaiting">): SentinelStep[] {
  const runs = isObj(trace) && Array.isArray(trace.runs) ? trace.runs.filter(isObj) : [];
  const nodes = new Set(runs.flatMap((r) => (Array.isArray(r.steps) ? r.steps.filter(isObj) : [])).map((x) => x.node));
  const out: SentinelStep[] = [];
  if (nodes.has("enrich") || nodes.has("compare")) out.push("linked");
  if (nodes.has("summarise")) out.push("summary");
  if (incident.drafted) out.push("draft");
  if (incident.drafted && incident.awaiting) out.push("awaiting_approval");
  return out;
}

/** Retry delay after repeated voice-service failures: 1 s, 2 s, 4 s, 8 s, then at most 15 s. */
export const voiceBackoffMs = (failures: number): number => Math.min(15_000, 1000 * 2 ** Math.max(0, failures - 1));

/**
 * ONE decision for the AI second look, used by the screen AND the speech: a model answered (route local/cloud)
 * or the fixed rules decided (route none). The screen and the spoken line can never disagree.
 */
export const usedModel = (v: Verdict): boolean => v.model_route !== "none";
