/**
 * Plays the pre-generated voice clips (tools/voice_clips) back to back, gapless, no runtime TTS.
 * Clips come from /voice/<lang>/manifest.json; an id that is not in the manifest (or a manifest that
 * fails to load) falls back to speechSynthesis using the clip's text. Never overlaps: a new play()
 * cancels the one in flight.
 */

export type VoiceLang = "ar_ae" | "en";

export interface VoiceManifestEntry {
  id: string;
  file: string;
  text: string;
  ms: number;
  engine: string;
  voice: string;
}

export interface VoicePlayer {
  /** Plays the ids in order with a short gap; resolves when done (or when stopped). */
  play(ids: string[]): Promise<void>;
  /** Stops immediately, including speech synthesis. Pending play() promises resolve. */
  stop(): void;
  /** True when the id has a pre-generated clip. */
  has(id: string): boolean;
  /** Resolves once the manifest is loaded and every clip is decoded (or failed). */
  ready: Promise<void>;
}

export interface VoicePlayerOptions {
  lang: VoiceLang;
  /** Gap between clips in ms (default 120). */
  gapMs?: number;
  /** Text for an id that is not in the manifest, used for the speechSynthesis fallback. */
  fallbackText?: (id: string) => string | undefined;
  /** Test seams. */
  fetchImpl?: typeof fetch;
  audioContext?: () => AudioContext;
  synth?: SpeechSynthesis | null;
  baseUrl?: string;
}

export function createVoicePlayer(opts: VoicePlayerOptions): VoicePlayer {
  const gap = opts.gapMs ?? 120;
  const base = opts.baseUrl ?? `/voice/${opts.lang}`;
  const doFetch = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a));
  const entries = new Map<string, VoiceManifestEntry>();
  const buffers = new Map<string, AudioBuffer>();
  let ctx: AudioContext | null = null;
  let token = 0; // bumps on every play()/stop(); a run that sees a stale token exits
  let current: AudioBufferSourceNode | null = null;
  let wake: (() => void) | null = null;

  const getCtx = (): AudioContext | null => {
    if (ctx) return ctx;
    try {
      ctx = opts.audioContext ? opts.audioContext() : new AudioContext();
    } catch {
      ctx = null;
    }
    return ctx;
  };
  const synth = (): SpeechSynthesis | null =>
    opts.synth !== undefined ? opts.synth : typeof speechSynthesis === "undefined" ? null : speechSynthesis;

  const ready = (async () => {
    try {
      const res = await doFetch(`${base}/manifest.json`);
      if (!res.ok) return;
      const list = (await res.json()) as VoiceManifestEntry[];
      for (const e of list) entries.set(e.id, e);
    } catch {
      return; // no manifest: every id falls back to speech synthesis
    }
    const c = getCtx();
    if (!c) return;
    await Promise.all(
      [...entries.values()].map(async (e) => {
        try {
          const r = await doFetch(`${base}/${e.file}`);
          if (!r.ok) return;
          buffers.set(e.id, await c.decodeAudioData(await r.arrayBuffer()));
        } catch {
          /* clip stays missing: falls back to speech */
        }
      }),
    );
  })();

  const cancelWait = () => {
    const w = wake;
    wake = null;
    w?.();
  };

  // Each pending step owns its `wake`; a late event from a cancelled step only resolves its own promise
  // and never touches the shared `wake`/`current` of the run that replaced it.
  const waitOrWake = (ms: number) =>
    new Promise<void>((resolve) => {
      const mine = () => {
        clearTimeout(t);
        resolve();
      };
      const t = setTimeout(() => {
        if (wake === mine) wake = null;
        resolve();
      }, ms);
      wake = mine;
    });

  function playBuffer(buf: AudioBuffer, my: number): Promise<void> {
    const c = ctx;
    if (!c) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const src = c.createBufferSource();
      src.buffer = buf;
      src.connect(c.destination);
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        if (current === src) current = null;
        if (wake === mine) wake = null;
        resolve();
      };
      const mine = () => {
        src.onended = null;
        if (current === src) {
          try {
            src.stop();
          } catch {
            /* already stopped */
          }
        }
        finish();
      };
      if (my !== token) return resolve();
      current = src;
      wake = mine;
      src.onended = finish;
      src.start();
    });
  }

  function speak(text: string, my: number): Promise<void> {
    const s = synth();
    if (!s || typeof SpeechSynthesisUtterance === "undefined" || my !== token) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = opts.lang === "en" ? "en-GB" : "ar-AE";
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        if (wake === mine) wake = null;
        resolve();
      };
      const mine = () => {
        u.onend = null;
        u.onerror = null;
        s.cancel();
        finish();
      };
      u.onend = finish;
      u.onerror = finish;
      wake = mine;
      s.speak(u);
    });
  }

  return {
    ready,
    has: (id) => buffers.has(id),
    stop() {
      token++;
      const src = current;
      current = null;
      if (src) {
        src.onended = null;
        try {
          src.stop();
        } catch {
          /* already stopped */
        }
      }
      cancelWait();
      synth()?.cancel();
    },
    async play(ids) {
      token++;
      const my = token;
      cancelWait();
      synth()?.cancel();
      await ready;
      const c = getCtx();
      if (c && c.state === "suspended") await c.resume().catch(() => undefined);
      for (let i = 0; i < ids.length; i++) {
        if (my !== token) return;
        const id = ids[i] as string;
        const buf = buffers.get(id);
        if (buf) await playBuffer(buf, my);
        else {
          const text = entries.get(id)?.text ?? opts.fallbackText?.(id);
          if (text) await speak(text, my);
        }
        if (my !== token) return;
        if (i < ids.length - 1) await waitOrWake(gap);
      }
    },
  };
}
