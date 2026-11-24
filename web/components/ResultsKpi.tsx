import type { Lang } from "@/lib/contracts";
import {
  BADGE_HELP,
  BADGE_LABEL,
  buildAttacks,
  buildFpHistory,
  buildKpiGrid,
  buildOps,
  artifactNote,
  buildRealSynthetic,
  kpiCopy,
  type Badge as BadgeKind,
  type Fig,
  type FpHistory,
  type FpRunView,
  type OpsRow,
  type RsGroup,
} from "@/lib/results-kpi";
import type { ResultsView } from "@/lib/results";
import { Fold } from "@/components/Fold";

/** Provenance badge: REAL / SYNTHETIC / FIXTURE (or MIXED where an artifact says both). Text, not colour alone. */
export function Badge({ kind, lang, short = false }: { kind: BadgeKind; lang: Lang; short?: boolean }) {
  return (
    <span className="prov-badge" data-badge={kind} title={BADGE_HELP[kind][lang]} dir="auto">
      {short ? kind : BADGE_LABEL[kind][lang]}
    </span>
  );
}

/** A note published in an artifact: Arabic when we hold a translation, else the English text, labelled and LTR-isolated. Never hidden. */
export function ArtifactNote({ text, lang }: { text: string; lang: Lang }) {
  const ar = artifactNote(text, lang);
  if (ar !== null) return <>{ar}</>;
  return (
    <>
      <span className="muted">ملاحظة منهجية (بالإنجليزية): </span>
      <bdi dir="ltr" lang="en" className="note-en">{text}</bdi>
    </>
  );
}

/** "0 من 50": the words keep the page direction, every number is isolated (no forced LTR on Arabic phrases). */
function CountOf({ text }: { text: string }) {
  return <>{text.split(/(\d[\d.,]*%?)/).map((part, i) => (i % 2 === 1 ? <bdi key={i} dir="ltr">{part}</bdi> : part))}</>;
}

function FigView({ fig, ciLabel }: { fig: Fig; ciLabel: string }) {
  return (
    <>
      <b>{fig.main}</b>
      {fig.detail ? <span className="ci"><CountOf text={fig.detail} /></span> : null}
      {fig.ci ? <span className="ci"><span className="vh">{ciLabel}: </span><bdi dir="ltr">{fig.ci}</bdi></span> : null}
    </>
  );
}

