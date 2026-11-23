import type { Metadata } from "next";
import Link from "next/link";
import { Icon, type IconName } from "@/components/Icon";
import { TIERS } from "@/lib/contracts";
import { translate, type MessageKey } from "@/lib/i18n";
import { pageMetadata } from "@/lib/meta";
import { HOW } from "@/lib/page-content";
import { serverLang } from "@/lib/server-lang";

const TIER_ICONS: Record<(typeof TIERS)[number], IconName> = { T0: "list", T1: "url", T2: "box", T3: "spark" };

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: HOW[lang].title, description: HOW[lang].lead });
}

export default async function HowItWorksPage() {
  const lang = await serverLang();
  const c = HOW[lang];
  const t = (key: MessageKey) => translate(lang, key);
  return (
    <main id="main" className="page">
      <div className="wrap">
        <h1 className="page-title">{c.title}</h1>
        <p className="page-lead">{c.lead}</p>

        <section aria-labelledby="steps-h">
          <div className="sec-head"><h2 id="steps-h">{c.stepsTitle}</h2></div>
          <ol className="steps4">
            {c.steps.map((s) => (
              <li className="card" key={s.title}>
                <div>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="figure figure--tall">
            <img src="/images/how-it-works.svg" alt={c.figureAlt} width={720} height={1880} loading="lazy" decoding="async" />
          </div>
        </section>

        <section aria-labelledby="layers-h">
          <div className="sec-head"><h2 id="layers-h">{c.layersTitle}</h2></div>
          <p className="sec-sub">{c.layersLead}</p>
          <div className="how-grid">
            {TIERS.map((tier) => (
              <div className="card how-card" key={tier}>
                <span className="code">{tier}</span>
                <h3>
                  <Icon name={TIER_ICONS[tier]} size={22} />
                  {t(`tier.${tier}`)}
                </h3>
                <p>{t(`how.${tier}`)}</p>
              </div>
            ))}
          </div>
        </section>

        <section aria-labelledby="agents-h">
          <div className="sec-head"><h2 id="agents-h">{c.agentsTitle}</h2></div>
          <p className="sec-sub">{c.agentsLead}</p>
          <div className="agents">
            {[c.investigator, c.sentinel].map((a, i) => (
              <article className="card agent" key={a.title}>
                <h3>
                  <Icon name={i === 0 ? "eye" : "flag"} size={24} />
                  {a.title}
                </h3>
                <p className="muted">{a.role}</p>
                <ul className="prose">
                  {a.list.map((li) => <li key={li}>{li}</li>)}
                </ul>
              </article>
            ))}
          </div>
          <div className="figure figure--tall">
            <img src="/images/ai-agents.svg" alt={c.agentsAlt} width={720} height={1270} loading="lazy" decoding="async" />
          </div>
          <p className="how-foot">
            <Icon name="scale" size={22} />
            <span>{c.principle}</span>
          </p>
        </section>

        <p><Link className="btn btn--primary" href="/">{c.cta}</Link></p>
      </div>
    </main>
  );
}
