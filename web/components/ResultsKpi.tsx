import type { Lang } from "@/lib/contracts";
import {
  BADGE_HELP,
  BADGE_LABEL,
  buildAttacks,
  buildFpHistory,
  buildKpiGrid,
  buildOps,
  buildRealSynthetic,
  kpiCopy,
  type Badge as BadgeKind,
  type Fig,
  type FpHistory,
  type OpsRow,
  type RsGroup,
} from "@/lib/results-kpi";
import type { ResultsView } from "@/lib/results";

/** Provenance badge: REAL / SYNTHETIC / FIXTURE (or MIXED where an artifact says both). Text, not colour alone. */
export function Badge({ kind, lang }: { kind: BadgeKind; lang: Lang }) {
  return (
    <span className="prov-badge" data-badge={kind} title={BADGE_HELP[kind][lang]} dir="auto">
      {BADGE_LABEL[kind][lang]}
    </span>
  );
}

function FigView({ fig, ciLabel }: { fig: Fig; ciLabel: string }) {
  return (
    <>
      <b>{fig.main}</b>
      {fig.detail ? <span className="ci">{fig.detail}</span> : null}
      {fig.ci ? <span className="ci">{ciLabel}: {fig.ci}</span> : null}
    </>
  );
}

export function KpiGridSection({ view, lang }: { view: ResultsView | null; lang: Lang }) {
  const grid = buildKpiGrid(view, lang);
  const c = kpiCopy(lang);
  if (!grid) return null;
  const cols = ["val", "test"] as const;
  return (
    <section aria-labelledby="kpi-h" data-testid="kpi-grid" className="kpi-sec">
      <div className="sec-head">
        <h2 id="kpi-h">{c.kpiTitle}</h2>
        <Badge kind={grid.badge} lang={lang} />
      </div>
      <p className="muted">{c.kpiLead}</p>
      <p className="muted" data-testid="kpi-scope">{c.kpiScope}</p>
      <div className="kpis">
        {grid.rows.map((row) => (
          <article className="card kpi" key={row.key} data-testid={`kpi-${row.key}`}>
            <h3 className="kpi-name">{row.label}</h3>
            <p className="kpi-explain">{row.explain}</p>
            <div className="kpi-cols">
              {cols.map((sp) => {
                const cell = row.cells.find((x) => x.split === sp);
                return (
                  <div className="metric kpi-cell" key={sp} data-testid={`metric-${sp === "test" ? "test" : "val"}-${row.key}`}>
                    <span className="lbl">{c[sp]}</span>
                    {cell ? <FigView fig={cell.fig} ciLabel={c.ci} /> : <b>–</b>}
                  </div>
                );
              })}
            </div>
          </article>
        ))}
        <article className="card kpi" data-testid="kpi-official">
          <h3 className="kpi-name">{c.official}</h3>
          <p className="kpi-explain">{c.officialHelp}</p>
          <div className="kpi-cols">
            {cols.map((sp) => (
              <div className="metric kpi-cell" key={sp} data-testid={`metric-${sp}-official`}>
                <span className="lbl">{c[sp]}</span>
                {grid.official[sp] !== null ? <b>{grid.official[sp]}</b> : <b>–</b>}
              </div>
            ))}
          </div>
        </article>
      </div>
      <p className="muted kpi-n" data-testid="kpi-n">
        {c.val}: n = {grid.n.val} · {c.test}: n = {grid.n.test}
        {grid.countsFromReScore ? <> · {c.kpiCounts}</> : null}
      </p>
    </section>
  );
}

function Group({ g, lang, ciLabel }: { g: RsGroup; lang: Lang; ciLabel: string }) {
  return (
    <div className="card rs-group" data-testid={`rs-${g.id}`}>
      <div className="rs-head">
        <h4 className="h4">{g.title}</h4>
        <Badge kind={g.badge} lang={lang} />
      </div>
      {g.counts.length > 0 ? <p className="ci rs-counts">{g.counts.join(" · ")}</p> : null}
      <div className="rs-metrics">
        {g.metrics.map((m) => (
          <div className="metric" key={m.key} data-testid={`rs-${g.id}-${m.key}`}>
            <span className="lbl">{m.label}</span>
            <FigView fig={m.fig} ciLabel={ciLabel} />
            <Badge kind={m.badge} lang={lang} />
          </div>
        ))}
      </div>
      {g.caveat ? <p className="muted rs-caveat"><span dir="ltr" lang="en">{g.caveat}</span></p> : null}
    </div>
  );
}

