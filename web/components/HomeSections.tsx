"use client";

import Link from "next/link";
import { usePrefs } from "@/lib/prefs";
import type { MessageKey } from "@/lib/i18n";
import { CapBadge } from "./CapBadge";
import { Icon, type IconName } from "./Icon";
import { LensGlyph } from "./AgentChip";
import { ProofStats } from "./ProofStats";
import { Radar } from "./Radar";

const OUT: { n: 1 | 2 | 3 | 4; icon: IconName }[] = [
  { n: 1, icon: "clock" },
  { n: 2, icon: "list" },
  { n: 3, icon: "flag" },
  { n: 4, icon: "hand" },
];

/** Home sections 4 to 7: outcomes, the two agents, proof, the authority message. Badges only from the flags passed in. */
export function HomeSections({ investigatorLive, sentinelLive }: { investigatorLive: boolean; sentinelLive: boolean }) {
  const { t, lang } = usePrefs();
  return (
    <>
      <section aria-labelledby="out-h" data-testid="outcomes">
        <div className="wrap">
          <div className="sec-head"><h2 id="out-h">{t("out.title")}</h2></div>
          <ul className="outcomes">
            {OUT.map(({ n, icon }) => (
              <li className="card outcome" key={n}>
                <Icon name={icon} size={28} />
                <h3>{t(`out.${n}.title` as MessageKey)}</h3>
                <p>{t(`out.${n}.text` as MessageKey)}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="meet-h" data-testid="meet">
        <div className="wrap">
          <div className="sec-head"><h2 id="meet-h">{t("meet.title")}</h2></div>
          <div className="meet">
            <article className="card meet-card" data-agent="inv" data-testid="meet-inv">
              <header>
                <span className="meet-glyph"><LensGlyph /></span>
                <div>
                  <span className="agent-chip-kind">{t("agent.kind")}</span>
                  <h3>{t("agent.inv.name")}</h3>
                  <p className="meet-role">{t("agent.inv.role")}</p>
                </div>
              </header>
              <p>{t("meet.inv.text")}</p>
              <p className="agent-chip-ai">
                <span>{t("agent.inv.aistep")}</span>
                <CapBadge live={investigatorLive} lang={lang} />
              </p>
            </article>
            <article className="card meet-card" data-agent="sen" data-testid="meet-sen">
              <header>
                <span className="meet-glyph"><Radar mini /></span>
                <div>
                  <span className="agent-chip-kind">{t("agent.kind")}</span>
                  <h3>{t("agent.sen.name")}</h3>
                  <p className="meet-role">{t("agent.sen.role")}</p>
                </div>
              </header>
              <p>{t("meet.sen.text")}</p>
              <p className="agent-chip-ai"><CapBadge live={sentinelLive} lang={lang} /></p>
            </article>
          </div>
          <p className="card principle">
            <Icon name="scale" size={26} />
            <b>{t("meet.principle")}</b>
          </p>
          <p className="how-more"><Link href="/agents">{t("meet.cta")}</Link></p>
        </div>
      </section>

      <section className="tint" aria-labelledby="proof-home-h" data-testid="proof-section">
        <div className="wrap">
          <ProofStats lang={lang} variant="home" />
        </div>
      </section>

      <section aria-labelledby="auth-band-h" data-testid="auth-band">
        <div className="wrap">
          <div className="auth-band">
            <Icon name="unplug" size={28} />
            <div>
              <h2 id="auth-band-h">{t("auth.band.title")}</h2>
              <p>{t("auth.band.text")}</p>
            </div>
            <Link className="btn" href="/authorities">{t("auth.band.cta")}</Link>
          </div>
        </div>
      </section>
    </>
  );
}
