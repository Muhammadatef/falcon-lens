import type { Metadata } from "next";
import Link from "next/link";
import { CapBadge } from "@/components/CapBadge";
import type { Capabilities } from "@/lib/capabilities";
import { loadCapabilities } from "@/lib/capabilities";
import type { Lang } from "@/lib/contracts";
import { ARCH, type AgentBlock, type ArchContent } from "@/lib/arch-content";
import { pageMetadata } from "@/lib/meta";
import { serverLang } from "@/lib/server-lang";

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: ARCH[lang].title, description: ARCH[lang].lead.slice(0, 160) });
}

/** The investigator loop. Labels are code identifiers, so the figure is always left-to-right. */
function LoopDiagram({ c }: { c: ArchContent }) {
  const nodes = [
    { x: 46, label: "plan", kind: "llm" },
    { x: 136, label: "act", kind: "code" },
    { x: 226, label: "observe", kind: "code" },
    { x: 316, label: "decide", kind: "code" },
  ];
  return (
    <figure className="loop" dir="ltr" data-testid="loop-diagram">
      <svg viewBox="0 0 362 150" role="img" aria-label={`${c.loopLabel}: plan, act, observe, decide. ${c.loopBudget}. ${c.loopDone}.`} focusable="false">
        <path className="loop-arc" d="M316 52 C316 -14 46 -14 46 52" />
        <path className="loop-arrow" d="M46 52 L46 56 M42 50 L46 56 L50 50" />
        {nodes.slice(0, 3).map((n, i) => (
          <path key={n.label} className="loop-link" d={`M${n.x + 27} 80 H${nodes[i + 1]!.x - 27}`} />
        ))}
        {nodes.map((n) => (
          <g key={n.label} className={`loop-node loop-node--${n.kind}`}>
            <circle cx={n.x} cy={80} r={26} />
            <text x={n.x} y={84} textAnchor="middle">{n.label}</text>
          </g>
        ))}
        <path className="loop-link" d="M316 106 V128" />
        <text className="loop-cap" x={316} y={144} textAnchor="end">stop → arbiter</text>
        <text className="loop-cap" x={181} y={17} textAnchor="middle">repeat ≤ 6</text>
        <circle className="loop-dot" r={6} />
      </svg>
      <figcaption className="small">{c.loopBudget} · {c.loopDone}</figcaption>
    </figure>
  );
}

function Flow({ block, legend, caps, lang }: { block: AgentBlock; legend: ArchContent["legend"]; caps: Capabilities; lang: Lang }) {
  return (
    <ol className="flow" data-testid="flow">
      {block.layers.map((l) => (
        <li className="flow-node" data-kind={l.kind ?? "code"} key={l.tag + l.title}>
          <span className="flow-tag mono">{l.tag}</span>
          <div>
            <h4>{l.title}{l.cap ? <> <CapBadge live={caps[l.cap]} lang={lang} /></> : null}</h4>
            <p>{l.body}</p>
            <span className="flow-kind">{legend[l.kind ?? "code"]}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Agent({ id, block, c, caps, lang, badge, children }: { id: string; block: AgentBlock; c: ArchContent; caps: Capabilities; lang: Lang; badge?: boolean; children?: React.ReactNode }) {
  return (
    <section className="agent-arch" aria-labelledby={`${id}-h`} data-testid={id}>
      <div className="sec-head">
        <h2 id={`${id}-h`}>{block.name}</h2>
        <span className="chip mono">{block.adr}</span>
        {badge !== undefined ? <CapBadge live={badge} lang={lang} /> : null}
      </div>
      <p className="card pattern">
        <b>{block.pattern}</b>
        <span className="muted">{block.patternNote}</span>
      </p>
      <div className="prose">
        <h3>{block.whyTitle}</h3>
        <ul>{block.why.map((w) => <li key={w}>{w}</li>)}</ul>
      </div>
      {children}
      <h3 className="h3">{block.flowTitle}</h3>
      <Flow block={block} legend={c.legend} caps={caps} lang={lang} />
      <div className="prose">
        <h3>{block.guardTitle}</h3>
        <ul>{block.guards.map((g) => <li key={g}>{g}</li>)}</ul>
        <h3>{block.rejectedTitle}</h3>
        <ul>{block.rejected.map((r) => <li key={r.name}><b>{r.name}</b>: {r.reason}</li>)}</ul>
      </div>
    </section>
  );
}

export default async function AgentsArchitecturePage() {
  const lang = await serverLang();
  const c = ARCH[lang];
  const caps = await loadCapabilities();
  return (
    <main id="main" className="page">
      <div className="wrap">
        <h1 className="page-title">{c.title}</h1>
        <p className="page-lead">{c.lead}</p>
        <ul className="legend" aria-label="legend">
          {(["llm", "code", "gate"] as const).map((k) => (
            <li key={k} data-kind={k}><i aria-hidden="true" />{c.legend[k]}</li>
          ))}
        </ul>

        <Agent id="investigator" block={c.investigator} c={c} caps={caps} lang={lang} badge={caps.investigator}>
          <LoopDiagram c={c} />
          <div className="chips-wrap">
            <h3 className="h3">{c.toolsTitle}</h3>
            <ul className="chips">{c.tools.map((t) => <li className="chip mono" key={t}>{t}</li>)}</ul>
          </div>
        </Agent>

        <Agent id="sentinel" block={c.sentinel} c={c} caps={caps} lang={lang} />

        <p><Link className="btn" href="/how-it-works">{c.back}</Link></p>
      </div>
    </main>
  );
}
