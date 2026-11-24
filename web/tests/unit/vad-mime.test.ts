import { describe, expect, it } from "vitest";
import { AUDIO_TYPES } from "../../lib/voice";
import { pickMimeType } from "../../lib/vad";

describe("pickMimeType", () => {
  it("prefers webm/opus where it exists (Chrome, Android)", () => {
    expect(pickMimeType(() => true)).toBe("audio/webm;codecs=opus");
  });
  it("falls back to ogg, then mp4/aac (iOS Safari records only audio/mp4)", () => {
    expect(pickMimeType((t) => t.startsWith("audio/ogg") || t.startsWith("audio/mp4"))).toBe("audio/ogg;codecs=opus");
    expect(pickMimeType((t) => t === "audio/mp4")).toBe("audio/mp4");
    expect(pickMimeType((t) => t.startsWith("audio/mp4"))).toBe("audio/mp4;codecs=mp4a.40.2");
  });
  it("returns null when nothing is recordable and survives a throwing engine", () => {
    expect(pickMimeType(() => false)).toBeNull();
    expect(
      pickMimeType((t) => {
        if (t.includes("webm")) throw new Error("boom");
        return t === "audio/mp4";
      }),
    ).toBe("audio/mp4");
  });
});

describe("stableDate (iOS hydration)", () => {
  it("drops the Arabic comma and bidi marks WebKit adds, so server and Safari render the same text", async () => {
    const { stableDate } = await import("../../lib/i18n");
    const fmt = { format: () => "23 نوفمبر،‏ 2026" } as unknown as Intl.DateTimeFormat;
    expect(stableDate(fmt, new Date(0))).toBe("23 نوفمبر 2026");
  });
});

describe("web route audio types", () => {
  it("accepts what iOS records and refuses the rest", () => {
    for (const t of ["audio/mp4", "audio/mp4;codecs=mp4a.40.2", "audio/aac", "audio/x-m4a", "audio/webm;codecs=opus", "audio/wav"]) expect(AUDIO_TYPES.test(t)).toBe(true);
    for (const t of ["audio/mpeg", "text/plain", "application/octet-stream", "video/x-matroska"]) expect(AUDIO_TYPES.test(t)).toBe(false);
  });
});