export function RealSyntheticSection({ lang }: { lang: Lang }) {
  const rs = buildRealSynthetic(lang);
  const c = kpiCopy(lang);
  if (!rs) return null;
  return (
    <section aria-labelledby="rs-h" data-testid="real-synthetic" className="kpi-sec">
      <div className="sec-head"><h2 id="rs-h">{c.rsTitle}</h2></div>
      <p className="muted">{c.rsLead}</p>
      <div className="rs-cols">
        <div className="rs-col" data-testid="rs-real">
          <h3 className="h3">{c.rsReal} <Badge kind="REAL" lang={lang} /></h3>
          {rs.realTotal !== null ? <p className="rs-total"><span className="lbl">{c.manifestReal}</span> <b dir="ltr">{rs.realTotal}</b></p> : null}
          {rs.real.map((g) => <Group key={g.id} g={g} lang={lang} ciLabel={c.ci} />)}
          <p className="muted">{c.rsMatches}</p>
        </div>
        <div className="rs-col" data-testid="rs-synthetic">
          <h3 className="h3">{c.rsSynth} <Badge kind="SYNTHETIC" lang={lang} /> <Badge kind="FIXTURE" lang={lang} /></h3>
          {rs.syntheticTotal !== null ? <p className="rs-total"><span className="lbl">{c.manifestSynth}</span> <b dir="ltr">{rs.syntheticTotal}</b></p> : null}
          {rs.synthetic.map((g) => <Group key={g.id} g={g} lang={lang} ciLabel={c.ci} />)}
          <p className="card callout" role="note"><span>{c.rsSynthNote}</span></p>
        </div>
      </div>
      <ul className="area-prov">
        <li>{c.artifact}: <code dir="ltr">{rs.artifact}</code>{rs.messageArtifact ? <> · <code dir="ltr">{rs.messageArtifact}</code></> : null}</li>
        <li><span dir="ltr" lang="en">{rs.provenance}</span></li>
        <li><span dir="ltr" lang="en">{rs.separationRule}</span></li>
      </ul>
    </section>
  );
}

/** Inline SVG sparkline of the false-alarm rate across runs (oldest left). Pure geometry from the artifacts' values. */
function Spark({ h, lang }: { h: FpHistory; lang: Lang }) {
  const c = kpiCopy(lang);
  const W = 320;
  const H = 96;
  const P = 8;
  const { all, web, lo, hi } = h.series;
  const top = Math.max(...hi.filter((v): v is number => v !== null), ...all.filter((v): v is number => v !== null)) * 1.08 || 1;
  const x = (i: number) => (all.length === 1 ? W / 2 : P + (i * (W - 2 * P)) / (all.length - 1));
  const y = (v: number) => H - P - (v / top) * (H - 2 * P);
  const line = (s: (number | null)[]) => s.flatMap((v, i) => (v === null ? [] : [`${x(i).toFixed(1)},${y(v).toFixed(1)}`])).join(" ");
  const band = (() => {
    const up: string[] = [];
    const down: string[] = [];
    lo.forEach((l, i) => {
      const u = hi[i];
      if (l === null || u === null || u === undefined) return;
      up.push(`${x(i).toFixed(1)},${y(u).toFixed(1)}`);
      down.unshift(`${x(i).toFixed(1)},${y(l).toFixed(1)}`);
    });
    return [...up, ...down].join(" ");
  })();
  const last = all.length - 1;
  const lastV = all[last];
  return (
    <figure className="spark" data-testid="fp-spark">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={c.fpSpark} className="spark-svg" preserveAspectRatio="xMidYMid meet">
        <title>{c.fpSpark}</title>
        <line x1={P} x2={W - P} y1={H - P} y2={H - P} className="spark-axis" />
        {band ? <polygon points={band} className="spark-band" /> : null}
        <polyline points={line(web)} className="spark-web" fill="none" />
        <polyline points={line(all)} className="spark-all" fill="none" />
        {all.map((v, i) => (v === null || i === last ? null : <circle key={i} cx={x(i)} cy={y(v)} r={2.5} className="spark-dot" />))}
        {lastV !== null && lastV !== undefined ? <circle cx={x(last)} cy={y(lastV)} r={5} className="spark-now" /> : null}
      </svg>
      <figcaption className="spark-cap">
        <span>{c.fpOldest}</span>
        <span className="spark-key"><i className="k-all" /> {c.fpAll}</span>
        <span className="spark-key"><i className="k-web" /> {c.fpWeb}</span>
        <span>{c.fpNewestShort}</span>
      </figcaption>
    </figure>
  );
}

