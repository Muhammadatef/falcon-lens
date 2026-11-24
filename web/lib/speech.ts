/**
 * Spoken output through the browser's own speechSynthesis (no network, no third-party voice service).
 * Arabic needs an ar-* voice installed (macOS: Majed/Maged, Android: Google Arabic); when there is none the caller
 * shows the text on screen only. Long text is spoken sentence by sentence, because some engines stop after ~15 s.
 */
import type { Lang } from "./contracts";

const PREFERRED_AR = /majed|maged|tarik|laila|hoda|zariyah|maha|salma|naayf|hamed/i;

const synth = (): SpeechSynthesis | null => (typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null);

const norm = (l: string) => l.replace("_", "-").toLowerCase();

export function pickVoice(voices: readonly SpeechSynthesisVoice[], lang: Lang): SpeechSynthesisVoice | null {
  const mine = voices.filter((v) => norm(v.lang).startsWith(lang));
  if (!mine.length) return null;
  if (lang === "ar") return mine.find((v) => PREFERRED_AR.test(v.name)) ?? mine[0] ?? null;
  return mine.find((v) => norm(v.lang) === "en-gb") ?? mine.find((v) => v.localService) ?? mine[0] ?? null;
}

async function loadVoices(s: SpeechSynthesis): Promise<SpeechSynthesisVoice[]> {
  const now = s.getVoices();
  if (now.length) return now;
  await new Promise<void>((resolve) => {
    const done = () => {
      s.removeEventListener("voiceschanged", done);
      resolve();
    };
    s.addEventListener("voiceschanged", done);
    window.setTimeout(done, 1200);
  });
  return s.getVoices();
}

/** Can this device speak the language? (Arabic needs a real ar-* voice.) */
export async function canSpeak(lang: Lang): Promise<boolean> {
  const s = synth();
  if (!s) return false;
  const voices = await loadVoices(s);
  return lang === "en" ? true : pickVoice(voices, lang) !== null;
}

export const sentences = (text: string): string[] => text.split(/(?<=[.؟?!۔])\s+/u).map((x) => x.trim()).filter(Boolean);

/**
 * Speaks `text`; resolves when finished, cancelled, or when it cannot speak (returns whether it spoke).
 * `alive` lets the caller abort between sentences (Stop pressed).
 */
export async function speak(text: string, lang: Lang, alive: () => boolean): Promise<boolean> {
  const s = synth();
  if (!s || !text.trim()) return false;
  const voice = pickVoice(await loadVoices(s), lang);
  if (lang === "ar" && !voice) return false;
  for (const part of sentences(text)) {
    if (!alive()) return true;
    await new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(part);
      u.lang = voice?.lang ?? (lang === "ar" ? "ar-SA" : "en-GB");
      if (voice) u.voice = voice;
      u.rate = 0.92;
      u.pitch = 1;
      const guard = window.setTimeout(resolve, 20_000);
      const end = () => {
        window.clearTimeout(guard);
        resolve();
      };
      u.onend = end;
      u.onerror = end;
      s.speak(u);
    });
  }
  return true;
}

export function cancelSpeech(): void {
  synth()?.cancel();
}
