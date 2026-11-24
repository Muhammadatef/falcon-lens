import { afterEach, describe, expect, it, vi } from "vitest";
import { createVoicePlayer, type VoiceManifestEntry } from "@/lib/voice-player";

const manifest: VoiceManifestEntry[] = [
  { id: "ar_ae.a", file: "ar_ae.a.mp3", text: "ا", ms: 100, engine: "x", voice: "v" },
  { id: "ar_ae.b", file: "ar_ae.b.mp3", text: "ب", ms: 100, engine: "x", voice: "v" },
  { id: "ar_ae.broken", file: "ar_ae.broken.mp3", text: "نص احتياطي", ms: 100, engine: "x", voice: "v" },
];

function mockFetch(opts: { manifestOk?: boolean } = {}) {
  return vi.fn(async (url: string) => {
    if (url.endsWith("manifest.json")) {
      return opts.manifestOk === false
        ? ({ ok: false } as Response)
        : ({ ok: true, json: async () => manifest } as unknown as Response);
    }
    if (url.includes("broken")) return { ok: false } as Response;
    return { ok: true, arrayBuffer: async () => new ArrayBuffer(8) } as unknown as Response;
  }) as unknown as typeof fetch;
}

/** AudioContext whose sources "play" for 10 ms and record start order and overlap. */
function mockAudio() {
  const log: string[] = [];
  let active = 0;
  let maxActive = 0;
  const ctx = {
    state: "running",
    destination: {},
    resume: async () => undefined,
    decodeAudioData: async () => ({ tag: "buf" }) as unknown as AudioBuffer,
    createBufferSource() {
      const src: Record<string, unknown> = {
        buffer: null,
        connect: () => undefined,
        onended: null,
        start() {
          active++;
          maxActive = Math.max(maxActive, active);
          log.push("start");
          src.timer = setTimeout(() => {
            active--;
            (src.onended as (() => void) | null)?.();
          }, 10);
        },
        stop() {
          clearTimeout(src.timer as ReturnType<typeof setTimeout>);
          active--;
          log.push("stop");
        },
      };
      return src;
    },
  } as unknown as AudioContext;
  return { ctx, log, maxActive: () => maxActive };
}

function mockSynth() {
  const spoken: string[] = [];
  const synth = {
    speak: (u: { text: string; onend: () => void }) => {
      spoken.push(u.text);
      setTimeout(() => u.onend(), 5);
    },
    cancel: vi.fn(),
  } as unknown as SpeechSynthesis;
  return { synth, spoken };
}

class Utt {
  constructor(public text: string) {}
  lang = "";
  onend: () => void = () => undefined;
  onerror: () => void = () => undefined;
}

afterEach(() => vi.unstubAllGlobals());

describe("voice player", () => {
  it("plays a sequence in order with gaps and never overlaps", async () => {
    vi.stubGlobal("SpeechSynthesisUtterance", Utt);
    const a = mockAudio();
    const p = createVoicePlayer({
      lang: "ar_ae",
      gapMs: 20,
      fetchImpl: mockFetch(),
      audioContext: () => a.ctx,
      synth: null,
    });
    await p.ready;
    expect(p.has("ar_ae.a")).toBe(true);
    expect(p.has("ar_ae.missing")).toBe(false);
    const t0 = Date.now();
    await p.play(["ar_ae.a", "ar_ae.b", "ar_ae.a"]);
    expect(a.log).toEqual(["start", "start", "start"]);
    expect(a.maxActive()).toBe(1);
    expect(Date.now() - t0).toBeGreaterThanOrEqual(2 * 20 + 3 * 10 - 8);
  });

  it("hands a missing clip to speakFallback (the app's voice picker) instead of raw speechSynthesis", async () => {
    const a = mockAudio();
    const s = mockSynth();
    const said: string[] = [];
    const p = createVoicePlayer({
      lang: "ar_ae",
      gapMs: 1,
      fetchImpl: mockFetch(),
      audioContext: () => a.ctx,
      synth: s.synth,
      fallbackText: (id) => (id === "ar_ae.nope" ? "غير موجود" : undefined),
      speakFallback: async (text, alive) => {
        if (alive()) said.push(text);
      },
    });
    await p.play(["ar_ae.a", "ar_ae.nope"]);
    expect(a.log).toEqual(["start"]);
    expect(said).toEqual(["غير موجود"]);
    expect(s.spoken).toEqual([]);
  });

  it("falls back to speech for ids missing from the manifest or failing to decode", async () => {
    vi.stubGlobal("SpeechSynthesisUtterance", Utt);
    const a = mockAudio();
    const s = mockSynth();
    const p = createVoicePlayer({
      lang: "ar_ae",
      gapMs: 1,
      fetchImpl: mockFetch(),
      audioContext: () => a.ctx,
      synth: s.synth,
      fallbackText: (id) => (id === "ar_ae.nope" ? "غير موجود" : undefined),
    });
    await p.play(["ar_ae.a", "ar_ae.nope", "ar_ae.broken", "ar_ae.unknown"]);
    expect(a.log).toEqual(["start"]);
    expect(s.spoken).toEqual(["غير موجود", "نص احتياطي"]);
  });

  it("uses speech for everything when the manifest fails to load", async () => {
    vi.stubGlobal("SpeechSynthesisUtterance", Utt);
    const s = mockSynth();
    const p = createVoicePlayer({
      lang: "en",
      gapMs: 1,
      fetchImpl: mockFetch({ manifestOk: false }),
      audioContext: () => mockAudio().ctx,
      synth: s.synth,
      fallbackText: (id) => `say ${id}`,
    });
    await p.play(["en.x", "en.y"]);
    expect(s.spoken).toEqual(["say en.x", "say en.y"]);
    expect(p.has("en.x")).toBe(false);
  });

  it("stop() halts immediately and resolves play()", async () => {
    vi.stubGlobal("SpeechSynthesisUtterance", Utt);
    const a = mockAudio();
    const s = mockSynth();
    const p = createVoicePlayer({
      lang: "ar_ae",
      gapMs: 50,
      fetchImpl: mockFetch(),
      audioContext: () => a.ctx,
      synth: s.synth,
    });
    await p.ready;
    const run = p.play(["ar_ae.a", "ar_ae.b", "ar_ae.a"]);
    await new Promise((r) => setTimeout(r, 3));
    p.stop();
    await run;
    expect(a.log).toEqual(["start", "stop"]);
    expect(s.synth.cancel).toHaveBeenCalled();
  });

  it("a new play() cancels the one in flight without overlap", async () => {
    vi.stubGlobal("SpeechSynthesisUtterance", Utt);
    const a = mockAudio();
    const p = createVoicePlayer({
      lang: "ar_ae",
      gapMs: 20,
      fetchImpl: mockFetch(),
      audioContext: () => a.ctx,
      synth: null,
    });
    await p.ready;
    const first = p.play(["ar_ae.a", "ar_ae.b"]);
    await new Promise((r) => setTimeout(r, 3));
    const second = p.play(["ar_ae.b"]);
    await Promise.all([first, second]);
    expect(a.maxActive()).toBe(1);
    expect(a.log.filter((x) => x === "start")).toHaveLength(2);
  });
});