function FpCell({ fig, ciLabel }: { fig: Fig | null; ciLabel: string }) {
  if (!fig) return <span className="muted">–</span>;
  return (
    <span className="fp-fig">
      <b>{fig.main}</b>
      {fig.detail ? <span className="ci">{fig.detail}</span> : null}
      {fig.ci ? <span className="ci">{ciLabel}: {fig.ci}</span> : null}
    </span>
  );
}

export function FpHistorySection({ lang }: { lang: Lang }) {
  const h = buildFpHistory(lang);
  const c = kpiCopy(lang);
  if (!h) return null;
  return (
    <section aria-labelledby="fp-h" data-testid="fp-history" className="kpi-sec">
      <div className="sec-head"><h2 id="fp-h">{c.fpTitle}</h2><Badge kind="REAL" lang={lang} /></div>
      <p className="muted">{c.fpLead}</p>
      <p className="muted" data-testid="fp-scope">{c.fpScope}</p>
      <Spark h={h} lang={lang} />
      <div className="tbl-wrap" role="region" tabIndex={0} aria-label={c.fpTitle}>
        <table className="tbl fp-tbl">
          <caption>{c.fpTitle}</caption>
          <thead>
            <tr>
              <th scope="col">{c.fpRun}</th>
              <th scope="col">{c.fpAll}</th>
              <th scope="col">{c.fpWeb}</th>
              <th scope="col">{c.fpNoWeb}</th>
            </tr>
          </thead>
          <tbody>
            {h.runs.map((r) => (
              <tr key={r.artifact} data-testid={r.newest ? "fp-newest" : "fp-run"} className={r.newest ? "fp-newest" : undefined} aria-current={r.newest ? "true" : undefined}>
                <th scope="row">
                  <span className="fp-date" dir="ltr">{r.date}</span>
                  <span className="fp-meta">{r.setLabel} · <code dir="ltr">{r.sha}</code></span>
                  {r.newest ? <span className="chip fp-chip">{c.fpNewest}</span> : null}
                  {r.reRun ? <span className="chip fp-chip">{c.fpReRun}</span> : null}
                  {r.postHoc ? <span className="chip fp-chip">{c.fpPostHoc}</span> : null}
                  {r.dangerous !== null && r.dangerous > 0 ? <span className="chip fp-chip">{r.dangerous} {c.fpDangerous}</span> : null}
                  <details className="fp-changes">
                    <summary>{c.fpChanges}{r.changeCount !== null ? <> · <span dir="ltr">{r.changeCount}</span> {c.fpCommits}</> : null}</summary>
                    {r.changeCount === null ? <p className="muted">{c.fpChangesNone}</p> : (
                      <ul dir="ltr" lang="en">
                        {r.changes.map((s) => <li key={s}>{s}</li>)}
                        {r.changeCount > r.changes.length ? <li className="muted">… {c.fpMore}</li> : null}
                      </ul>
                    )}
                  </details>
                </th>
                <td><FpCell fig={r.all} ciLabel={c.ci} /></td>
                <td><FpCell fig={r.web} ciLabel={c.ci} /></td>
                <td><FpCell fig={r.noWeb} ciLabel={c.ci} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="card callout" role="note" data-testid="fp-note"><span>{c.fpNote}</span></p>
    </section>
  );
}

export function AttacksSection({ lang }: { lang: Lang }) {
  const budgets = buildAttacks(lang);
  const c = kpiCopy(lang);
  if (budgets.length === 0) return null;
  return (
    <section aria-labelledby="atk-h" data-testid="attacks" className="kpi-sec">
      <div className="sec-head"><h2 id="atk-h">{c.atkTitle}</h2><Badge kind={budgets[0]!.badge} lang={lang} /></div>
      <p className="muted">{c.atkLead}</p>
      <p className="muted" data-testid="atk-scope">{c.atkScope}</p>
      {budgets.map((b) => (
        <div className="tbl-wrap atk" key={b.budget} data-testid={`atk-${b.budget}`} role="region" tabIndex={0} aria-label={b.budget === "extended" ? c.atkExtended : c.atkProduction}>
          <table className="tbl">
            <caption>{b.budget === "extended" ? c.atkExtended : c.atkProduction}</caption>
            <thead>
              <tr>
                <th scope="col">{c.atkCategory}</th>
                <th scope="col">{c.atkHarmful}</th>
                <th scope="col">{c.atkAnswered}</th>
              </tr>
            </thead>
            <tbody>
              {[...b.rows, b.total].map((r) => (
                <tr key={r.category} data-testid={`atk-${b.budget}-${r.category}`}>
                  <th scope="row">{r.label}</th>
                  <td><b dir="ltr">{r.harmful}</b>{r.ci ? <span className="ci"> {c.ci}: {r.ci}</span> : null}</td>
                  <td><span dir="ltr">{r.answered}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="ci atk-src"><code dir="ltr">{b.artifact}</code></p>
        </div>
      ))}
      <p className="card callout" role="note" data-testid="atk-note"><span>{c.atkNote}</span></p>
    </section>
  );
}

function OpsCards({ rows, lang }: { rows: OpsRow[]; lang: Lang }) {
  const c = kpiCopy(lang);
  return (
    <div className="metrics">
      {rows.map((r) => (
        <div className="card metric" key={r.key} data-testid={`ops-${r.key}`}>
          <span className="lbl">{r.label}</span>
          <FigView fig={r.fig} ciLabel={c.ci} />
          <Badge kind={r.badge} lang={lang} />
        </div>
      ))}
    </div>
  );
}

export function OpsSection({ lang }: { lang: Lang }) {
  const o = buildOps(lang);
  const c = kpiCopy(lang);
  if (o.cost.length + o.agreement.length + o.stability.length === 0 && !o.extractor) return null;
  const ex = o.extractor;
  return (
    <section aria-labelledby="ops-h" data-testid="ops" className="kpi-sec">
      <div className="sec-head"><h2 id="ops-h">{c.opsTitle}</h2></div>
      <p className="muted">{c.opsLead}</p>
      <p className="muted" data-testid="ops-scope">{c.opsScope}</p>
      {o.cost.length > 0 ? <><h3 className="h3">{c.opsCost}</h3><OpsCards rows={o.cost} lang={lang} /></> : null}
      {o.agreement.length > 0 ? <><h3 className="h3">{c.opsAgree}</h3><OpsCards rows={o.agreement} lang={lang} /></> : null}
      {ex ? (
        <>
          <div className="sec-head"><h3 className="h3">{c.opsExtract}</h3><Badge kind={ex.badge} lang={lang} /></div>
          <div className="tbl-wrap" data-testid="ops-extractor" role="region" tabIndex={0} aria-label={c.opsExtract}>
            <table className="tbl">
              <caption>{c.opsExtract}</caption>
              <thead>
                <tr>
                  <th scope="col">{c.route}</th>
                  {ex.rows.map((r) => <th scope="col" key={r.key}>{r.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {ex.columns.map((col) => (
                  <tr key={col.route} data-testid={`ops-extractor-${col.route}`}>
                    <th scope="row">{col.route === "cloud" ? c.cloud : c.local}<span className="ci"> <code dir="ltr">{col.model}</code></span></th>
                    {ex.rows.map((r) => <td key={r.key}><FpCell fig={r[col.route]} ciLabel={c.ci} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {ex.agreement.length > 0 ? (
            <div className="metrics">
              {ex.agreement.map((a) => (
                <div className="card metric" key={a.key} data-testid={`ops-agree-${a.key}`}>
                  <span className="lbl">{a.label}</span>
                  <FigView fig={a.fig} ciLabel={c.ci} />
                  <Badge kind={ex.badge} lang={lang} />
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
      {o.stability.length > 0 ? <><h3 className="h3">{c.opsStable}</h3><OpsCards rows={o.stability} lang={lang} /></> : null}
    </section>
  );
}
