"use client";

import { useEffect, useState } from "react";

/** Presenter mode (projector layout): `?stage=1` or the toggle. It only sets `data-stage` on <html>; all the work is CSS (voice-stage.css). */
export function VoiceStageToggle({ onLabel, offLabel }: { onLabel: string; offLabel: string }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("stage") === "1") setOn(true);
    return () => document.documentElement.removeAttribute("data-stage");
  }, []);
  useEffect(() => {
    if (on) document.documentElement.setAttribute("data-stage", "1");
    else document.documentElement.removeAttribute("data-stage");
  }, [on]);
  return (
    <button type="button" className="btn btn--sm voice-stage-toggle" data-testid="voice-presenter" aria-pressed={on} onClick={() => setOn((v) => !v)}>
      {on ? offLabel : onLabel}
    </button>
  );
}

/** Keeps the newest live step in view inside the steps panel (the panel scrolls, the page does not). Wide layouts only. */
export function StageFollow({ trigger }: { trigger: number }) {
  useEffect(() => {
    if (!window.matchMedia("(min-width: 1000px) and (min-height: 560px)").matches) return;
    const box = document.querySelector<HTMLElement>(".voice-steps-scroll");
    if (!box) return;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    box.scrollTo({ top: box.scrollHeight, behavior: calm ? "auto" : "smooth" });
  }, [trigger]);
  return null;
}
