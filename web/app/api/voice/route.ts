import { WindowLimiter, visitorKey } from "@/lib/public-campaigns";
import { VOICE_LIMITS, parseVoiceReply } from "@/lib/voice";
import { apiBase, notConnected, upstreamHeaders } from "../public/campaigns/shared";

export const dynamic = "force-dynamic";

/**
 * Per visitor: 30 a minute, the same as the API (FL_VOICE_RATE_PER_MIN) and docs/PRIVACY.md. Continuous listening
 * sends one clip per heard sentence, so a presenter talking next to the microphone can send one every few seconds;
 * at 20 the 429 could land on the wake phrase itself (estimate from sentence length, not a measurement).
 */
const limiter = new WindowLimiter(30, 60_000);
/** Multipart overhead on top of the 1 MB audio cap. */
const MAX_BODY = VOICE_LIMITS.maxBytes + 16 * 1024;
const AUDIO_TYPES = /^(audio\/(webm|ogg|wav|x-wav|wave)|video\/webm)(;|$)/i;

/** Pre-warm ping on enabling hands-free mode: wakes this route, touches nothing upstream, returns nothing sensitive. */
export async function GET(): Promise<Response> {
  return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
}

/**
 * Hands-free voice: relays one short utterance to POST /v1/voice/utterance with the server-only key.
 * The browser never sees the key. Audio and transcripts are never logged or stored here; nothing in this
 * file writes either to a log, a file or a cache.
 */
export async function POST(request: Request): Promise<Response> {
  const wait = limiter.take(visitorKey(request));
  if (wait > 0) return notConnected(429, { "Retry-After": String(wait) });

  const length = Number.parseInt(request.headers.get("content-length") ?? "", 10);
  if (!Number.isFinite(length)) return notConnected(411);
  if (length > MAX_BODY) return notConnected(413);
  if (!(request.headers.get("content-type") ?? "").toLowerCase().startsWith("multipart/form-data")) return notConnected(415);

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return notConnected(400);
  }
  const audio = form.get("audio");
  if (!(audio instanceof File) || audio.size === 0) return notConnected(400);
  if (audio.size > VOICE_LIMITS.maxBytes) return notConnected(413);
  if (!AUDIO_TYPES.test(audio.type)) return notConnected(415);

  const out = new FormData();
  out.append("audio", audio, "utterance");
  const hint = form.get("lang_hint");
  if (hint === "ar" || hint === "en") out.append("lang_hint", hint);
  if (form.get("follow_up") === "1") out.append("follow_up", "1");

  const headers = upstreamHeaders(request, "application/json");
  if (!headers) return notConnected(503);
  try {
    const upstream = await fetch(`${apiBase()}/v1/voice/utterance`, { method: "POST", headers, body: out, cache: "no-store", signal: AbortSignal.timeout(20_000) });
    if (upstream.status === 429) return notConnected(429, { "Retry-After": "10" });
    if (upstream.status === 413 || upstream.status === 415 || upstream.status === 404) return notConnected(upstream.status);
    // 422: this clip was refused (too long, undecodable) and the service is fine. 503: both speech engines are down.
    // Passed through so the page can tell "say it again" from "voice is unavailable" (both used to be a 502).
    if (upstream.status === 422) return notConnected(422);
    if (upstream.status === 503) return notConnected(503, { "Retry-After": "2" });
    if (!upstream.ok) return notConnected(502);
    const reply = parseVoiceReply(await upstream.json());
    if (!reply) return notConnected(502);
    // The utterance span's trace context (a W3C id, no content): the browser sends it with the checks it starts.
    const tp = upstream.headers.get("traceparent") ?? "";
    const link: Record<string, string> = /^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$/.test(tp) ? { traceparent: tp } : {};
    const { answerId, ...rest } = reply; // the browser contract keeps the API field name
    return Response.json({ ...rest, answer_id: answerId }, { headers: { "Cache-Control": "no-store", ...link } });
  } catch {
    return notConnected(502);
  }
}
