"use client";

import { useEffect, useState } from "react";
import type { Lang } from "@/lib/contracts";
import { voiceText } from "@/lib/i18n-voice";
import { STAGE_BUDGET_MS, seconds, type Stage, type TierRow } from "@/lib/voice-progress";

/** Live progress of the current voice request: what happened, what is happening now, how long each part took. */
export function VoiceProgress({ stages, tiers, lang, total, offline }: { stages: readonly Stage[]; tiers: readonly TierRow[]; lang: Lang; total: number | null; offline: boolean }) {
  const running = stages.some((s) => s.status === "active");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(t);
  }, [running]);
  if (!stages.length && !offline) return null;
  const t = (key: Parameters<typeof voiceText>[1], vars?: Record<string, string>) => voiceText(lang, key, vars);
  const label = (s: Stage) => t(s.id === "heard" ? "voice.prog.heard" : s.id === "understand" ? "voice.prog.understand" : s.id === "investigate" ? "voice.prog.investigate" : s.id === "link" ? "voice.prog.link" : s.id === "reply" ? "voice.prog.reply" : "voice.prog.answer");
  return (
    <section className="card voice-progress" aria-labelledby="voice-prog-h" data-testid="voice-progress" lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <h2 id="voice-prog-h" className="h3">{t("voice.prog.h")}</h2>
      <ol className="voice-stages">
        {stages.map((s) => {
          const ms = s.status === "active" ? now - s.startedAt : (s.ms ?? 0);
          const slow = s.status === "active" && ms > STAGE_BUDGET_MS[s.id];
          return (
            <li key={s.id} className="voice-stage" data-testid="voice-stage" data-stage={s.id} data-status={s.status}>
              <span className="voice-stage-mark" aria-hidden="true">{s.status === "done" ? <svg className="voice-tick" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" focusable="false"><path d="M5 12.5 10 17.5 19 7" /></svg> : <span className="voice-spin" />}</span>
              <span className="voice-stage-body">
                <span className="voice-stage-label">{label(s)}</span>
                {s.detail ? <span className="voice-stage-detail" data-testid="voice-stage-detail">{s.detail}</span> : null}
                {slow ? <span className="voice-stage-slow" data-testid="voice-still" role="status">{t("voice.prog.still")}</span> : null}
                {s.id === "investigate" && tiers.length ? (
                  <ul className="voice-tiers">
                    {tiers.map((r) => (
                      <li key={r.tier} data-testid="voice-tier" data-tier={r.tier} data-status={r.status}>
                        <span className="voice-tier-name">{t(r.tier === "T0" ? "voice.prog.t0" : r.tier === "T1" ? (r.step === "lookalike" ? "voice.prog.t1.url" : "voice.prog.t1.message") : r.tier === "T2" ? "voice.prog.t2" : "voice.prog.t3")}</span>
                        <span className="voice-tier-note">{r.status === "skipped" ? t("voice.prog.skipped") : (r.found ?? t("voice.prog.nothing"))}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </span>
              <span className="voice-stage-time" data-testid="voice-stage-time">{seconds(ms)} s</span>
            </li>
          );
        })}
      </ol>
      {total !== null ? <p className="voice-elapsed" data-testid="voice-elapsed">{t("voice.prog.checked", { s: seconds(total) })}</p> : null}
      {offline ? <p className="paste-error" role="alert" data-testid="voice-offline">{t("voice.prog.offline")}</p> : null}
    </section>
  );
}
