/**
 * One spoken utterance to /api/voice, with a time limit and one automatic retry. No DOM, so it is unit-tested.
 *
 * Why: over the public tunnel the live bench saw requests hang for 30 s and connections fail outright. A page that
 * waits that long looks dead. Here a request is given `timeoutMs` (10 s), and a timeout, a network error or a
 * gateway/engine failure (502, 503, 504) is retried once; `onRetry` lets the page say its "still checking" line.
 * A refused clip (413, 415, 422) and a rate limit (429) are never retried: the answer would be the same.
 *
 * Audio and transcripts are never logged or stored here.
 */
import type { Lang } from "./contracts";
import { parseVoiceReply, type VoiceReply } from "./voice";

/** Why a voice request did not produce an answer. `error` in the /api/voice body carries the same codes. */
export type VoiceProblemReason = "audio_too_long" | "audio_refused" | "rate_limited" | "voice_unavailable" | "timeout" | "not_connected";

export const VOICE_REQUEST = { timeoutMs: 10_000, retries: 1 } as const;

/** Shown (never spoken) next to the microphone. Formal Arabic first; short enough for a phone screen. */
export const VOICE_PROBLEM_TEXT: Record<VoiceProblemReason, Record<Lang, string>> = {
  audio_too_long: { ar: "المقطع أطول من 15 ثانية. قل طلبك في جملة قصيرة.", en: "That was longer than 15 seconds. Say it in one short sentence." },
  audio_refused: { ar: "تعذّرت قراءة المقطع الصوتي. حاول مرة أخرى.", en: "We could not read that recording. Please try again." },
  rate_limited: { ar: "طلبات كثيرة في وقت قصير. انتظر لحظات ثم حاول مرة أخرى.", en: "Too many requests in a short time. Wait a moment, then try again." },
  voice_unavailable: { ar: "خدمة التعرّف على الصوت غير متاحة الآن. يمكنك لصق الرسالة في المربع.", en: "Speech recognition is unavailable right now. You can paste the message in the box." },
  timeout: { ar: "الاتصال بطيء. حاول مرة أخرى، أو الصق الرسالة في المربع.", en: "The connection is slow. Try again, or paste the message in the box." },
  not_connected: { ar: "تعذّر الاتصال بالخدمة. حاول مرة أخرى.", en: "We could not reach the service. Please try again." },
};

export function voiceProblemText(reason: VoiceProblemReason, lang: Lang): string {
  return VOICE_PROBLEM_TEXT[reason][lang];
}

/** True when the same clip can never succeed on a retry: it does not count as a service failure. */
export function isClipProblem(reason: VoiceProblemReason): boolean {
  return reason === "audio_too_long" || reason === "audio_refused";
}

export type VoiceRequestResult =
  | { ok: true; reply: VoiceReply; traceparent: string | null; attempts: number }
  | { ok: false; reason: VoiceProblemReason; status: number; retryAfterS: number | null; attempts: number };

export interface VoiceRequestOptions {
  timeoutMs?: number;
  retries?: number;
  /** Called once before each retry (attempt number that failed, why): the page plays its "still checking" line. */
  onRetry?: (attempt: number, reason: VoiceProblemReason) => void;
  fetchImpl?: typeof fetch;
  url?: string;
}

const REASONS: readonly VoiceProblemReason[] = ["audio_too_long", "audio_refused", "rate_limited", "voice_unavailable", "timeout", "not_connected"];

/** Reason from the status and the body's `error` code (unknown codes fall back to the status). */
export function reasonOf(status: number, body: unknown): VoiceProblemReason {
  const code = typeof body === "object" && body !== null ? (body as Record<string, unknown>).error : null;
  const named = REASONS.find((r) => r === code);
  if (named && named !== "not_connected") return named;
  if (status === 429) return "rate_limited";
  if (status === 503) return "voice_unavailable";
  if (status === 504) return "timeout";
  if (status === 413 || status === 415 || status === 422) return "audio_refused";
  return "not_connected";
}

/** Seconds from an upstream Retry-After header, kept within 1..60; `fallback` when it is missing or odd. */
export function retryAfterSeconds(raw: string | null, fallback: number): string {
  const n = Number.parseInt(raw ?? "", 10);
  return String(Number.isFinite(n) && n >= 1 && n <= 60 ? n : fallback);
}

/** The API answers a refused clip with a problem document; its `type` ends in the slug (audio-too-long, ...). */
export function clipReason(problem: unknown): VoiceProblemReason {
  const type = typeof problem === "object" && problem !== null ? (problem as Record<string, unknown>).type : "";
  return typeof type === "string" && type.includes("audio-too-long") ? "audio_too_long" : "audio_refused";
}

const RETRYABLE = new Set([502, 503, 504]);

function retryAfter(res: Response): number | null {
  const n = Number.parseInt(res.headers.get("retry-after") ?? "", 10);
  return Number.isFinite(n) && n >= 0 && n <= 120 ? n : null;
}

export async function postUtterance(form: FormData, options: VoiceRequestOptions = {}): Promise<VoiceRequestResult> {
  const timeoutMs = options.timeoutMs ?? VOICE_REQUEST.timeoutMs;
  const retries = options.retries ?? VOICE_REQUEST.retries;
  const doFetch = options.fetchImpl ?? fetch;
  let last: VoiceRequestResult = { ok: false, reason: "not_connected", status: 0, retryAfterS: null, attempts: 0 };
  for (let attempt = 1; attempt <= retries + 1; attempt++) {
    let retry = false;
    try {
      const res = await doFetch(options.url ?? "/api/voice", { method: "POST", body: form, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
      const body: unknown = await res.json().catch(() => null);
      if (res.ok) {
        const reply = parseVoiceReply(body);
        if (reply) return { ok: true, reply, traceparent: res.headers.get("traceparent"), attempts: attempt };
        last = { ok: false, reason: "not_connected", status: 502, retryAfterS: null, attempts: attempt };
        retry = true;
      } else {
        last = { ok: false, reason: reasonOf(res.status, body), status: res.status, retryAfterS: retryAfter(res), attempts: attempt };
        retry = RETRYABLE.has(res.status);
      }
    } catch (err) {
      const timedOut = err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
      last = { ok: false, reason: timedOut ? "timeout" : "not_connected", status: 0, retryAfterS: null, attempts: attempt };
      retry = true;
    }
    if (!retry || attempt > retries) break;
    options.onRetry?.(attempt, last.reason);
  }
  return last;
}
