import type { Metadata } from "next";
import { VoiceAssistant } from "@/components/VoiceAssistant";
import { voiceText } from "@/lib/i18n-voice";
import { pageMetadata } from "@/lib/meta";
import { loadCapabilities } from "@/lib/capabilities";
import { flag } from "@/lib/cap-flag";
import { serverLang } from "@/lib/server-lang";
import "./voice.css";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: voiceText(lang, "voice.title"), description: voiceText(lang, "voice.lead") });
}

/** Hands-free "Hey Falcon" mode. The microphone is allowed on this page only (proxy.ts Permissions-Policy). */
export default async function VoicePage() {
  const lang = await serverLang();
  const preview = !flag(await loadCapabilities(), "voice_assistant");
  const other = lang === "ar" ? "en" : "ar";
  return (
    <main id="main" className="page">
      <div className="wrap">
        <header className="voice-head">
          <h1 className="page-title">
            <span>{voiceText(lang, "voice.title")}</span>
            <span className="voice-title-alt" lang={other} aria-hidden="true">| {voiceText(other, "voice.title")}</span>
            {preview ? <span className="voice-preview" data-testid="voice-preview">{voiceText(lang, "voice.preview")}</span> : null}
          </h1>
          <p className="page-lead">{voiceText(lang, "voice.lead")}</p>
        </header>
        <VoiceAssistant />
      </div>
    </main>
  );
}
