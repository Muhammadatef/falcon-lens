import type { Metadata } from "next";
import { Icon } from "@/components/Icon";
import { pageMetadata } from "@/lib/meta";
import { AUTH } from "@/lib/page-content";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: AUTH[lang].title, description: AUTH[lang].lead });
}

export default async function AuthoritiesPage() {
  const lang = await serverLang();
  const c = AUTH[lang];
  return (
    <main id="main" className="page">
      <div className="wrap">
        <h1 className="page-title">{c.title}</h1>
        <p className="page-lead">{c.lead}</p>

        <p className="card callout" role="note" data-testid="not-connected">
          <Icon name="hand" size={24} />
          <span><b>{c.status}</b></span>
        </p>

        <section aria-labelledby="surf-h">
          <div className="sec-head"><h2 id="surf-h">{c.surfacesTitle}</h2></div>
          <div className="tbl-wrap" tabIndex={0} role="region" aria-labelledby="surf-h">
            <table className="tbl">
              <thead>
                <tr>{c.cols.map((h) => <th scope="col" key={h}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {c.rows.map((r) => (
                  <tr key={r.name}>
                    <th scope="row">{r.name}</th>
                    <td><code>{r.entry}</code></td>
                    <td>{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
