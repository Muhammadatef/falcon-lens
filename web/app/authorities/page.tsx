import type { Metadata } from "next";
import Link from "next/link";
import { CapBadge } from "@/components/CapBadge";
import { Icon } from "@/components/Icon";
import { flag } from "@/lib/cap-flag";
import { loadCapabilities } from "@/lib/capabilities";
import { dt } from "@/lib/i18n-docs";
import { pageMetadata } from "@/lib/meta";
import { AUTH } from "@/lib/page-content";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: AUTH[lang].title, description: AUTH[lang].lead });
}

const IFACES = [
  { name: "REST v1", cap: "rest_api" },
  { name: "MCP", cap: "mcp" },
  { name: "STIX 2.1", cap: "stix" },
] as const;

export default async function AuthoritiesPage() {
  const lang = await serverLang();
  const c = AUTH[lang];
  const caps = await loadCapabilities();
  return (
    <main id="main" className="page">
      <div className="wrap">
        <h1 className="page-title">{c.title}</h1>

        <p className="card callout" role="note" data-testid="not-connected">
          <Icon name="hand" size={24} />
          <span><b>{c.status}</b></span>
        </p>

        <p className="page-lead">{c.lead}</p>

        <section aria-labelledby="out-h">
          <div className="sec-head"><h2 id="out-h">{c.outcomesTitle}</h2></div>
          <ul className="outcomes" data-testid="outcomes">
            {c.outcomes.map((o) => (
              <li className="card" key={o.title}>
                <h3>{o.title}</h3>
                <p>{o.text}</p>
              </li>
            ))}
          </ul>
          <ul className="ifaces" aria-label={dt(lang, "ap.ifaces")} data-testid="ifaces">
            {IFACES.map((i) => (
              <li key={i.name}>
                <span dir="ltr">{i.name}</span> <CapBadge live={flag(caps, i.cap)} lang={lang} />
              </li>
            ))}
          </ul>
          <p><Link className="btn" href="/docs/integration">{dt(lang, "ap.ifaces.more")}</Link></p>
        </section>

        <div className="prose">
          {c.sections.map((s, i) => (
            <section key={s.title} aria-labelledby={`a-${i}`}>
              <h2 id={`a-${i}`}>{s.title}</h2>
              {s.body?.map((p) => <p key={p}>{p}</p>)}
              {s.list ? <ul>{s.list.map((li) => <li key={li}>{li}</li>)}</ul> : null}
            </section>
          ))}
        </div>

        <section className="prose" aria-labelledby="boundary-h">
          <h2 id="boundary-h">{c.boundaryTitle}</h2>
          <p>{c.boundaryIn}</p>
          <p>{c.boundaryOut}</p>
          <p className="muted">{c.docs}</p>
        </section>
      </div>
    </main>
  );
}
