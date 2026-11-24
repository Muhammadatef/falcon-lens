"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { traceHref } from "@/lib/agent-trace";
import { parseIncident, type Incident } from "@/lib/contracts";
import { checkHref, parseSummary, type VerdictSummary } from "@/lib/history";
import { hT, type HistoryKey } from "@/lib/i18n-history";
import { formatTime, pick, translateMaybe } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { useLiveList, type ListLoad } from "@/lib/use-live-list";
import { DemoRibbon, SourceBadge, UntrustedText } from "./Chrome";
import { Icon, SeverityMark } from "./Icon";

export type HistoryTab = "checks" | "incidents";

const useH = () => {
  const { lang } = usePrefs();
  return (key: HistoryKey, vars?: Record<string, string | number>) => hT(lang, key, vars);
};

const byCreated = (a: VerdictSummary, b: VerdictSummary) => b.created_at.localeCompare(a.created_at);
const byUpdated = (a: Incident, b: Incident) => b.updated_at.localeCompare(a.updated_at);

/** Public, read-only history of both agents: Investigator checks and Sentinel incidents, past and live. */
export function HistoryBoard({ demo, initialTab }: { demo: boolean; initialTab: HistoryTab }) {
  const { t } = usePrefs();
  const h = useH();
  const [tab, setTab] = useState<HistoryTab>(initialTab);
  const [attempt, setAttempt] = useState(0);
  const tabRefs = useRef<Record<HistoryTab, HTMLButtonElement | null>>({ checks: null, incidents: null });

  const checks = useLiveList<VerdictSummary>({ enabled: !demo && tab === "checks", attempt, listPath: "/api/public/checks", streamPath: "/api/public/checks/stream", event: "verdict", parse: parseSummary, idOf: (s) => s.verdict_id, compare: byCreated });
  const incidents = useLiveList<Incident>({ enabled: !demo && tab === "incidents", attempt, listPath: "/api/public/incidents", streamPath: "/api/public/incidents/stream", event: "incident", parse: parseIncident, idOf: (i) => i.incident_id, compare: byUpdated });
  const active = tab === "checks" ? checks : incidents;

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const next: HistoryTab = tab === "checks" ? "incidents" : "checks";
    setTab(next);
    tabRefs.current[next]?.focus();
  };

  const retry = () => setAttempt((n) => n + 1);

  return (
    <>
      {demo ? <DemoRibbon /> : null}
      <main id="main">
        <section aria-labelledby="history-title">
          <div className="wrap">
            <div className="sec-head">
              <h1 className="page-title" id="history-title">{h("hs.title")}</h1>
              {demo ? <SourceBadge source="synthetic" /> : null}
              {!demo && active.load.state === "ok" ? <span className={active.live ? "pill pill--live pill--brand" : "pill"} data-testid="history-live">{t(active.live ? "board.live" : "board.paused")}</span> : null}
            </div>
            <p className="sec-sub">{h("hs.sub")}</p>

            <div className="hs-tabs" role="tablist" aria-label={h("hs.tabs")}>
              {(["checks", "incidents"] as const).map((id) => (
                <button
                  key={id}
                  ref={(el) => { tabRefs.current[id] = el; }}
                  id={`tab-${id}`}
                  role="tab"
                  type="button"
                  aria-selected={tab === id}
                  aria-controls={`panel-${id}`}
                  tabIndex={tab === id ? 0 : -1}
                  data-testid={`tab-${id}`}
                  onClick={() => setTab(id)}
                  onKeyDown={onTabKey}
                >
                  <Icon name={id === "checks" ? "eye" : "flag"} size={20} />
                  {h(id === "checks" ? "hs.tab.checks" : "hs.tab.incidents")}
                </button>
              ))}
            </div>

            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} data-testid={`panel-${tab}`}>
              {tab === "checks" ? (
                <Panel<VerdictSummary> demo={demo} load={checks.load} onRetry={retry} empty={["hs.empty.checks.title", "hs.empty.checks.body"]} more={checks.more} moreBusy={checks.moreBusy} label="hs.checks.list" render={(items) => items.map((s) => <CheckRow key={s.verdict_id} s={s} demo={demo} />)} />
              ) : (
                <Panel<Incident> demo={demo} load={incidents.load} onRetry={retry} empty={["hs.empty.inc.title", "hs.empty.inc.body"]} more={incidents.more} moreBusy={incidents.moreBusy} label="hs.inc.list" render={(items) => items.map((i) => <IncidentRow key={i.incident_id} i={i} demo={demo} />)} />
              )}
            </div>
          </div>
        </section>
      </main>
    </>
  );
}

/** Demo rows are loaded lazily so they stay out of the live bundle path. */
function useDemo<T>(demo: boolean, tab: "checks" | "incidents"): ListLoad<T> | null {
  const [state, setState] = useState<ListLoad<T> | null>(null);
  useEffect(() => {
    if (!demo) return;
    let cancelled = false;
    void Promise.all([import("@/lib/demo-history"), import("@/lib/demo")]).then(([history, demoMod]) => {
      if (cancelled) return;
      const items = (tab === "checks" ? history.DEMO_CHECK_ROWS : [demoMod.DEMO_INCIDENT]) as unknown as T[];
      setState({ state: "ok", items, next: null });
    });
    return () => { cancelled = true; };
  }, [demo, tab]);
  return state;
}

interface PanelProps<T> {
  demo: boolean;
  load: ListLoad<T>;
  onRetry: () => void;
  empty: [HistoryKey, HistoryKey];
  more: () => void;
  moreBusy: boolean;
  label: HistoryKey;
  render: (items: T[]) => ReactNode;
}

