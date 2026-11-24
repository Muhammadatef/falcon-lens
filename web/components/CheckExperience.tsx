"use client";

import type { InputType } from "@/lib/contracts";
import { usePrefs } from "@/lib/prefs";
import { useCheck } from "@/lib/use-check";
import { lensStateFor } from "@/lib/verdict-stream";
import { CheckBox } from "./CheckBox";
import { DemoRibbon } from "./Chrome";
import { AgentChip } from "./AgentChip";
import { HomeSections } from "./HomeSections";
import { VoiceEntry } from "./VoiceEntry";
import { Icon } from "./Icon";
import { Lens } from "./Lens";
import { Radar } from "./Radar";
import { Result } from "./Result";
import { SentinelTicker } from "./SentinelTicker";

export interface CheckExperienceProps {
  demo: boolean;
  initialId: string | null;
  initialText: string;
  shareFailed: boolean;
  pendingKinds: readonly InputType[];
  investigatorLive: boolean;
  sentinelLive: boolean;
}

export function CheckExperience({ demo, initialId, initialText, shareFailed, pendingKinds, investigatorLive, sentinelLive }: CheckExperienceProps) {
  const { t, lang } = usePrefs();
  const { state, start, playDemo, reset } = useCheck(initialId);
  const busy = state.phase === "submitting" || state.phase === "waiting" || state.phase === "streaming";
  const showResult = state.phase !== "idle";
  const finalVerdict = state.phase === "final" ? state.verdict?.verdict : null;

  return (
    <>
      {demo ? <DemoRibbon /> : null}
      <main id="main">
        <div className="hero wrap">
          <div className="hero-grid">
            <div>
              <span className="eyebrow">{t("home.eyebrow")}</span>
              <h1>{t("home.title")}</h1>
              <p className="hero-sub hero-sub--full">{t(sentinelLive ? "home.sub" : "home.sub.phone")}</p>
              <p className="hero-sub hero-sub--phone">{t("home.sub.phone")}</p>

              {shareFailed ? (
                <p className="paste-error" role="alert" data-testid="share-failed">
                  <Icon name="suspicious" size={20} />
                  <span>{t("share.failed")}</span>
                </p>
              ) : null}

              <CheckBox pending={pendingKinds} busy={busy} initialText={initialText} onSubmit={(input, preview) => void start(input, preview)} />

              {demo ? (
                <div className="demos" data-testid="demo-examples">
                  <span className="badge-demo">DEMO DATA</span>
                  <span className="muted">{t("demo.try")}</span>
                  <button className="btn btn--sm" type="button" data-testid="demo-danger" onClick={() => void playDemo("danger")}>{t("demo.danger")}</button>
                  <button className="btn btn--sm" type="button" data-testid="demo-nws" onClick={() => void playDemo("nws")}>{t("demo.nws")}</button>
                  <p className="small demos-note">{t("demo.note")}</p>
                </div>
              ) : null}

              <p className="promise">
                <Icon name="hand" size={20} />
                <span>{t("promise")}</span>
              </p>

              <div className="agent-chips" data-testid="agent-chips">
                <AgentChip agent="inv" lang={lang} aiLive={investigatorLive} sentinelLive={sentinelLive} variant="chip" />
                <AgentChip agent="sen" lang={lang} aiLive={investigatorLive} sentinelLive={sentinelLive} variant="chip" />
              </div>
            </div>
            <div className="duo">
              <div className="lens-stage" data-state={lensStateFor(state.phase)}>
                <Lens state={lensStateFor(state.phase)} verdict={finalVerdict} tiers={state.tiers} />
              </div>
              <div className="duo-radar" aria-hidden="true"><Radar /></div>
              <AgentChip agent="inv" lang={lang} aiLive={investigatorLive} sentinelLive={sentinelLive} variant="tag" />
              <AgentChip agent="sen" lang={lang} aiLive={investigatorLive} sentinelLive={sentinelLive} variant="tag" />
            </div>
          </div>
        </div>

        {showResult ? null : <VoiceEntry />}
        {showResult ? <Result state={state} onReset={reset} investigatorLive={investigatorLive} sentinelLive={sentinelLive} /> : null}

        <SentinelTicker demo={demo} sentinelLive={sentinelLive} />
        <HomeSections investigatorLive={investigatorLive} sentinelLive={sentinelLive} />
      </main>
    </>
  );
}
