/** Types, settings and message shapes shared by the service worker and the extension pages. */
import type { Lang, VerdictWord } from "./i18n";
import type { PrefilterResult } from "./prefilter";

declare const __FL_API_BASE__: string;
declare const __FL_WEB_BASE__: string;

export const DEFAULT_API_BASE: string = __FL_API_BASE__;
export const DEFAULT_WEB_BASE: string = __FL_WEB_BASE__;

export const CACHE_TTL_MS = 10 * 60 * 1000;
export const ALLOW_TTL_MS = 10 * 60 * 1000;
export const HOVER_DELAY_MS = 400;
export const SERVER_WAIT_S = 6;

export interface Settings {
  apiBase: string;
  apiKey: string;
  webBase: string;
  lang: Lang;
  serverChecks: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  apiBase: DEFAULT_API_BASE,
  apiKey: "",
  webBase: DEFAULT_WEB_BASE,
  lang: "ar",
  serverChecks: true,
};

export async function loadSettings(): Promise<Settings> {
  const raw = (await chrome.storage.local.get("settings"))["settings"] as Partial<Settings> | undefined;
  const s = { ...DEFAULT_SETTINGS, ...(raw ?? {}) };
  if (s.lang !== "ar" && s.lang !== "en") s.lang = "ar";
  if (!normaliseBase(s.apiBase)) s.apiBase = DEFAULT_API_BASE;
  if (!normaliseBase(s.webBase)) s.webBase = DEFAULT_WEB_BASE;
  return s;
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  const next = { ...(await loadSettings()), ...patch };
  await chrome.storage.local.set({ settings: next });
  return next;
}

/** https anywhere, http only for this computer. Returns the origin, or null when not acceptable. */
export function normaliseBase(value: string): string | null {
  let u: URL;
  try {
    u = new URL(value.trim());
  } catch {
    return null;
  }
  const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
  if (u.protocol !== "https:" && !(u.protocol === "http:" && local)) return null;
  if (u.username || u.password) return null;
  return u.origin;
}

/** Host permission pattern for an origin. Match patterns carry no port. */
export const permissionPattern = (origin: string): string => `${new URL(origin).protocol}//${new URL(origin).hostname}/*`;

export const isWebUrl = (value: string): boolean => {
  try {
    const p = new URL(value).protocol;
    return p === "http:" || p === "https:";
  } catch {
    return false;
  }
};

/** The part of a contract Verdict the extension shows. Everything else is dropped on receipt. */
export interface SlimVerdict {
  verdict_id: string;
  verdict: VerdictWord;
  risk_score: number;
  final: boolean;
  degraded: boolean;
  source: "live" | "replay" | "synthetic" | "fixture";
  brand: { name_ar: string; name_en: string; domains: string[] } | null;
  reasons: { ar: string; en: string }[];
  now: { ar: string[]; en: string[] };
  caution: { ar: string[]; en: string[] };
}

export type CheckError = "offline" | "disabled" | "rate_limited" | "no_permission" | "bad_response" | "unsupported";
export type CheckReply = { ok: true; verdict: SlimVerdict } | { ok: false; error: CheckError };

export type Message =
  | { type: "prefilter"; url: string }
  | { type: "check"; url: string }
  | { type: "allow"; url: string }
  | { type: "back_steps"; url: string }
  | { type: "ping" };

export interface PrefilterReply {
  local: PrefilterResult;
  lang: Lang;
}

const str = (v: unknown, max: number): string => (typeof v === "string" ? v.slice(0, max) : "");
const list = (v: unknown, n: number, max: number): string[] =>
  Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, n).map((x) => (x as string).slice(0, max)) : [];
const bilingual = (v: unknown): { ar: string[]; en: string[] } => {
  const o = (v ?? {}) as Record<string, unknown>;
  return { ar: list(o["ar"], 6, 160), en: list(o["en"], 6, 160) };
};

/**
 * Validate and shrink a server response. The server is trusted for the verdict, not for shape:
 * anything outside the contract enums is rejected, and every string is length-capped.
 */
export function slimVerdict(raw: unknown): SlimVerdict | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Record<string, unknown>;
  const word = v["verdict"];
  if (word !== "dangerous" && word !== "suspicious" && word !== "no_warning_signs") return null;
  if (typeof v["verdict_id"] !== "string" || !/^vd_[0-9A-HJKMNP-TV-Z]{26}$/.test(v["verdict_id"])) return null;
  const score = typeof v["risk_score"] === "number" ? Math.max(0, Math.min(100, Math.round(v["risk_score"]))) : 0;
  const b = v["impersonated_brand"] as Record<string, unknown> | null | undefined;
  const actions = (v["actions"] ?? {}) as Record<string, unknown>;
  const src = v["source"];
  const reasons = Array.isArray(v["reasons"]) ? v["reasons"] : [];
  return {
    verdict_id: v["verdict_id"],
    verdict: word,
    risk_score: score,
    final: v["final"] === true,
    degraded: v["degraded"] === true,
    source: src === "replay" || src === "synthetic" || src === "fixture" ? src : "live",
    brand:
      b && typeof b === "object"
        ? { name_ar: str(b["name_ar"], 80), name_en: str(b["name_en"], 80), domains: list(b["official_domains"], 4, 80) }
        : null,
    reasons: reasons
      .slice(0, 3)
      .map((r) => ({ ar: str((r as Record<string, unknown>)?.["ar"], 220), en: str((r as Record<string, unknown>)?.["en"], 220) }))
      .filter((r) => r.ar || r.en),
    now: bilingual(actions["now"]),
    caution: bilingual(actions["caution"]),
  };
}

export const send = <T>(msg: Message): Promise<T> => chrome.runtime.sendMessage(msg) as Promise<T>;
