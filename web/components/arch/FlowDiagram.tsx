"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CapBadge } from "@/components/CapBadge";
import { Icon } from "@/components/Icon";
import { ArchPanel, REPO_BLOB } from "@/components/arch/ArchPanel";
import { FlowControls, type FlowStatus } from "@/components/arch/FlowControls";
import { ToolBadge } from "@/components/arch/ToolBadge";
import { FLOWS, FLOW_UI, NODE_DESC, badgeTool, nodesOf, type FlowNode, type FlowSpec } from "@/lib/arch-flow";
import type { Lang } from "@/lib/contracts";
import { LOGO_PATHS } from "@/lib/tool-logos.gen";

/** Timeline, in milliseconds: the layers build in (LEAD), then each step is a hop (TRAVEL) and a rest (DWELL). */
export const FLOW_TIMING = { lead: 1500, travel: 620, dwell: 680 } as const;
const STEP = FLOW_TIMING.travel + FLOW_TIMING.dwell;
const ease = (p: number) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);

type Point = readonly [number, number];
interface Geometry { w: number; h: number; pts: Point[]; edges: string[] }

/** A wire between two node centres: straight when they share a row or a column, an S-curve otherwise. */
function wire(a: Point, b: Point): string {
  const [ax, ay] = a;
  const [bx, by] = b;
  if (Math.abs(ay - by) < 6 || Math.abs(ax - bx) < 6) return `M${ax} ${ay}L${bx} ${by}`;
  const my = (ay + by) / 2;
  return `M${ax} ${ay}C${ax} ${my} ${bx} ${my} ${bx} ${by}`;
}

/**
 * An animated architecture diagram. The boxes are real HTML buttons in a responsive grid (touch-sized, RTL by
 * logical properties, readable by a screen reader); the wires and the travelling dot are drawn in SVG layers from
 * the measured box positions, so the same component works from a phone to a wide screen and in both directions.
 *
 * Motion: the layers build in, then one request travels the numbered path while the caption follows. Play, pause,
 * replay and step buttons control it. With `prefers-reduced-motion` nothing moves: the whole path is drawn, every
 * box keeps its number and label, and the steps can be read one at a time. A text version sits under every diagram.
 *
 * CSP: no inline styles; positions are SVG attributes. Capture scripts can seek it with a `fl-flow-seek` event.
 */
