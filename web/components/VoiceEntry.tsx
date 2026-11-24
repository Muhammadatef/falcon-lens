"use client";

import Link from "next/link";
import { voiceText } from "@/lib/i18n-voice";
import { usePrefs } from "@/lib/prefs";
import { Icon } from "./Icon";

/** Big, simple entry to /voice on Home. It only navigates: the microphone is requested on /voice, after one tap. */
export function VoiceEntry() {
  const { lang } = usePrefs();
  return (
    <section className="wrap voice-entry" aria-labelledby="voice-entry-h" data-testid="voice-entry">
      <div className="card voice-entry-card">
        <Icon name="mic" size={44} />
        <div>
          <h2 id="voice-entry-h" className="h3">
            {voiceText(lang, "voice.entry.h")} <span className="voice-preview">{voiceText(lang, "voice.preview")}</span>
          </h2>
          <p>{voiceText(lang, "voice.entry.p")}</p>
        </div>
        <Link className="btn btn--primary voice-big" href="/voice" data-testid="voice-entry-cta">
          {voiceText(lang, "voice.entry.cta")}
        </Link>
      </div>
    </section>
  );
}
