"use client";

import { FLOW_UI, type FlowLang } from "@/lib/arch-flow";

export type FlowStatus = "idle" | "playing" | "paused" | "done";

const GLYPH = {
  play: "M8 5.5v13l11-6.5z",
  pause: "M7 5h3.5v14H7zM13.500 5H17v14h-3.500z",
  replay: "M5 12a7 7 0 1 0 2.300-5.200M5 4.500v4h4",
  prev: "M14.500 6 8.500 12l6 6",
  next: "M9.500 6l6 6-6 6",
} as const;

function Glyph({ name, filled }: { name: keyof typeof GLYPH; filled?: boolean }) {
  return (
    <svg className="afc-glyph" data-dir={name === "prev" || name === "next" ? "true" : undefined} width="20" height="20" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth={filled ? 0 : 2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={GLYPH[name]} />
    </svg>
  );
}

/**
 * Player bar of an animated diagram: play or pause, replay, previous and next step, the step counter and the
 * caption of the current step (before the first step the caller passes a short hint instead). With reduced
 * motion the play button is not offered; the steps can still be read one by one.
 */
export function FlowControls({ lang, status, step, total, caption, reduced, onToggle, onReplay, onPrev, onNext, testid }: {
  lang: FlowLang;
  status: FlowStatus;
  step: number;
  total: number;
  caption: string;
  reduced: boolean;
  onToggle: () => void;
  onReplay: () => void;
  onPrev: () => void;
  onNext: () => void;
  testid: string;
}) {
  const ui = FLOW_UI[lang];
  const playing = status === "playing";
  return (
    <div className="afc" data-testid={`${testid}-bar`}>
      <div className="afc-btns" role="group" aria-label={ui.controls}>
        {reduced ? null : (
          <button type="button" className="afc-btn afc-btn--main" onClick={onToggle} aria-pressed={playing} data-testid={`${testid}-toggle`}>
            <Glyph name={playing ? "pause" : "play"} filled />
            <span>{playing ? ui.pause : ui.play}</span>
          </button>
        )}
        {reduced ? null : (
          <button type="button" className="afc-btn" onClick={onReplay} aria-label={ui.replay} title={ui.replay} data-testid={`${testid}-replay`}>
            <Glyph name="replay" />
          </button>
        )}
        <button type="button" className="afc-btn" onClick={onPrev} disabled={step <= 0} aria-label={ui.prev} title={ui.prev} data-testid={`${testid}-prev`}>
          <Glyph name="prev" />
        </button>
        <button type="button" className="afc-btn" onClick={onNext} disabled={step >= total - 1} aria-label={ui.next} title={ui.next} data-testid={`${testid}-next`}>
          <Glyph name="next" />
        </button>
      </div>
      <p className="afc-cap" data-testid={`${testid}-caption`}>
        {step >= 0 ? (
          <span className="afc-count" data-testid={`${testid}-count`}>
            {ui.step} <bdi>{step + 1}</bdi> {ui.of} <bdi>{total}</bdi>
          </span>
        ) : null}
        <span className="afc-text">{caption}</span>
      </p>
    </div>
  );
}
