"use client";

import Link from "next/link";
import { TIERS, type InputType } from "@/lib/contracts";
import { usePrefs } from "@/lib/prefs";
import { useCheck } from "@/lib/use-check";
import { lensStateFor } from "@/lib/verdict-stream";
import { CheckBox } from "./CheckBox";
import { DemoRibbon } from "./Chrome";
import { Icon, type IconName } from "./Icon";
import { Lens } from "./Lens";
import { Result } from "./Result";

const HOW_ICONS: Record<(typeof TIERS)[number], IconName> = { T0: "list", T1: "url", T2: "box", T3: "spark" };

export interface CheckExperienceProps {
  demo: boolean;
  initialId: string | null;
  initialText: string;
  shareFailed: boolean;
  pendingKinds: readonly InputType[];
  investigatorLive: boolean;
}

export function CheckExperience({ demo, initialId, initialText, shareFailed, pendingKinds, investigatorLive }: CheckExperienceProps) {
  const { t } = usePrefs();
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
              <span className="eyebrow">{t("hero.eyebrow")}</span>
              <h1>{t("hero.title")}</h1>
              <p className="hero-sub">{t("hero.sub")}</p>

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
            </div>
            <div className="lens-stage" data-state={lensStateFor(state.phase)}>
              <Lens state={lensStateFor(state.phase)} verdict={finalVerdict} tiers={state.tiers} />
            </div>
          </div>
        </div>

        {showResult ? <Result state={state} onReset={reset} /> : null}

        <section id="how" aria-labelledby="how-title">
          <div className="wrap">
            <div className="sec-head">
              <h2 id="how-title">{t("how.title")}</h2>
            </div>
            <p className="sec-sub">{t("how.sub")}</p>
            <div className="how-grid">
              {TIERS.map((tier) => (
                <div className="card how-card" key={tier}>
                  <span className="code">{tier}</span>
                  <h3>
                    <Icon name={HOW_ICONS[tier]} size={22} />
                    {t(`tier.${tier}`)}
                  </h3>
                  <p>{t(`how.${tier}`)}</p>
                  {tier === "T3" ? <p><span className="cap" data-live={investigatorLive ? "true" : "false"}><i aria-hidden="true" />{t(investigatorLive ? "cap.live" : "cap.progress")}</span></p> : null}
                </div>
              ))}
            </div>
            <p className="how-foot">
              <Icon name="scale" size={22} />
              <span>{t("how.foot")}</span>
            </p>
            <p className="how-more"><Link href="/how-it-works">{t("nav.how")}</Link></p>
          </div>
        </section>
      </main>
    </>
  );
}
