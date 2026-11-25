import Link from "next/link";
import { CapBadge } from "@/components/CapBadge";
import { FlowDiagram } from "@/components/arch/FlowDiagram";
import { flag } from "@/lib/cap-flag";
import type { Capabilities } from "@/lib/capabilities";
import type { Lang } from "@/lib/contracts";
import { BUILDING_AGENTS, type BuildingAgentsCopy, type Item, type NodeKind, type PipeLane } from "@/lib/docs-building-agents";
import { bundledDspyRows, excludesZero } from "@/lib/dspy-results";

const fmt = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 4 });
const KINDS: NodeKind[] = ["llm", "code", "gate", "store"];

function Legend({ c }: { c: BuildingAgentsCopy }) {
  return (
    <ul className="legend" aria-label="legend">
      {KINDS.map((k) => <li key={k} data-kind={k}><i aria-hidden="true" />{c.legend[k]}</li>)}
    </ul>
  );
}

/**
 * A lane-by-lane pipeline. Plain HTML lists (no inline styles, no raw HTML): vertical on a phone, one row per lane
 * from 1100px. Identifiers are code and stay left-to-right; the connectors mirror in RTL through logical CSS.
 */
function Pipeline({ lanes, label, caps, lang, id }: { lanes: PipeLane[]; label: string; caps: Capabilities; lang: Lang; id: string }) {
  return (
    <figure className="ba-fig" role="group" aria-label={label} data-testid={id}>
      {lanes.map((lane, li) => (
        <div className="ba-lane" key={lane.title}>
          <h3 className="ba-lane-title"><span className="ba-lane-n" aria-hidden="true">{li + 1}</span>{lane.title}</h3>
          <ol className="ba-nodes" data-n={lane.nodes.length}>
            {lane.nodes.map((n) => (
              <li className="ba-node" data-kind={n.kind} key={n.id}>
                <span className="ba-id mono" translate="no">{n.id}</span>
                <b>{n.name}</b>
                <span className="ba-note">{n.note}</span>
                {n.cap ? <span><CapBadge live={flag(caps, n.cap)} lang={lang} /></span> : null}
              </li>
            ))}
          </ol>
        </div>
      ))}
    </figure>
  );
}

function Items({ items }: { items: Item[] }) {
  return (
    <ul className="ba-items">
      {items.map((it) => (
        <li className="card ba-item" key={it.title}>
          <h3>{it.title}</h3>
          <p>{it.body}</p>
          {it.path ? <code className="mono ba-path" translate="no" dir="ltr">{it.path}</code> : null}
        </li>
      ))}
    </ul>
  );
}

