import type { Metadata } from "next";
import Link from "next/link";
import { LensGlyph } from "@/components/AgentChip";
import { CapBadge } from "@/components/CapBadge";
import { Icon } from "@/components/Icon";
import { Radar } from "@/components/Radar";
import { ArchDiagram } from "@/components/arch/ArchDiagram";
import { at } from "@/lib/i18n-arch";
import { loadCapabilities } from "@/lib/capabilities";
import { translate, type MessageKey } from "@/lib/i18n";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: translate(lang, "agents.title"), description: translate(lang, "agents.lead") });
}

const STEPS = [1, 2, 3] as const;
const PROMISES = [1, 2, 3] as const;

/** How the two AI agents protect you, in plain words: no pattern or tool names here (those live in /docs/agents). */
export default async function AgentsPage() {
  const lang = await serverLang();
  const caps = await loadCapabilities();
  const t = (key: MessageKey) => translate(lang, key);
  return (
    <main id="main" className="page" data-testid="agents-page">
      <div className="wrap">
        <h1 className="page-title">{t("agents.title")}</h1>
        <p className="page-lead">{t("agents.lead")}</p>

        <div className="lanes">
          <section className="card lane" data-agent="inv" aria-labelledby="lane-inv-h" data-testid="lane-inv">
            <header>
              <span className="meet-glyph"><LensGlyph /></span>
              <div>
                <span className="agent-chip-kind">{t("agent.kind")}</span>
                <h2 id="lane-inv-h">{t("agent.inv.name")}</h2>
                <p className="lane-tag">{t("agents.inv.tag")}</p>
              </div>
            </header>
            <ol className="lane-steps" aria-label={t("agents.steps.label")}>
              {STEPS.map((n) => (
                <li key={n}>
                  <div>
                    <h3>
                      {t(`agents.inv.${n}.title` as MessageKey)}
                      {n === 2 ? <CapBadge live={caps.investigator} lang={lang} /> : null}
                    </h3>
                    <p>{t(`agents.inv.${n}.text` as MessageKey)}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section className="card lane" data-agent="sen" aria-labelledby="lane-sen-h" data-testid="lane-sen">
            <header>
              <span className="meet-glyph"><Radar mini /></span>
              <div>
                <span className="agent-chip-kind">{t("agent.kind")}</span>
                <h2 id="lane-sen-h">
                  {t("agent.sen.name")} <CapBadge live={caps.sentinel_agent} lang={lang} />
                </h2>
                <p className="lane-tag">{t("agents.sen.tag")}</p>
              </div>
            </header>
            <ol className="lane-steps" aria-label={t("agents.steps.label")}>
              {STEPS.map((n) => (
                <li key={n}>
                  <div>
                    <h3>{t(`agents.sen.${n}.title` as MessageKey)}</h3>
                    <p>{t(`agents.sen.${n}.text` as MessageKey)}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>

        <p className="handoff" data-testid="handoff">
          <Icon name="refresh" size={24} />
          <span>{t("agents.handoff")}</span>
        </p>

        <section aria-labelledby="biz-arch-h" data-testid="agents-arch">
          <div className="sec-head"><h2 id="biz-arch-h">{at(lang, "arch.biz.title")}</h2></div>
          <p className="muted">{at(lang, "arch.biz.lead")}</p>
          <ArchDiagram lang={lang} caps={caps as unknown as Record<string, boolean>} view="biz" />
        </section>

        <section aria-labelledby="promises-h">
          <div className="sec-head"><h2 id="promises-h">{t("agents.promises.title")}</h2></div>
          <ul className="promises">
            {PROMISES.map((n) => (
              <li className="card" key={n}>
                <h3>{t(`agents.p${n}.title` as MessageKey)}</h3>
                <p>{t(`agents.p${n}.text` as MessageKey)}</p>
              </li>
            ))}
          </ul>
        </section>

        <div className="cta-row">
          <Link className="btn btn--primary" href="/">{t("agents.cta")}</Link>
          <Link className="btn" href="/docs/agents" data-testid="agents-docs-link">{t("agents.docs")}</Link>
        </div>
      </div>
    </main>
  );
}
