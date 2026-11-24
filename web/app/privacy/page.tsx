import type { Metadata } from "next";
import { Icon } from "@/components/Icon";
import { pageMetadata } from "@/lib/meta";
import { PRIVACY } from "@/lib/page-content";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: PRIVACY[lang].title, description: PRIVACY[lang].lead });
}

export default async function PrivacyPage() {
  const lang = await serverLang();
  const c = PRIVACY[lang];
  return (
    <main id="main" className="page">
      <div className="wrap">
        <h1 className="page-title">{c.title}</h1>
        <p className="page-lead">{c.lead}</p>
        <div className="prose prose--grid">
          {c.sections.map((s, i) => (
            <section key={s.title} aria-labelledby={`p-${i}`}>
              <h2 id={`p-${i}`}>{s.title}</h2>
              {s.body?.map((p) => <p key={p}>{p}</p>)}
              {s.list ? <ul>{s.list.map((li) => <li key={li}>{li}</li>)}</ul> : null}
            </section>
          ))}
        </div>
        <p className="card callout" role="note">
          <Icon name="scale" size={24} />
          <span>{c.note}</span>
        </p>
      </div>
    </main>
  );
}
