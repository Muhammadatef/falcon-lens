import { describe, expect, it, vi } from "vitest";
import { VOICE_PROBLEM_TEXT, isClipProblem, postUtterance, reasonOf, voiceProblemText } from "@/lib/voice-request";

const REPLY = { transcript: "Hey Falcon, check my messages", lang: "en", wake: true, intent: "check_clipboard", command: "check my messages", answer_id: null, duration_ms: 2300, model: "native:whisper-large-v3-turbo" };
const json = (status: number, body: unknown, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
const form = () => {
  const f = new FormData();
  f.append("audio", new Blob([new Uint8Array([1, 2, 3])], { type: "audio/webm" }), "utterance");
  return f;
};

describe("postUtterance", () => {
  it("returns the parsed reply and the trace id on the first try", async () => {
    const fetchImpl = vi.fn(async () => json(200, REPLY, { traceparent: "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" }));
    const out = await postUtterance(form(), { fetchImpl });
    expect(out.ok && out.reply.intent).toBe("check_clipboard");
    expect(out.ok && out.traceparent).toMatch(/^00-/);
    expect(out.attempts).toBe(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("gives up on a stalled request after the time limit, retries once, and tells the page before the retry", async () => {
    const stall = (_url: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason ?? new DOMException("timed out", "TimeoutError")));
      });
    const fetchImpl = vi.fn(stall).mockImplementationOnce(stall).mockImplementationOnce(async () => json(200, REPLY));
    const onRetry = vi.fn();
    const t0 = Date.now();
    const out = await postUtterance(form(), { fetchImpl, timeoutMs: 60, onRetry });
    expect(Date.now() - t0).toBeLessThan(1000);
    expect(out.ok).toBe(true);
    expect(out.attempts).toBe(2);
    expect(onRetry).toHaveBeenCalledExactlyOnceWith(1, "timeout");
  });

  it("reports a timeout after two stalled attempts and never tries a third time", async () => {
    const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_r, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("timed out", "TimeoutError")))));
    const out = await postUtterance(form(), { fetchImpl, timeoutMs: 30 });
    expect(out).toMatchObject({ ok: false, reason: "timeout", attempts: 2 });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("retries a connection error and a 502/503 once", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(json(200, REPLY));
    expect((await postUtterance(form(), { fetchImpl })).ok).toBe(true);
    const down = vi.fn(async () => json(503, { error: "voice_unavailable" }, { "retry-after": "2" }));
    const out = await postUtterance(form(), { fetchImpl: down });
    expect(out).toMatchObject({ ok: false, reason: "voice_unavailable", status: 503, retryAfterS: 2, attempts: 2 });
  });

  it("never retries a refused clip or a rate limit", async () => {
    for (const [status, body, reason] of [
      [422, { error: "audio_too_long" }, "audio_too_long"],
      [422, { error: "audio_refused" }, "audio_refused"],
      [413, { error: "audio_refused" }, "audio_refused"],
      [429, { error: "rate_limited" }, "rate_limited"],
    ] as const) {
      const fetchImpl = vi.fn(async () => json(status, body, { "retry-after": "7" }));
      const onRetry = vi.fn();
      const out = await postUtterance(form(), { fetchImpl, onRetry });
      expect(out).toMatchObject({ ok: false, reason, status, attempts: 1 });
      expect(fetchImpl).toHaveBeenCalledTimes(1);
      expect(onRetry).not.toHaveBeenCalled();
    }
  });

  it("treats a 200 that is not a voice reply as a failure", async () => {
    const out = await postUtterance(form(), { fetchImpl: vi.fn(async () => json(200, { hello: "world" })), retries: 0 });
    expect(out).toMatchObject({ ok: false, reason: "not_connected", attempts: 1 });
  });
});

describe("voice problem reasons and texts", () => {
  it("maps statuses when the body names nothing", () => {
    expect(reasonOf(429, null)).toBe("rate_limited");
    expect(reasonOf(503, {})).toBe("voice_unavailable");
    expect(reasonOf(422, { error: "not_connected" })).toBe("audio_refused");
    expect(reasonOf(502, { error: "something_new" })).toBe("not_connected");
  });
  it("only a refused clip is the speaker's to fix", () => {
    expect(isClipProblem("audio_too_long")).toBe(true);
    expect(isClipProblem("voice_unavailable")).toBe(false);
  });
  it("has Arabic and English for every reason and never says safe", () => {
    for (const [reason, t] of Object.entries(VOICE_PROBLEM_TEXT)) {
      expect(t.ar.length, reason).toBeGreaterThan(8);
      expect(t.en.length, reason).toBeGreaterThan(8);
      expect(/[؀-ۿ]/.test(t.ar), reason).toBe(true);
      expect(/\bsafe\b/i.test(t.en) || t.ar.includes("آمن"), reason).toBe(false);
    }
    expect(voiceProblemText("audio_too_long", "en")).toContain("15 seconds");
  });
});