export function FlowDiagram({ spec: specId, lang, caps, view = "full", children }: {
  spec: FlowSpec["id"];
  lang: Lang;
  caps: Record<string, boolean>;
  view?: "full" | "biz";
  /** Extra content for the text version (server-rendered). */
  children?: ReactNode;
}) {
  const spec = FLOWS.find((s) => s.id === specId)!;
  const ui = FLOW_UI[lang];
  const tid = `flow-${spec.id}`;
  const total = spec.steps.length;
  const nodes = useMemo(() => nodesOf(spec), [spec]);
  const stepOf = useMemo(() => new Map(spec.steps.map((s, i) => [s.node, i] as const)), [spec]);

  const rootRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const progRefs = useRef<(SVGPathElement | null)[]>([]);
  const dotRef = useRef<SVGGElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const tRef = useRef(-FLOW_TIMING.lead);
  const stepRef = useRef(-1);
  const geomRef = useRef<Geometry | null>(null);
  const reducedRef = useRef(false);

  const [status, setStatus] = useState<FlowStatus>("idle");
  const [step, setStep] = useState(-1);
  const [reduced, setReduced] = useState(false);
  const [armed, setArmed] = useState(false);
  const [built, setBuilt] = useState(false);
  const [geom, setGeom] = useState<Geometry | null>(null);
  const [panel, setPanel] = useState<{ node: string; graph?: string } | null>(null);

  const paint = useCallback((t: number) => {
    const g = geomRef.current;
    if (!g) return;
    const still = reducedRef.current;
    const idx = t < 0 ? -1 : Math.min(total - 1, Math.floor(t / STEP));
    const p = idx <= 0 ? 1 : ease(Math.min(1, (t - idx * STEP) / FLOW_TIMING.travel));
    progRefs.current.forEach((el, i) => {
      if (!el) return;
      const offset = still || i < idx - 1 ? 0 : i === idx - 1 ? 1 - p : 1;
      el.setAttribute("stroke-dashoffset", offset.toFixed(4));
    });
    const dot = dotRef.current;
    if (!dot) return;
    // The dot is shown only while it travels; on arrival it fades and the box itself lights up (its label stays readable).
    const path = progRefs.current[idx - 1];
    if (still || idx < 1 || p >= 1 || !path) {
      dot.setAttribute("opacity", "0");
      return;
    }
    const at = path.getPointAtLength(path.getTotalLength() * p);
    dot.setAttribute("transform", `translate(${at.x.toFixed(1)} ${at.y.toFixed(1)})`);
    dot.setAttribute("opacity", Math.min(1, (1 - p) * 8).toFixed(2));
  }, [total]);

  const goto = useCallback((t: number) => {
    tRef.current = t;
    const idx = t < 0 ? -1 : Math.min(total - 1, Math.floor(t / STEP));
    stepRef.current = idx;
    setStep(idx);
    paint(t);
  }, [paint, total]);

  // Reduced motion: decided on the client, and followed if the visitor changes the setting.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      reducedRef.current = mq.matches;
      setReduced(mq.matches);
      if (mq.matches) setStatus((s) => (s === "playing" ? "paused" : s));
      paint(tRef.current);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [paint]);

  // Measure the boxes on the request path and redraw the wires whenever the layout changes.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const centre = (el: HTMLElement): Point => {
      let x = el.offsetWidth / 2;
      let y = el.offsetHeight / 2;
      let cur: HTMLElement | null = el;
      while (cur && cur !== stage) {
        x += cur.offsetLeft;
        y += cur.offsetTop;
        cur = cur.offsetParent as HTMLElement | null;
      }
      return [Math.round(x), Math.round(y)];
    };
    const measure = () => {
      const pts: Point[] = [];
      for (const s of spec.steps) {
        const el = nodeRefs.current.get(s.node);
        if (!el) return;
        pts.push(centre(el));
      }
      const next: Geometry = { w: stage.offsetWidth, h: stage.offsetHeight, pts, edges: pts.slice(1).map((b, i) => wire(pts[i]!, b)) };
      const prev = geomRef.current;
      if (prev && prev.w === next.w && prev.h === next.h && prev.edges.join() === next.edges.join()) return;
      geomRef.current = next;
      setGeom(next);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(stage);
    void document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [spec]);

  useEffect(() => {
    paint(tRef.current);
  }, [geom, paint]);

  // Build in and start once, when the diagram reaches the middle of the screen.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (reducedRef.current) {
      setBuilt(true);
      return;
    }
    setArmed(true);
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      setBuilt(true);
      if (!reducedRef.current) setStatus((s) => (s === "idle" ? "playing" : s));
    }, { rootMargin: "-25% 0px -25% 0px" });
    io.observe(root);
    return () => io.disconnect();
  }, []);

  // The clock.
  useEffect(() => {
    if (status !== "playing") return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      tRef.current += Math.min(64, now - last);
      last = now;
      const t = tRef.current;
      const idx = t < 0 ? -1 : Math.min(total - 1, Math.floor(t / STEP));
      if (idx !== stepRef.current) {
        stepRef.current = idx;
        setStep(idx);
      }
      paint(t);
      if (t >= total * STEP) {
        setStatus("done");
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [status, paint, total]);

  // Frame-exact seeking for the capture scripts (web/scripts/capture-arch.mjs): detail = time in ms.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onSeek = (e: Event) => {
      const t = Number((e as CustomEvent<number>).detail);
      if (!Number.isFinite(t)) return;
      setBuilt(true);
      setStatus(t >= total * STEP ? "done" : "paused");
      goto(t);
    };
    root.addEventListener("fl-flow-seek", onSeek);
    return () => root.removeEventListener("fl-flow-seek", onSeek);
  }, [goto, total]);

  const toggle = () => {
    if (status === "playing") return setStatus("paused");
    if (status === "done") goto(0);
    setBuilt(true);
    setStatus("playing");
  };
  const replay = () => {
    goto(0);
    setBuilt(true);
    setStatus("playing");
  };
  const stepTo = (idx: number) => {
    if (idx < 0 || idx > total - 1) return;
    setBuilt(true);
    setStatus("paused");
    goto(idx * STEP + FLOW_TIMING.travel);
  };

  const closePanel = useCallback(() => {
    setPanel((cur) => {
      if (cur) requestAnimationFrame(() => nodeRefs.current.get(cur.node)?.focus());
      return null;
    });
  }, []);
  const openNode = (node: FlowNode) => {
    setStatus((s) => (s === "playing" ? "paused" : s));
    setPanel({ node: node.id, graph: node.graph });
  };

  useEffect(() => {
    if (!panel) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePanel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [panel, closePanel]);

  const toolOf = (node: FlowNode) => badgeTool(node.badge, LOGO_PATHS);

  const renderNode = (node: FlowNode) => {
    const no = stepOf.get(node.id);
    const live = caps[node.cap] === true;
    const tool = toolOf(node);
    const state = no === undefined || step < 0 ? undefined : no === step ? "active" : no < step ? "done" : undefined;
    return (
      <li key={node.id} className="af-item">
        <button
          type="button"
          ref={(el) => {
            if (el) nodeRefs.current.set(node.id, el);
            else nodeRefs.current.delete(node.id);
          }}
          className="af-node"
          data-state={state}
          data-live={live ? "true" : "false"}
          data-llm={node.llm ? "true" : undefined}
          data-onpath={no === undefined ? undefined : "true"}
          data-testid={`${tid}-node-${node.id}`}
          aria-haspopup="dialog"
          aria-expanded={panel?.node === node.id}
          onClick={() => openNode(node)}
        >
          <ToolBadge badge={node.badge} />
          <span className="af-node-text">
            <b>{node.label[lang]}</b>
            <small>{node.sub[lang]}</small>
          </span>
          {tool ? <span className="vh">{ui.panelTool}: {tool}</span> : null}
          {no === undefined ? null : (
            <>
              <i className="af-no" aria-hidden="true">{no + 1}</i>
              <span className="vh">{ui.step} {no + 1}</span>
            </>
          )}
          {live ? <span className="vh">{ui.status}: {ui.live}</span> : <span className="af-prog">{ui.progress}</span>}
        </button>
      </li>
    );
  };

  const open = panel ? nodes.find((x) => x.id === panel.node) : undefined;
  const openTool = open ? toolOf(open) : null;
  const src = open?.repo ?? "";
  const dialog = !panel || !open ? null : panel.graph ? (
    <ArchPanel id={panel.graph} lang={lang} caps={caps} view={view} onClose={closePanel} onOpen={(id) => setPanel({ node: panel.node, graph: id })} closeRef={closeRef} />
  ) : (
    <>
      <div className="ap-scrim" aria-hidden="true" onClick={closePanel} />
      <div className="ap" role="dialog" aria-modal="false" aria-labelledby="ap-title" data-testid="arch-panel" data-node={open.id} data-kind="tool">
        <header className="ap-head">
          <div>
            <span className="ap-kind">{openTool ?? spec.title[lang]}</span>
            <h2 id="ap-title">{open.label[lang]}</h2>
            <CapBadge live={caps[open.cap] === true} lang={lang} />
          </div>
          <button type="button" ref={closeRef} className="ap-close" onClick={closePanel} aria-label={ui.close} data-testid="arch-panel-close">
            <span aria-hidden="true">×</span>
          </button>
        </header>
        <div className="ap-body">
          <section>
            <h3>{ui.panelWhat}</h3>
            <p>{NODE_DESC[open.id]?.[lang] ?? open.sub[lang]}</p>
          </section>
          {openTool ? (
            <section>
              <h3>{ui.panelTool}</h3>
              <p className="af-panel-tool">
                <ToolBadge badge={open.badge} />
                <span>{openTool}{"mono" in open.badge ? ` (${ui.badgeNote})` : ""}</span>
              </p>
            </section>
          ) : null}
          {view === "full" ? (
            <section>
              <h3>{ui.panelCode}</h3>
              <p><a className="ap-link" href={REPO_BLOB + src} rel="noopener noreferrer" target="_blank" data-testid="arch-code-link">{ui.codeLink}</a></p>
            </section>
          ) : null}
        </div>
      </div>
    </>
  );

  const caption = step >= 0 ? spec.steps[step]!.caption[lang] : "";
  const hasMono = nodes.some((x) => "mono" in x.badge);

  return (
    <figure ref={rootRef} className="af" data-flow={spec.id} data-motion={reduced ? "static" : "animated"} data-status={status} data-step={step} data-armed={armed ? "true" : undefined} data-built={built ? "true" : undefined} data-duration={total * STEP} data-testid={tid}>
      <figcaption className="vh">{ui.diagram}: {spec.title[lang]}</figcaption>
      <FlowControls lang={lang} status={status} step={step} total={total} caption={caption || (reduced ? ui.idleStatic : ui.idle)} reduced={reduced} onToggle={toggle} onReplay={replay} onPrev={() => stepTo(step - 1)} onNext={() => stepTo(step + 1)} testid={tid} />

      <div className="af-stage" ref={stageRef} role="group" aria-label={spec.title[lang]} data-testid={`${tid}-stage`}>
        {geom ? (
          <svg className="af-wires" viewBox={`0 0 ${geom.w} ${geom.h}`} aria-hidden="true" focusable="false" data-testid={`${tid}-wires`}>
            {geom.edges.map((d, i) => <path key={`b${i}`} className="af-wire" d={d} />)}
            {geom.edges.map((d, i) => (
              <path
                key={`p${i}`}
                ref={(el) => {
                  progRefs.current[i] = el;
                }}
                className="af-wire-on"
                d={d}
                pathLength={1}
                strokeDasharray="1 1"
                strokeDashoffset={1}
              />
            ))}
          </svg>
        ) : null}

        {spec.bands.map((band, bi) => (
          <section key={band.id} className="af-band" data-band={band.id} data-i={bi} aria-labelledby={`${tid}-band-${band.id}`} data-testid={`${tid}-band-${band.id}`}>
            <header className="af-band-head">
              <span className="af-band-icon"><Icon name={band.icon} size={22} /></span>
              <h3 id={`${tid}-band-${band.id}`}>{band.title[lang]}</h3>
              <p>{band.sub[lang]}</p>
            </header>
            <div className="af-groups" data-count={band.groups.length}>
              {band.groups.map((group) => (
                <div key={group.id} className="af-group" data-tone={group.tone} data-titled={group.title ? "true" : "false"} data-size={group.nodes.length > 4 ? "wide" : "narrow"} data-testid={`${tid}-group-${group.id}`}>
                  {group.title ? (
                    <h4 className="af-group-title">
                      {group.badge ? <ToolBadge badge={group.badge} size="sm" /> : null}
                      <span>{group.title[lang]}</span>
                    </h4>
                  ) : null}
                  <ul className="af-nodes" aria-label={group.title ? group.title[lang] : band.title[lang]}>{group.nodes.map(renderNode)}</ul>
                </div>
              ))}
            </div>
          </section>
        ))}

        {geom ? (
          <svg className="af-dots" viewBox={`0 0 ${geom.w} ${geom.h}`} aria-hidden="true" focusable="false">
            <g ref={dotRef} opacity={0} data-testid={`${tid}-dot`}>
              <circle className="af-dot-halo" r={15} />
              <circle className="af-dot" r={6} />
            </g>
          </svg>
        ) : null}
      </div>

      <ul className="af-legend" aria-label={lang === "ar" ? "دليل المخطط" : "Legend"}>
        <li><i className="af-key" data-key="path" aria-hidden="true">1</i>{ui.altSteps}</li>
        <li><i className="af-key" data-key="llm" aria-hidden="true" />{ui.model}</li>
        {hasMono ? <li><i className="af-key" data-key="mono" aria-hidden="true">Aa</i>{ui.badgeNote}</li> : null}
        <li><span className="af-prog">{ui.progress}</span></li>
      </ul>
      <p className="af-note" data-testid={`${tid}-logo-note`}>{ui.logos}</p>

      <details className="af-alt" data-testid={`${tid}-alt`}>
        <summary>{ui.alt}</summary>
        <div className="af-alt-body">
          <h4>{ui.altSteps}</h4>
          <ol className="af-alt-steps">
            {spec.steps.map((s) => <li key={s.node}>{s.caption[lang]}</li>)}
          </ol>
          <h4>{ui.altParts}</h4>
          {spec.bands.map((band) => (
            <div key={band.id} className="af-alt-band">
              <h5>{band.title[lang]}</h5>
              <ul>
                {band.groups.flatMap((g) => g.nodes).map((node) => {
                  const tool = toolOf(node);
                  return (
                    <li key={node.id}>
                      <b>{node.label[lang]}</b>
                      {tool && tool !== node.label[lang] ? <> ({tool})</> : null}: {node.sub[lang]}. {ui.status}: {caps[node.cap] === true ? ui.live : ui.progress}.
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          {children}
        </div>
      </details>
      {dialog}
    </figure>
  );
}
