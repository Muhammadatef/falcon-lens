import type { Metadata } from "next";
import { VoiceAssistant } from "@/components/VoiceAssistant";
import { voiceText } from "@/lib/i18n-voice";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";
import { VoiceStageToggle } from "@/components/VoiceStage";
import "./voice.css";
import "./voice-stage.css";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: voiceText(lang, "voice.title"), description: voiceText(lang, "voice.lead") });
}

/** Hands-free "Hey Falcon" mode. The microphone is allowed on this page only (proxy.ts Permissions-Policy). */
export default async function VoicePage() {
  const lang = await serverLang();
  return (
    <main id="main" className="page voice-page">
      <div className="wrap">
        <div className="voice-head">
        <h1 className="page-title">
          {voiceText(lang, "voice.title")} <span className="voice-preview" data-testid="voice-preview">{voiceText(lang, "voice.preview")}</span>
        </h1>
        <VoiceStageToggle onLabel={voiceText(lang, "voice.stage.on")} offLabel={voiceText(lang, "voice.stage.off")} />
        </div>
        <p className="page-lead">{voiceText(lang, "voice.lead")}</p>
        <VoiceAssistant />
      </div>
    </main>
  );
}