function DspyTable({ c, lang }: { c: BuildingAgentsCopy["whyDspy"]; lang: Lang }) {
  const rows = bundledDspyRows();
  if (rows.length === 0) return <p className="muted" data-testid="ba-dspy-none">{c.none}</p>;
  return (
    <div className="tbl-wrap" tabIndex={0} role="group" aria-label={c.tableCaption} data-testid="ba-dspy-table">
      <table className="tbl">
        <caption>{c.tableCaption}</caption>
        <thead>
          <tr>{c.cols.map((h) => <th scope="col" key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.artifact}>
              <th scope="row" className="mono" translate="no">{r.role}</th>
              <td className="mono">{fmt(r.before)}</td>
              <td className="mono">{fmt(r.after)}</td>
              <td className="mono">{r.low !== null && r.high !== null ? `[${fmt(r.low)}, ${fmt(r.high)}]` : "-"}</td>
              <td>{excludesZero(r) ? c.yes : c.no}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small faint ba-src" lang={lang}>{rows.some((r) => r.synthetic) ? c.synthetic : "evals/results/published/dspy"}</p>
    </div>
  );
}

/** Body of /docs/building-agents (the h1 and lead are rendered by the page). */
export function BuildingAgentsDoc({ lang, caps }: { lang: Lang; caps: Capabilities }) {
  const c = BUILDING_AGENTS[lang];
  const rows = bundledDspyRows();
  const adopted = rows.filter((r) => r.adopted).length;
  const toc: [string, string][] = [
    ["#process", c.process.title],
    ["#sentinel", c.sentinel.title],
    ["#dspy-pipeline", c.dspy.title],
    ["#why-langgraph", c.whyLg.title],
    ["#why-dspy", c.whyDspy.title],
    ["#not-used", c.notUsed.title],
  ];
  return (
    <>
      <nav className="card ba-toc" aria-label={c.back}>
        <ol>
          {toc.map(([tocHref, t]) => <li key={tocHref}><a href={tocHref}>{t}</a></li>)}
        </ol>
      </nav>

      <section className="docs-sec" id="process" aria-labelledby="ba-process-h">
        <div className="sec-head"><h2 id="ba-process-h">{c.process.title}</h2></div>
        <p className="ba-intro">{c.process.intro}</p>
        <Items items={c.process.items} />
      </section>

      <section className="docs-sec" id="sentinel" aria-labelledby="ba-sentinel-h">
        <div className="sec-head"><h2 id="ba-sentinel-h">{c.sentinel.title}</h2></div>
        <p className="ba-intro">{c.sentinel.intro}</p>
        <Legend c={c} />
        <Pipeline lanes={c.sentinel.lanes} label={c.sentinel.label} caps={caps} lang={lang} id="ba-sentinel" />
        <div className="flow-section" data-testid="ba-sentinel-flow"><FlowDiagram spec="dir" lang={lang} caps={caps as unknown as Record<string, boolean>} /></div>
        <Items items={c.sentinel.notes} />
      </section>

      <section className="docs-sec" id="dspy-pipeline" aria-labelledby="ba-dspy-h">
        <div className="sec-head"><h2 id="ba-dspy-h">{c.dspy.title}</h2></div>
        <p className="ba-intro">{c.dspy.intro}</p>
        <Legend c={c} />
        <Pipeline lanes={c.dspy.lanes} label={c.dspy.label} caps={caps} lang={lang} id="ba-dspy" />
        <div className="flow-section" data-testid="ba-dspy-flow"><FlowDiagram spec="dspy" lang={lang} caps={caps as unknown as Record<string, boolean>} /></div>
        <Items items={c.dspy.notes} />
      </section>

      <section className="docs-sec" id="why-langgraph" aria-labelledby="ba-lg-h">
        <div className="sec-head"><h2 id="ba-lg-h">{c.whyLg.title}</h2></div>
        <p className="ba-intro">{c.whyLg.intro}</p>
        <Items items={c.whyLg.items} />
        <div className="prose">
          <h3>{c.whyLg.coreTitle}</h3>
          <p>{c.whyLg.core}</p>
          <h3>{c.whyLg.invTitle}</h3>
          <p>{c.whyLg.inv}</p>
        </div>
      </section>

      <section className="docs-sec" id="why-dspy" aria-labelledby="ba-wd-h">
        <div className="sec-head"><h2 id="ba-wd-h">{c.whyDspy.title}</h2></div>
        <p className="ba-intro">{c.whyDspy.intro}</p>
        <Items items={c.whyDspy.items} />
        <div className="card callout ba-result" role="note" data-testid="ba-dspy-result" data-adopted={adopted}>
          <div className="prose">
            <h3>{c.whyDspy.resultTitle}</h3>
            <p>{adopted === 0 && rows.length > 0 ? c.whyDspy.result : c.whyDspy.none}</p>
          </div>
        </div>
        <DspyTable c={c.whyDspy} lang={lang} />
        <div className="prose">
          <h3>{c.whyDspy.gateTitle}</h3>
          <p>{c.whyDspy.gate}</p>
        </div>
      </section>

      <section className="docs-sec" id="not-used" aria-labelledby="ba-nu-h">
        <div className="sec-head"><h2 id="ba-nu-h">{c.notUsed.title}</h2></div>
        <p className="ba-intro">{c.notUsed.intro}</p>
        <Items items={c.notUsed.items} />
      </section>

      <p><Link className="btn" href="/docs/agents">{c.back}</Link></p>
    </>
  );
}
