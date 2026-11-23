"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CapBadge } from "@/components/CapBadge";
import { BIZ_GROUPS, FULL_GROUPS, NODE_BY_ID, idsOf, relatedOf, type GroupDef, type GroupId } from "@/lib/arch-graph";
import type { Lang } from "@/lib/contracts";
import { at, NODE_TEXT, TOOL_IO, type ArchKey } from "@/lib/i18n-arch";

type Caps = Record<string, boolean>;
type View = "full" | "biz";

const isTool = (group: GroupId) => group === "tools_inv" || group === "tools_sen";

/**
 * The connected, interactive architecture. Plain HTML buttons in lanes (no third-party library, no inline styles,
 * no raw-HTML injection), so it works under the strict nonce CSP. Hover or focus shows a tooltip
 * (one plain sentence, one technical sentence); click, Enter or Space opens the details panel; Esc closes.
 * Connections are animated only when the visitor has not asked for reduced motion (CSS).
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

  const active = open ?? tip;
  const related = useMemo(() => new Set(active ? relatedOf(active, visible) : []), [active, visible]);

  const renderNode = (id: string) => {
    const def = NODE_BY_ID.get(id)!;
    const text = NODE_TEXT[lang][id]!;
    const live = caps[def.cap] === true;
    const tool = isTool(def.group);
    const mode = TOOL_IO[id]?.mode;
    return (
      <li
        key={id}
        className="an-item"
        data-rel={related.has(id) ? "true" : undefined}
        data-active={active === id ? "true" : undefined}
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
          <span className={tool ? "an-name mono" : "an-name"}>{text.name}</span>
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

  const panelDef = open ? NODE_BY_ID.get(open) : null;
  const panelText = open ? NODE_TEXT[lang][open] : null;
  const io = open ? TOOL_IO[open] : undefined;
  const slug = panelDef?.doc;
  const panel = panelDef && panelText ? (
    <>
      <div className="ap-scrim" aria-hidden="true" onClick={close} />
      <div className="ap" role="dialog" aria-modal="false" aria-labelledby="ap-title" data-testid="arch-panel" data-node={open ?? undefined} data-kind={panelDef.kind}>
        <header className="ap-head">
          <div>
            <span className="ap-kind">{t(`arch.kind.${panelDef.kind}` as ArchKey)}</span>
            <h2 id="ap-title" className={isTool(panelDef.group) ? "mono" : undefined}>{panelText.name}</h2>
            <CapBadge live={caps[panelDef.cap] === true} lang={lang} />
          </div>
          <button type="button" ref={closeRef} className="ap-close" onClick={close} aria-label={t("arch.panel.close")} data-testid="arch-panel-close">
            <span aria-hidden="true">×</span>
          </button>
        </header>
        <div className="ap-body">
          <section>
            <h3>{t("arch.panel.what")}</h3>
            <p>{panelText.plain}</p>
            {view === "full" ? <p className="ap-tech">{panelText.tech}</p> : null}
          </section>
          <section>
            <h3>{t("arch.panel.why")}</h3>
            <p>{panelText.why}</p>
          </section>
          <section className="ap-never">
            <h3>{t("arch.panel.never")}</h3>
            <p>{panelText.never}</p>
          </section>
          {view === "full" ? (
            <>
              {io?.mode ? (
                <section>
                  <h3>{t("arch.panel.mode")}</h3>
                  <p>{t(`arch.mode.${io.mode}` as ArchKey)}</p>
                </section>
              ) : null}
              <section>
                <h3>{t("arch.panel.inputs")}</h3>
                {io ? <p className="mono ap-io">{io.inputs}</p> : <p>{panelText.inputs}</p>}
              </section>
              <section>
                <h3>{t("arch.panel.outputs")}</h3>
                {io ? <p className="mono ap-io">{io.outputs}</p> : <p>{panelText.outputs}</p>}
                {io?.budgetMs ? <p className="faint">{t("arch.panel.budget")}: <span className="mono">{io.budgetMs} {t("arch.panel.ms")}</span></p> : null}
              </section>
              <section>
                <h3>{t("arch.panel.code")}</h3>
                <ul className="ap-code">
                  {[panelDef.repo, ...(panelDef.repoMore ?? [])].map((p) => (
                    <li key={p}><code className="mono">{p}</code></li>
                  ))}
                </ul>
              </section>
            </>
          ) : null}
          <section>
            <h3>{t("arch.panel.docs")}</h3>
            <p>
              <Link href={`/docs/${slug}`} className="ap-link">{t("arch.docs.link")}</Link>
              {view === "full" ? <> · <code className="mono">{panelDef.docFile}</code></> : null}
            </p>
          </section>
          <section>
            <h3>{t("arch.panel.related")}</h3>
            <ul className="ap-rel">
              {relatedOf(panelDef.id, visible).map((rid) => (
                <li key={rid}>
                  <button type="button" className="ap-rel-btn" onClick={() => openNode(rid)} data-testid={`arch-rel-${rid}`}>
                    {NODE_TEXT[lang][rid]!.name}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </>
  ) : null;

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
