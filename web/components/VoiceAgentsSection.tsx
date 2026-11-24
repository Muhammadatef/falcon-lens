import { existsSync } from "node:fs";
import { join } from "node:path";
import Link from "next/link";
import type { Capabilities } from "@/lib/capabilities";
import type { Lang } from "@/lib/contracts";
import { CapBadge } from "./CapBadge";
import { VoiceDoc } from "./docs/VoiceDoc";

/** Languages whose pre-generated narration clips are available to this server (read from the files, never typed). */
function clipLanguages(): { en: boolean; ar: boolean } {
  // The clip route serves the private folder first (FL_VOICE_CLIPS_DIR), then the committed files.
  const roots = [process.env.FL_VOICE_CLIPS_DIR ?? "/data/private/voice/clips", join(process.cwd(), "public", "voice")];
  const has = (dir: string) => roots.some((r) => existsSync(join(r, dir, "manifest.json")));
  return { en: has("en"), ar: has("ar_ae") };
}

const TEXT = {
  en: {
    title: "Voice assistant | المساعد الصوتي",
    biz: "Say “Hey Falcon, check my messages”. The assistant reads the messages you copied, gives each one to Baseer (the Investigator), then hands the results to Dir' (the Sentinel), and tells you aloud what it found. Your voice is understood on our own machine: the audio is dropped after recognition and what you said is never stored.",
    privacy: "Privacy: audio is decoded in memory and discarded; the transcript goes back to your browser only. The trace span voice.utterance carries the engine, language, wake flag, intent and duration, never the words.",
    clips: (l: { en: boolean; ar: boolean }) =>
      l.en && l.ar ? "Pre-generated clips ship for English and Arabic." : l.en ? "Pre-generated clips ship for English; Arabic is read by the browser’s own voice until Arabic clips are added." : "No pre-generated clips are bundled in this build; the browser’s own voice reads every line.",
    open: "Try it",
  },
  ar: {
    title: "المساعد الصوتي | Voice assistant",
    biz: "قل «يا صقر، افحص رسائلي». يقرأ المساعد الرسائل التي نسختها، ويسلّم كل رسالة إلى «بصير»، المحقّق، ثم يحيل النتائج إلى «درع»، الحارس، ويخبرك بصوت مسموع بما وجده. يُفهم كلامك على جهازنا نفسه: يُتخلص من التسجيل بعد التعرف عليه ولا يُحفظ ما قلته.",
    privacy: "الخصوصية: يُفك ترميز الصوت في الذاكرة ويُتلف، ولا يعود النص المفرَّغ إلا إلى متصفحك. يحمل مسار التتبع voice.utterance المحرك واللغة وعلامة التنبيه والنية والمدة فقط، ولا يحمل الكلمات.",
    clips: (l: { en: boolean; ar: boolean }) =>
      l.en && l.ar ? "المقاطع المولَّدة مسبقاً متوفرة بالإنجليزية والعربية." : l.en ? "المقاطع المولَّدة مسبقاً متوفرة بالإنجليزية؛ ويقرأ صوتُ المتصفح العربيةَ إلى أن تُضاف مقاطع عربية." : "لا مقاطع مولَّدة مسبقاً في هذا الإصدار؛ يقرأ صوت المتصفح كل سطر.",
    open: "جرّبه",
  },
} as const;

/** Voice assistant block for /agents (business wording) and /docs/agents (technical flow). The badge follows the `voice_assistant` capability flag. */
export function VoiceAgentsSection({ lang, caps, view }: { lang: Lang; caps: Capabilities; view: "biz" | "tech" }) {
  const t = TEXT[lang];
  return (
    <section className="card" id={view === "tech" ? "voice" : undefined} aria-labelledby={`voice-${view}-h`} data-testid={`agents-voice-${view}`}>
      <div className="sec-head">
        <h2 id={`voice-${view}-h`}>
          {t.title} <CapBadge live={caps.voice_assistant} lang={lang} />
        </h2>
      </div>
      {view === "biz" ? <p>{t.biz}</p> : <VoiceDoc lang={lang} />}
      {view === "tech" ? <p className="muted">{t.clips(clipLanguages())}</p> : null}
      <p className="muted">{t.privacy}</p>
      {view === "biz" ? <p><Link className="btn" href="/voice">{t.open}</Link></p> : null}
    </section>
  );
}
