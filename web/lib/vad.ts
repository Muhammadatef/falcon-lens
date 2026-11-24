/**
 * In-browser voice-activity detector for hands-free mode: Web Audio (AnalyserNode RMS energy) plus MediaRecorder.
 * No libraries. One utterance = from the first voiced frame until ~800 ms of silence by default (VOICE_LIMITS.silenceMs, NEXT_PUBLIC_FL_VAD_SILENCE_MS 400-1500; measured in evals/results/published/voice/vad_silence_*.json) (min 0.4 s of voice, max 12 s).
 * Audio stays in memory as one small Blob that is handed to the caller and dropped; nothing is stored or logged.
 *
 * The threshold adapts to the room: it sits a fixed factor above a slowly tracked noise floor, so a fan or a TV
 * in the background does not keep it "speaking".
 */
import { VOICE_LIMITS } from "./voice";

const FRAME_MS = 30;
const MIN_THRESHOLD = 0.02;
const NOISE_FACTOR = 3;
const FLOOR_ALPHA = 0.05;

export interface Listener {
  stop: () => void;
  /** While paused (checking, speaking) nothing is captured: the assistant must not hear itself. */
  pause: () => void;
  resume: () => void;
  /** Starts capturing now, even before anyone is loud enough (noisy room; the Space key). */
  force: () => void;
}

export interface ListenerEvents {
  onUtterance: (audio: Blob, voicedMs: number) => void;
  /** True while a voice is being captured: drives the "listening" pulse. */
  onVoice?: (active: boolean) => void;
  /** Input level 0..1, about every 90 ms, for the on-screen meter. */
  onLevel?: (level: number) => void;
}

/**
 * Containers the API accepts, best first: webm/opus (Chrome, Firefox, Android), ogg/opus, then MP4/AAC, which is the
 * only thing iOS Safari's MediaRecorder produces (wav is not recordable natively).
 */
export const RECORDER_TYPES: readonly string[] = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "audio/aac",
];

/** The first of RECORDER_TYPES the browser can record (`supported` is a test seam for MediaRecorder.isTypeSupported). */
export function pickMimeType(supported?: (type: string) => boolean): string | null {
  const test = supported ?? (typeof MediaRecorder === "undefined" ? null : (t: string) => MediaRecorder.isTypeSupported(t));
  if (!test) return null;
  for (const type of RECORDER_TYPES) {
    try {
      if (test(type)) return type;
    } catch {
      /* some engines throw on unknown types: try the next */
    }
  }
  return null;
}

export function voiceSupported(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined" && pickMimeType() !== null && (typeof AudioContext !== "undefined" || "webkitAudioContext" in window);
}

export function startListener(stream: MediaStream, events: ListenerEvents): Listener {
  const Ctx: typeof AudioContext = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const mime = pickMimeType() ?? "audio/webm";

  let floor = 0.005;
  let paused = false;
  let stopped = false;
  let recorder: MediaRecorder | null = null;
  let chunks: Blob[] = [];
  let startedAt = 0;
  let lastVoiceAt = 0;
  let voicedFrames = 0;
  let levelAt = 0;

  const rms = (): number => {
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += (samples[i] ?? 0) * (samples[i] ?? 0);
    return Math.sqrt(sum / samples.length);
  };

  const begin = (now: number) => {
    chunks = [];
    voicedFrames = 0;
    startedAt = now;
    lastVoiceAt = now;
    try {
      recorder = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 32_000 });
    } catch {
      recorder = null;
      return;
    }
    recorder.addEventListener("dataavailable", (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    });
    recorder.start(250);
    events.onVoice?.(true);
  };

  const finish = (discard: boolean) => {
    const rec = recorder;
    recorder = null;
    events.onVoice?.(false);
    if (!rec) return;
    const voicedMs = voicedFrames * FRAME_MS;
    rec.addEventListener(
      "stop",
      () => {
        const blob = new Blob(chunks, { type: mime });
        chunks = [];
        if (!discard && !stopped && voicedMs >= VOICE_LIMITS.minMs && blob.size > 0 && blob.size <= VOICE_LIMITS.maxBytes) events.onUtterance(blob, voicedMs);
      },
      { once: true },
    );
    try {
      rec.stop();
    } catch {
      /* already inactive */
    }
  };

  const tick = () => {
    if (stopped) return;
    const now = performance.now();
    const level = rms();
    if (events.onLevel && now - levelAt >= 90) {
      levelAt = now;
      events.onLevel(paused ? 0 : Math.min(1, level * 6));
    }
    if (paused) {
      if (recorder) finish(true);
      return;
    }
    const threshold = Math.max(MIN_THRESHOLD, floor * NOISE_FACTOR);
    const voiced = level > threshold;
    if (!recorder) {
      if (voiced) begin(now);
      else floor = floor * (1 - FLOOR_ALPHA) + level * FLOOR_ALPHA;
      if (recorder && voiced) voicedFrames += 1;
      return;
    }
    if (voiced) {
      lastVoiceAt = now;
      voicedFrames += 1;
    }
    if (now - lastVoiceAt >= VOICE_LIMITS.silenceMs || now - startedAt >= VOICE_LIMITS.maxMs) finish(false);
  };

  const timer = window.setInterval(tick, FRAME_MS);
  if (ctx.state === "suspended") void ctx.resume().catch(() => undefined);

  return {
    force: () => {
      if (paused || stopped || recorder) return;
      const now = performance.now();
      begin(now);
      // Two seconds of grace to start talking before the silence rule can end the capture.
      lastVoiceAt = now + 2000;
      voicedFrames = Math.ceil(VOICE_LIMITS.minMs / FRAME_MS);
    },
    pause: () => {
      paused = true;
    },
    resume: () => {
      paused = false;
    },
    stop: () => {
      if (stopped) return;
      stopped = true;
      window.clearInterval(timer);
      if (recorder) finish(true);
      source.disconnect();
      void ctx.close().catch(() => undefined);
      stream.getTracks().forEach((t) => t.stop());
    },
  };
}
