"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchPanel } from "@/components/arch/ArchPanel";
import { FlowControls, type FlowStatus } from "@/components/arch/FlowControls";
import { ToolBadge } from "@/components/arch/ToolBadge";
import { FLOW_UI, GRAPH_BADGE, badgeTool } from "@/lib/arch-flow";
import { BIZ_GROUPS, FULL_GROUPS, NODE_BY_ID, idsOf, relatedOf, type GroupDef, type GroupId } from "@/lib/arch-graph";
import type { Lang } from "@/lib/contracts";
import { at, NODE_TEXT, TOOL_IO, type ArchKey } from "@/lib/i18n-arch";
import { LOGO_PATHS } from "@/lib/tool-logos.gen";

type Caps = Record<string, boolean>;
type View = "full" | "biz";

/** One step of the lane diagram's own walk-through rests this long (ms). */
const WALK_MS = 1500;
const isTool = (group: GroupId) => group === "tools_inv" || group === "tools_sen";

/**
 * The connected, interactive architecture. Plain HTML buttons in lanes (no third-party library, no inline styles,
 * no raw-HTML injection), so it works under the strict nonce CSP. Hover or focus shows a tooltip
 * (one plain sentence, one technical sentence); click, Enter or Space opens the details panel; Esc closes.
 * Connections are animated only when the visitor has not asked for reduced motion (CSS). Each box carries the
 * badge of the tool it runs on (lib/arch-flow.ts GRAPH_BADGE), and the player bar walks the request through both
 * agents one box at a time: Play starts it (it never starts by itself), and the steps can be read one by one.
 */
