import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clipReason, retryAfterSeconds } from "@/lib/voice-request";
import { POST } from "./route";

const REPLY = { transcript: "Hey Falcon, check my messages", lang: "en", wake: true, intent: "check_clipboard", command: "check my messages", answer_id: null, duration_ms: 2300, model: "native:whisper-large-v3-turbo" };
const problem = (slug: string) => ({ type: `https://falconlens.app/problems/${slug}`, title: slug, status: 422 });
let n = 0;

/** Each request comes from its own visitor so the per-visitor limiter never interferes. */
function utterance(): Request {
  const form = new FormData();
  form.append("audio", new File([new Uint8Array(2000)], "utterance", { type: "audio/webm" }));
  const body = new Request("http://web.test/api/voice", { method: "POST", body: form });
  return new Request("http://web.test/api/voice", {
    method: "POST",
    headers: { "content-type": body.headers.get("content-type") ?? "", "content-length": "2400", "x-falcon-client-ip": `198.51.100.${++n}` },
    body: body.body,
    // @ts-expect-error duplex is required by Node for a streamed request body and is missing from the DOM types
    duplex: "half",
  });
}

function upstream(status: number, body: unknown, headers: Record<string, string> = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } })));
}

beforeEach(() => {
  vi.stubEnv("FL_WEB_READ_KEY", "test-key-not-a-secret");
  vi.stubEnv("FL_API_INTERNAL_URL", "http://api.test:8000");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("POST /api/voice passes the API's answer through with its meaning", () => {
  it("relays a good reply", async () => {
    upstream(200, REPLY);
    const res = await POST(utterance());
    expect(res.status).toBe(200);
    expect((await res.json()).intent).toBe("check_clipboard");
  });

  it("a clip that is too long is a 422 audio_too_long, not a 502 (the live bench saw 502)", async () => {
    upstream(422, problem("audio-too-long"));
    const res = await POST(utterance());
    expect(res.status).toBe(422);
    expect(await res.json()).toEqual({ error: "audio_too_long" });
  });

  it("an undecodable clip is a 422 audio_refused", async () => {
    upstream(422, problem("undecodable-audio"));
    const res = await POST(utterance());
    expect([res.status, (await res.json()).error]).toEqual([422, "audio_refused"]);
  });

  it("a rate limit keeps the API's Retry-After", async () => {
    upstream(429, { type: "rate-limited" }, { "retry-after": "37" });
    const res = await POST(utterance());
    expect([res.status, res.headers.get("retry-after"), (await res.json()).error]).toEqual([429, "37", "rate_limited"]);
  });

  it("engines down is a 503 voice_unavailable with a short Retry-After", async () => {
    upstream(503, { type: "stt-unavailable" }, { "retry-after": "2" });
    const res = await POST(utterance());
    expect([res.status, res.headers.get("retry-after"), (await res.json()).error]).toEqual([503, "2", "voice_unavailable"]);
  });

  it("an API that does not answer in time is a 504 timeout; any other failure stays a 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new DOMException("timed out", "TimeoutError"))));
    const slow = await POST(utterance());
    expect([slow.status, (await slow.json()).error]).toEqual([504, "timeout"]);
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    expect((await POST(utterance())).status).toBe(502);
    upstream(500, {});
    expect((await POST(utterance())).status).toBe(502);
  });

  it("allows 30 clips a minute from one visitor, then answers 429 rate_limited", async () => {
    upstream(200, REPLY);
    const same = () => {
      const r = utterance();
      r.headers.set("x-falcon-client-ip", "198.51.100.250");
      return r;
    };
    for (let i = 0; i < 30; i++) expect((await POST(same())).status).toBe(200);
    const res = await POST(same());
    expect([res.status, (await res.json()).error]).toEqual([429, "rate_limited"]);
    expect(Number(res.headers.get("retry-after"))).toBeGreaterThan(0);
  });
});

describe("route helpers", () => {
  it("reads the problem slug", () => {
    expect(clipReason(problem("audio-too-long"))).toBe("audio_too_long");
    expect(clipReason(problem("undecodable-audio"))).toBe("audio_refused");
    expect(clipReason(null)).toBe("audio_refused");
  });
  it("keeps Retry-After within 1..60 seconds", () => {
    expect(retryAfterSeconds("37", 10)).toBe("37");
    expect(retryAfterSeconds(null, 10)).toBe("10");
    expect(retryAfterSeconds("9999", 10)).toBe("10");
    expect(retryAfterSeconds("abc", 2)).toBe("2");
  });
});