export function KpiGridSection({ view, lang }: { view: ResultsView | null; lang: Lang }) {
  const grid = buildKpiGrid(view, lang);
  const c = kpiCopy(lang);
  if (!grid) return null;
  const cols = ["val", "test"] as const;
  return (
    <section aria-labelledby="kpi-h" id="sec-kpi" data-testid="kpi-grid" className="kpi-sec">
      <div className="sec-head">
        <h2 id="kpi-h">{c.kpiTitle}</h2>
        <Badge kind={grid.badge} lang={lang} />
      </div>
      <p className="muted">{c.kpiLead} {c.legend}</p>
      <p className="muted" data-testid="kpi-scope">{c.kpiScope}</p>
      <div className="tbl-wrap kpi-wrap">
        <table className="tbl kpi-tbl">
          <caption className="vh">{c.kpiTitle}</caption>
          <thead>
            <tr>
              <th scope="col" className="kpi-h0"><span className="vh">{c.kpiTitle}</span></th>
              {cols.map((sp) => (
                <th scope="col" key={sp}>
                  {c[sp]}
                  <span className="ci"> n = {grid.n[sp]}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row) => (
              <tr key={row.key} data-testid={`kpi-${row.key}`}>
                <th scope="row">
                  <span className="kpi-name">{row.label}</span>
                  <span className="kpi-explain">{row.explain}</span>
                </th>
                {cols.map((sp) => {
                  const cell = row.cells.find((x) => x.split === sp);
                  return (
                    <td key={sp} className="kpi-cell" data-testid={`metric-${sp}-${row.key}`}>
                      {cell ? <FigView fig={cell.fig} ciLabel={c.ci} /> : <b>–</b>}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr data-testid="kpi-official">
              <th scope="row">
                <span className="kpi-name">{c.official}</span>
                <span className="kpi-explain">{c.officialHelp}</span>
              </th>
              {cols.map((sp) => (
                <td key={sp} className="kpi-cell" data-testid={`metric-${sp}-official`}>
                  <b>{grid.official[sp] !== null ? grid.official[sp] : "–"}</b>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {grid.countsFromReScore ? <p className="muted kpi-n" data-testid="kpi-n">{c.kpiCounts}</p> : null}
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
      <div className="tbl-wrap">
        <table className="tbl rs-tbl">
          <caption className="vh">{g.title}</caption>
          <thead>
            <tr>
              <th scope="col"><span className="vh">{g.title}</span></th>
              {g.columns.map((col) => (
                <th scope="col" key={col.key}>
                  {col.label}
                  {col.counts ? <span className="ci">{col.counts}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {g.metrics.map((m) => (
              <tr key={m.key} data-testid={`rs-${g.id}-${m.key}`}>
                <th scope="row">
                  <span className="rs-lbl">{m.label}</span>
                  <Badge kind={m.badge} lang={lang} short />
                </th>
                {m.figs.map((f, i) => (
                  <td key={g.columns[i]!.key}>{f ? <FpCell fig={f} ciLabel={ciLabel} /> : <span className="muted">–</span>}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {g.caveat ? <p className="muted rs-caveat"><ArtifactNote text={g.caveat} lang={lang} /></p> : null}
    </div>
  );
}

export function RealSyntheticSection({ lang }: { lang: Lang }) {
  const rs = buildRealSynthetic(lang);
  const c = kpiCopy(lang);
  if (!rs) return null;
  return (
    <section aria-labelledby="rs-h" id="sec-rs" data-testid="real-synthetic" className="kpi-sec">
      <div className="sec-head"><h2 id="rs-h">{c.rsTitle}</h2></div>
      <p className="muted">{c.rsLead} {c.legend}</p>
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
      <details className="rs-src" data-testid="rs-src">
        <summary>{c.artifact}</summary>
      <ul className="area-prov">
        <li>{c.artifact}: <code dir="ltr">{rs.artifact}</code>{rs.messageArtifact ? <> · <code dir="ltr">{rs.messageArtifact}</code></> : null}</li>
        {rs.provenance ? <li><ArtifactNote text={rs.provenance} lang={lang} /></li> : null}
        {rs.separationRule ? <li><ArtifactNote text={rs.separationRule} lang={lang} /></li> : null}
      </ul>
      </details>
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
      {fig.detail ? <span className="ci"><CountOf text={fig.detail} /></span> : null}
      {fig.ci ? <span className="ci"><span className="vh">{ciLabel}: </span><bdi dir="ltr">{fig.ci}</bdi></span> : null}
    </span>
  );
}

const SHOWN = 3;

function FpTable({ runs, lang }: { runs: FpRunView[]; lang: Lang }) {
  const c = kpiCopy(lang);
  return (
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
            {runs.map((r) => (
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
  );
}

export function FpHistorySection({ lang }: { lang: Lang }) {
  const h = buildFpHistory(lang);
  const c = kpiCopy(lang);
  if (!h) return null;
  return (
    <Fold id="fp-h" title={c.fpTitle} badge={<Badge kind="REAL" lang={lang} />} testId="fp-history">
      <p className="muted">{c.fpLead}</p>
      <p className="muted" data-testid="fp-scope">{c.fpScope}</p>
      <Spark h={h} lang={lang} />
      <FpTable runs={h.runs.slice(0, SHOWN)} lang={lang} />
      {h.runs.length > SHOWN ? (
        <details className="fp-all" data-testid="fp-all">
          <summary>{c.fpShowAll} {h.runs.length}</summary>
          <FpTable runs={h.runs.slice(SHOWN)} lang={lang} />
        </details>
      ) : null}
      <p className="card callout" role="note" data-testid="fp-note"><span>{c.fpNote}</span></p>
    </Fold>
  );
}

export function AttacksSection({ lang }: { lang: Lang }) {
  const budgets = buildAttacks(lang);
  const c = kpiCopy(lang);
  if (budgets.length === 0) return null;
  return (
    <Fold id="atk-h" title={c.atkTitle} badge={<Badge kind={budgets[0]!.badge} lang={lang} />} testId="attacks">
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
                  <td><b><CountOf text={r.harmful} /></b>{r.ci ? <span className="ci"><CountOf text={c.ci} />: <bdi dir="ltr">{r.ci}</bdi></span> : null}</td>
                  <td><CountOf text={r.answered} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="ci atk-src"><code dir="ltr">{b.artifact}</code></p>
        </div>
      ))}
      <p className="card callout" role="note" data-testid="atk-note"><span>{c.atkNote}</span></p>
    </Fold>
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
          <Badge kind={r.badge} lang={lang} short />
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
    <Fold id="ops-h" title={c.opsTitle} testId="ops">
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
                  <Badge kind={ex.badge} lang={lang} short />
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
      {o.stability.length > 0 ? <><h3 className="h3">{c.opsStable}</h3><OpsCards rows={o.stability} lang={lang} /></> : null}
    </Fold>
  );
}
