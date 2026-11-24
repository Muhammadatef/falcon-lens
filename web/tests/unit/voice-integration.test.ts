import { afterEach, describe, expect, it, vi } from "vitest";
import { submitCheck } from "@/lib/api";
import { parseSummary } from "@/lib/history";
import { arbiterKeys, finalKeys, findingKeys, foundKeys, speakArbiter, speakFinal, speakFound, stepKeys } from "@/lib/voice-speech";
import { CLIPS, clipId } from "@/lib/voice-script";

const VID = "vd_01HZX3K9Q2M4N5P6R7S8T9V0WX";
const TP = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";

function stubFetch() {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ verdict_id: VID, events_url: `/v1/verdicts/${VID}/events`, status_url: `/v1/verdicts/${VID}` }), { status: 202 });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("voice checks use the public check API with a channel marker", () => {
  it("sends channel=voice and the utterance traceparent on /v1/check/message", async () => {
    const calls = stubFetch();
    await submitCheck({ kind: "message", text: "hello" }, { channel: "voice", traceparent: TP });
    expect(calls[0]!.url).toBe("/v1/check/message");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({ text: "hello", channel: "voice" });
    expect((calls[0]!.init.headers as Record<string, string>).traceparent).toBe(TP);
  });

  it("the Check page default is channel=web, and a malformed traceparent is never forwarded", async () => {
    const calls = stubFetch();
    await submitCheck({ kind: "url", url: "https://example.test/a" });
    await submitCheck({ kind: "url", url: "https://example.test/b" }, { channel: "voice", traceparent: "not-a-trace; x" });
    expect(JSON.parse(calls[0]!.init.body as string).channel).toBe("web");
    expect((calls[1]!.init.headers as Record<string, string>).traceparent).toBeUndefined();
  });
});

describe("history summary channel", () => {
  const row = { verdict_id: VID, created_at: "2026-11-24T10:00:00Z", input_type: "message", display: null, verdict: "dangerous", risk_score: 90, degraded: false, degraded_reasons: [], tier_reached: "T1", model_route: "none", source: "live", agent: {} };
  it("keeps only enum channels", () => {
    expect(parseSummary({ ...row, channel: "voice" })?.channel).toBe("voice");
    expect(parseSummary({ ...row, channel: "x<script>" })).not.toHaveProperty("channel");
    expect(parseSummary(row)).not.toHaveProperty("channel");
  });
});

describe("narration is composed of pre-generated clip ids only", () => {
  const known = new Set(CLIPS.map((c) => c.key));
  it("every key the assistant plays exists in the script, in both languages", () => {
    const keys = [...foundKeys(3), ...finalKeys([], "watching"), ...arbiterKeys(null), ...findingKeys({ linked: 3, linkStep: true, summary: true, drafted: true, awaiting: true })];
    for (const k of keys) {
      expect(known.has(k), k).toBe(true);
      expect(CLIPS.some((c) => c.id === clipId("ar_ae", k))).toBe(true);
      expect(CLIPS.some((c) => c.id === clipId("en", k))).toBe(true);
    }
    expect(stepKeys("lists", { model_route: "none" } as never)).toEqual(["investigator.lists"]);
    expect(stepKeys("wording", { model_route: "none" } as never)).toEqual([]);
  });

  it("the spoken text and the keys never drift apart", () => {
    expect(speakFound("en", 3)).toBe("I found three messages.");
    expect(speakArbiter("en", null)).toBe("The message could not be checked.");
    expect(speakFinal("en", [], "watching")).toBe("");
  });
});