export function ArchDiagram({ lang, caps, view }: { lang: Lang; caps: Caps; view: View }) {
  const groups = view === "full" ? FULL_GROUPS : BIZ_GROUPS;
  const visible = useMemo(() => new Set(idsOf(groups)), [groups]);
  const [open, setOpen] = useState<string | null>(null);
  const [tip, setTip] = useState<string | null>(null);
  const [align, setAlign] = useState<"start" | "end">("start");
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastOpener = useRef<string | null>(null);
  const skipHref = `#arch-end-${view}`;
  const t = (key: ArchKey, vars?: Record<string, string | number>) => at(lang, key, vars);

  const showTip = useCallback((id: string) => {
    const el = nodeRefs.current.get(id);
    if (el) {
      const r = el.getBoundingClientRect();
      const width = 304;
      const rtl = document.documentElement.dir === "rtl";
      const room = rtl ? r.right : window.innerWidth - r.left;
      setAlign(room >= width ? "start" : "end");
    }
    setTip(id);
  }, []);

  const openNode = useCallback((id: string) => {
    lastOpener.current = id;
    setTip(null);
    setOpen(id);
  }, []);

  const close = useCallback(() => {
    setOpen(null);
    const id = lastOpener.current;
    if (id) requestAnimationFrame(() => nodeRefs.current.get(id)?.focus());
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (open) close();
      else setTip(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);

  // The walk: the request path through the visible flow lanes, the Investigator first, then the Sentinel.
  const walk = useMemo(() => groups.filter((g) => g.flow && (g.id === "inv" || g.id === "sen")).flatMap((g) => g.segments.flatMap((seg) => [...seg.ids])), [groups]);
  const [walkAt, setWalkAt] = useState(-1);
  const [walkStatus, setWalkStatus] = useState<FlowStatus>("idle");
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      setReduced(mq.matches);
      if (mq.matches) setWalkStatus((cur) => (cur === "playing" ? "paused" : cur));
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  useEffect(() => {
    if (walkStatus !== "playing") return;
    const timer = window.setTimeout(() => {
      if (walkAt >= walk.length - 1) setWalkStatus("done");
      else setWalkAt(walkAt + 1);
    }, walkAt < 0 ? 200 : WALK_MS);
    return () => window.clearTimeout(timer);
  }, [walkStatus, walkAt, walk.length]);
  const walkToggle = () => {
    if (walkStatus === "playing") return setWalkStatus("paused");
    if (walkStatus === "done") setWalkAt(-1);
    setWalkStatus("playing");
  };
  const walkReplay = () => {
    setWalkAt(-1);
    setWalkStatus("playing");
  };
  const walkTo = (index: number) => {
    if (index < 0 || index > walk.length - 1) return;
    setWalkStatus("paused");
    setWalkAt(index);
  };
  const walkId = walkAt >= 0 ? walk[walkAt] : undefined;

  const active = open ?? tip;
  const related = useMemo(() => new Set(active ? relatedOf(active, visible) : []), [active, visible]);

  const renderNode = (id: string) => {
    const def = NODE_BY_ID.get(id)!;
    const text = NODE_TEXT[lang][id]!;
    const live = caps[def.cap] === true;
    const tool = isTool(def.group);
    const mode = TOOL_IO[id]?.mode;
    const badge = GRAPH_BADGE[id];
    const badgeName = badge ? badgeTool(badge, LOGO_PATHS) : null;
    return (
      <li
        key={id}
        className="an-item"
        data-rel={related.has(id) ? "true" : undefined}
        data-active={active === id ? "true" : undefined}
        data-flow={walkId === id ? "true" : undefined}
        onMouseEnter={() => showTip(id)}
        onMouseLeave={() => setTip((cur) => (cur === id ? null : cur))}
      >
        <button
          type="button"
          ref={(el) => {
            if (el) nodeRefs.current.set(id, el);
            else nodeRefs.current.delete(id);
          }}
          className="an"
          data-kind={def.kind}
          data-live={live ? "true" : "false"}
          data-tool={tool ? "true" : undefined}
          data-mode={mode}
          data-testid={`arch-node-${id}`}
          aria-haspopup="dialog"
          aria-expanded={open === id}
          aria-describedby={`tip-${id}`}
          onClick={() => openNode(id)}
          onFocus={() => showTip(id)}
          onBlur={() => setTip((cur) => (cur === id ? null : cur))}
        >
          <span className="an-main">
            {badge ? <ToolBadge badge={badge} size="sm" /> : null}
            <span className={tool ? "an-name mono" : "an-name"}>{text.name}</span>
          </span>
          {badgeName ? <span className="vh">{FLOW_UI[lang].panelTool}: {badgeName}</span> : null}
          <i className="an-dot" aria-hidden="true" />
          <span className="vh">{t("arch.status")}: {live ? (lang === "ar" ? "يعمل الآن" : "Live") : lang === "ar" ? "قيد الإنجاز" : "In progress"}</span>
        </button>
        <span role="tooltip" id={`tip-${id}`} className="an-tip" data-open={tip === id ? "true" : "false"} data-align={align} data-testid={`arch-tip-${id}`}>
          <b>{text.plain}</b>
          {view === "full" ? <span>{text.tech}</span> : null}
        </span>
      </li>
    );
  };

  const renderGroup = (g: GroupDef) => {
    const count = g.segments.reduce((sum, s) => sum + s.ids.length, 0);
    const title = t(`arch.group.${g.id}` as ArchKey, { n: count });
    return (
      <section key={g.id} className="ag" data-group={g.id} data-flow={g.flow ? "true" : "false"} aria-labelledby={`ag-${g.id}`} data-testid={`arch-group-${g.id}`}>
        <h3 id={`ag-${g.id}`} className="ag-title">{title}</h3>
        {g.segments.map((seg, i) => (
          <div className="ag-seg" data-seg={seg.label ?? "plain"} key={i}>
            {seg.label && view === "full" ? <p className="ag-seg-label">{t(`arch.seg.${seg.label}` as ArchKey)}</p> : null}
            <ul className={g.flow ? "ag-list ag-list--flow" : "ag-list"}>{seg.ids.map(renderNode)}</ul>
          </div>
        ))}
      </section>
    );
  };

  const byId = (id: GroupId) => groups.find((g) => g.id === id);
  const bridge = (kind: "entry" | "events") => (
    <div className="ab" data-bridge={kind} aria-hidden="true">
      <span className="ab-line" />
      <span className="ab-label">{t(`arch.bridge.${kind}` as ArchKey)}</span>
    </div>
  );

  const panel = open ? <ArchPanel id={open} lang={lang} caps={caps} view={view} visible={visible} onClose={close} onOpen={openNode} closeRef={closeRef} /> : null;

  const legend = (
    <ul className="legend arch-legend" aria-label={t("arch.legend")}>
      {(["code", "llm", "gate"] as const).map((k) => (
        <li key={k} data-kind={k}><i aria-hidden="true" />{t(`arch.kind.${k}` as ArchKey)}</li>
      ))}
      <li><i className="an-dot" data-live="true" aria-hidden="true" />{lang === "ar" ? "يعمل الآن" : "Live"}</li>
      <li><i className="an-dot" data-live="false" aria-hidden="true" />{lang === "ar" ? "قيد الإنجاز" : "In progress"}</li>
    </ul>
  );

  return (
    <div className="arch" data-view={view} data-testid="arch-diagram">
      <p className="arch-hint small muted">{t("arch.hint")}</p>
      {legend}
      {open ? null : <a className="arch-skip" href={skipHref}>{t("arch.skip")}</a>}
      <FlowControls lang={lang} status={walkStatus} step={walkAt} total={walk.length} caption={walkId ? NODE_TEXT[lang][walkId]!.plain : FLOW_UI[lang][reduced ? "idleStatic" : "idle"]} reduced={reduced} onToggle={walkToggle} onReplay={walkReplay} onPrev={() => walkTo(walkAt - 1)} onNext={() => walkTo(walkAt + 1)} testid={`arch-walk-${view}`} />
      <p className="af-note">{FLOW_UI[lang].logos}</p>
      <div role="group" aria-label={t(view === "full" ? "arch.diagram.label" : "arch.diagram.biz.label")} className="arch-body">
        {view === "full" && byId("entry") ? (
          <>
            {renderGroup(byId("entry")!)}
            {bridge("entry")}
          </>
        ) : null}
        <div className="arch-agents">
          {renderGroup(byId("inv")!)}
          {bridge("events")}
          {renderGroup(byId("sen")!)}
        </div>
        {view === "full" ? (
          <>
            <div className="arch-pair">{renderGroup(byId("tools_inv")!)}{renderGroup(byId("tools_sen")!)}</div>
            <div className="arch-trio">{renderGroup(byId("llm")!)}{renderGroup(byId("obs")!)}{renderGroup(byId("integ")!)}</div>
          </>
        ) : (
          <div className="arch-pair">{renderGroup(byId("biz_tools")!)}{renderGroup(byId("biz_found")!)}</div>
        )}
      </div>
      <span id={`arch-end-${view}`} tabIndex={-1} className="arch-end" />
      {panel}
    </div>
  );
}
