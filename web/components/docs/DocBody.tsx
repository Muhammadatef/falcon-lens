import { CapBadge } from "@/components/CapBadge";
import { Icon } from "@/components/Icon";
import { flag } from "@/lib/cap-flag";
import type { Capabilities } from "@/lib/capabilities";
import type { Lang } from "@/lib/contracts";
import { bundledProvenance, bundledThresholds, fmtThreshold } from "@/lib/docs-data";
import type { DocPage, DocSection } from "@/lib/docs-content";
import { dt } from "@/lib/i18n-docs";

/** Public repository the source documents live in (a constant, never built from data). */
const REPO_BLOB = "https://github.com/Muhammadatef/falcon-lens/blob/main/";

function Thresholds({ lang }: { lang: Lang }) {
  const t = bundledThresholds();
  const prov = bundledProvenance();
  if (!t || !prov) return <p className="muted" data-testid="thresholds-pending">{dt(lang, "docs.thr.none")}</p>;
  const rows: [string, string][] = [
    [dt(lang, "docs.thr.low"), fmtThreshold(t.tauLow)],
    [dt(lang, "docs.thr.high"), fmtThreshold(t.tauHigh)],
    ...(t.epsLow !== null ? ([[dt(lang, "docs.thr.elow"), fmtThreshold(t.epsLow)]] as [string, string][]) : []),
    ...(t.epsHigh !== null ? ([[dt(lang, "docs.thr.ehigh"), fmtThreshold(t.epsHigh)]] as [string, string][]) : []),
  ];
  return (
    <div className="card docs-data" data-testid="thresholds">
      <h3 className="h3">{dt(lang, "docs.thr.title")}</h3>
      <p className="small">{dt(lang, "docs.thr.from")} <code className="mono" translate="no" dir="ltr">{prov.artifact}</code></p>
      <dl className="kv-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className="mono" dir="ltr">{v}</dd>
          </div>
        ))}
        {t.fitSource ? (
          <div>
            <dt>{dt(lang, "docs.thr.src")}</dt>
            <dd dir="auto">{t.fitSource}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

function Provenance({ lang }: { lang: Lang }) {
  const p = bundledProvenance();
  if (!p) return <p className="muted" data-testid="provenance-pending">{dt(lang, "docs.thr.none")}</p>;
  const rows: [string, string | null][] = [
    [dt(lang, "docs.prov.artifact"), p.artifact],
    [dt(lang, "docs.prov.date"), p.createdAt],
    [dt(lang, "docs.prov.dataset"), p.datasetHash],
    [dt(lang, "docs.prov.sha"), p.gitSha],
    [dt(lang, "docs.prov.scope"), p.scope],
  ];
  return (
    <div className="card docs-data" data-testid="provenance">
      <dl className="kv-list">
        {rows.filter((r): r is [string, string] => r[1] !== null).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className="mono" dir="ltr" translate="no">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Section({ s, lang, caps }: { s: DocSection; lang: Lang; caps: Capabilities }) {
  return (
    <section className="docs-sec" aria-labelledby={`d-${s.id}`} id={s.id}>
      <div className="sec-head">
        <h2 id={`d-${s.id}`}>{s.title}</h2>
        {s.cap ? <CapBadge live={flag(caps, s.cap)} lang={lang} /> : null}
      </div>
      <div className="prose">
        {s.body?.map((p) => <p key={p}>{p}</p>)}
        {s.list ? <ul>{s.list.map((li) => <li key={li}>{li}</li>)}</ul> : null}
      </div>
      {s.cards ? (
        <div className="how-grid docs-tiers" data-testid="tier-cards">
          {s.cards.map((c) => (
            <div className="card how-card" key={c.tag}>
              <span className="code">{c.tag}</span>
              <h3>{c.title}</h3>
              <p>{c.body}</p>
              {c.cap ? <p><CapBadge live={flag(caps, c.cap)} lang={lang} /></p> : null}
            </div>
          ))}
        </div>
      ) : null}
      {s.table ? (
        <div className="tbl-wrap" tabIndex={0} role="group" aria-labelledby={`d-${s.id}`}>
          <table className="tbl">
            <thead>
              <tr>{s.table.cols.map((h) => <th scope="col" key={h}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {s.table.rows.map((r, i) => (
                <tr key={r[0]}>
                  <th scope="row">
                    {r[0]}
                    {s.table?.rowCaps?.[i] ? <> <CapBadge live={flag(caps, s.table.rowCaps[i]!)} lang={lang} /></> : null}
                  </th>
                  {r.slice(1).map((cell) => <td key={cell}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {s.data === "thresholds" ? <Thresholds lang={lang} /> : null}
      {s.data === "provenance" ? <Provenance lang={lang} /> : null}
    </section>
  );
}

export function DocBody({ page, lang, caps }: { page: DocPage; lang: Lang; caps: Capabilities }) {
  return (
    <>
      {page.callout ? (
        <p className="card callout" role="note" data-testid="not-connected-doc">
          <Icon name="hand" size={24} />
          <span><b>{page.callout}</b></span>
        </p>
      ) : null}
      {page.figure ? (
        <div className="figure docs-figure" dir="ltr" tabIndex={0} role="group" aria-label={page.figure.alt}>
          <img src={page.figure.src} alt={page.figure.alt} width={page.figure.width} height={page.figure.height} loading="lazy" decoding="async" />
        </div>
      ) : null}
      {page.sections.map((s) => <Section key={s.id} s={s} lang={lang} caps={caps} />)}
      <p className="small docs-sources" data-testid="doc-sources">
        {/* One plain link for engineers; raw repository paths are not shown on the page. */}
        {page.sources.slice(0, 1).map((src) => <a key={src} href={REPO_BLOB + src} rel="noopener noreferrer" target="_blank">{dt(lang, "docs.sources")}</a>)}
      </p>
    </>
  );
}