function Panel<T>(p: PanelProps<T>) {
  const { t } = usePrefs();
  const h = useH();
  const demoLoad = useDemo<T>(p.demo, p.label === "hs.checks.list" ? "checks" : "incidents");
  const load: ListLoad<T> = p.demo ? (demoLoad ?? { state: "loading" }) : p.load;
  if (load.state === "loading") return <div className="card state" role="status" data-testid="history-loading"><p>{h("hs.loading")}</p><div className="sk" /><div className="sk" /></div>;
  if (load.state === "not_connected") {
    return (
      <div className="card state" role="status" data-testid="history-not-connected">
        <Icon name="unplug" size={40} />
        <h2 className="h3">{t("ops.nc.title")}</h2>
        <p className="muted">{t("ops.nc.body")}</p>
        <button className="btn" type="button" onClick={p.onRetry}><Icon name="refresh" size={20} />{t("retry")}</button>
      </div>
    );
  }
  if (load.items.length === 0) {
    return (
      <div className="card state" role="status" data-testid="history-empty">
        <Icon name="no_warning_signs" size={40} />
        <h2 className="h3">{h(p.empty[0])}</h2>
        <p className="muted">{h(p.empty[1])}</p>
      </div>
    );
  }
  const sample = (load.items as { source?: string }[]).some((x) => x.source && x.source !== "live");
  return (
    <>
      {sample ? <p className="small hs-note" data-testid="history-sample-note">{h("hs.sample.note")}</p> : null}
      <ul className="hs-list" aria-label={h(p.label)} data-testid="history-list">{p.render(load.items)}</ul>
      {load.next ? <button className="btn" type="button" onClick={p.more} disabled={p.moreBusy} data-testid="history-more">{h("hs.more")}</button> : null}
    </>
  );
}

function CheckRow({ s, demo }: { s: VerdictSummary; demo: boolean }) {
  const { t, lang } = usePrefs();
  const h = useH();
  const l = { href: checkHref(s.verdict_id, demo) };
  const title = s.display ?? (s.input_type === "url" ? t("kind.url") : `${t(`kind.${s.input_type}`)} · ${h("hs.msg.hidden")}`);
  return (
    <li className="card hs-row" data-testid="check-row" data-verdict={s.verdict} data-check-id={s.verdict_id}>
      <div className="hs-top">
        <span className="vpill"><Icon name={s.verdict} size={20} />{t(`v.${s.verdict}`)}</span>
        <span className="pill mono" data-testid="check-row-risk">{h("hs.risk")} {s.risk_score}</span>
        <SourceBadge source={s.source} />
        {s.degraded ? <span className="pill pill--wait">{h("hs.degraded")}</span> : null}
        <time className="small hs-time" dateTime={s.created_at}>{formatTime(lang, s.created_at, true)}</time>
      </div>
      <h2 className="hs-title">
        <Link className="hs-link" href={l.href} data-testid="check-link">
          <span className="mono" dir="auto" translate="no">{title}</span>
          <span className="sr-only"> · {h("hs.open")}</span>
        </Link>
      </h2>
      <div className="hs-meta">
        <span className="small">{t(`kind.${s.input_type}`)}</span>
        <ol className="tierbar" aria-label={h("hs.tier")}>
          {(["T0", "T1", "T2", "T3"] as const).map((tier) => (
            <li key={tier} data-run={s.agent.tiers_run.includes(tier) ? "true" : "false"} className="mono" translate="no">{tier}</li>
          ))}
        </ol>
        <span className="small">{h(`hs.route.${s.model_route}` as HistoryKey)}</span>
        {s.agent.extractor_ran ? <span className="pill">{h("hs.agent.extractor")}</span> : null}
        {s.agent.investigator_ran ? <span className="pill pill--brand">{h("hs.agent.investigator")}</span> : null}
        {s.agent.tool_calls > 0 ? <span className="small">{h("hs.agent.tools", { n: s.agent.tool_calls })}</span> : null}
        {s.agent.llm_calls > 0 ? <span className="small">{h("hs.agent.llm", { n: s.agent.llm_calls })}</span> : null}
      </div>
    </li>
  );
}

function IncidentRow({ i, demo }: { i: Incident; demo: boolean }) {
  const { t, lang } = usePrefs();
  const h = useH();
  const l = { href: traceHref(i.incident_id, demo) };
  const title = pick(lang, i.summary) || translateMaybe(lang, "type", i.type);
  return (
    <li className="card hs-row" data-testid="incident-row" data-sev={i.severity} data-incident-id={i.incident_id}>
      <div className="hs-top">
        <span className="sev" data-sev={i.severity}><SeverityMark severity={i.severity} size={20} />{t("sev")}: {t(`sev.${i.severity}`)}</span>
        <span className={i.status === "awaiting_approval" ? "pill pill--wait pill--live" : "pill"}>{t(`is.${i.status}`)}</span>
        <SourceBadge source={i.source} />
        <time className="small hs-time" dateTime={i.updated_at}>{h("hs.updated")} {formatTime(lang, i.updated_at, true)}</time>
      </div>
      <h2 className="hs-title">
        <Link className="hs-link" href={l.href} data-testid="incident-link">
          <UntrustedText value={title} />
          <span className="sr-only"> · {h("hs.open")}</span>
        </Link>
      </h2>
      <div className="hs-meta">
        <span className="pill">{translateMaybe(lang, "type", i.type)}</span>
        <span className="small mono" dir="ltr" translate="no">{i.incident_id.slice(-8)}</span>
        <span className="small" data-testid="incident-counts">{h("hs.inc.counts", { v: i.linked_verdicts.length, i: i.indicators.length, a: i.actions.length })}</span>
        {i.rule_ids.map((r) => <span key={r} className="small mono" translate="no">rule:{r}</span>)}
      </div>
    </li>
  );
}
