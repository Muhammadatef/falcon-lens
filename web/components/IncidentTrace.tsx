"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { flatSteps, liveRun, parseAgentTrace, type AgentTrace, type NodeName, type TraceInterrupt, type TraceStep, type TraceTool } from "@/lib/agent-trace";
import { arLinkedChecks } from "@/lib/ar-count";
import { loadOne, type OneLoad } from "@/lib/agent-trace-api";
import { parseIncident, type Incident } from "@/lib/contracts";
import { formatTime, pick, translateMaybe } from "@/lib/i18n";
import { trT, type TraceKey } from "@/lib/i18n-trace";
import { usePrefs } from "@/lib/prefs";
import { IncidentOperatorLinks } from "./OperatorLinks";
import { DemoRibbon, SourceBadge, UntrustedText } from "./Chrome";
import { EvidencePackButton } from "./EvidencePackButton";
import { Icon, SeverityMark, type IconName } from "./Icon";

const useTT = () => {
  const { lang } = usePrefs();
  return (key: TraceKey, vars?: Record<string, string | number>) => trT(lang, key, vars);
};

const POLL_RUNNING_MS = 2500;
const POLL_WAITING_MS = 5000;
const NODE_ICON: Record<NodeName, IconName> = { enrich: "globe", compare: "scale", assess: "eye", summarise: "list", propose: "flag", act: "hand" };
const MODE_ICON: Record<TraceTool["mode"], IconName> = { read: "eye", internal_auto: "refresh", external_draft: "hand" };

type View = { state: "loading" } | { state: "not_found" } | { state: "not_connected" } | { state: "ok"; incident: Incident; trace: AgentTrace };

export function IncidentTrace({ incidentId, demo }: { incidentId: string; demo: boolean }) {
  const { t } = usePrefs();
  const tt = useTT();
  const [view, setView] = useState<View>({ state: "loading" });
  const [live, setLive] = useState(false);
  const l = { href: demo ? "/history?demo=1&tab=incidents" : "/history?tab=incidents" };

  const fetchAll = useCallback(
    async (signal: AbortSignal): Promise<View> => {
      if (demo) {
        const { DEMO_INCIDENT } = await import("@/lib/demo");
        const { DEMO_TRACE } = await import("@/lib/demo-trace");
        return { state: "ok", incident: DEMO_INCIDENT, trace: DEMO_TRACE };
      }
      // One same-origin, key-free call: the server adds its own read key and returns the allow-listed projection.
      const both: OneLoad<{ incident: Incident; trace: AgentTrace }> = await loadOne(`/api/public/incidents/${incidentId}`, parsePublicIncident, undefined, signal);
      if (both.state === "not_found") return { state: "not_found" };
      if (both.state !== "ok") return { state: "not_connected" };
      return { state: "ok", incident: both.value.incident, trace: both.value.trace };
    },
    [demo, incidentId],
  );

  // Poll while the agent is working or waiting; stop once the run has settled. Failures keep the last good view.
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const refresh = useRef<() => void>(() => undefined);
  useEffect(() => {
    const abort = new AbortController();
    let cancelled = false;
    const tick = async () => {
      const next = await fetchAll(abort.signal);
      if (cancelled) return;
      setView((prev) => (next.state === "not_connected" && prev.state === "ok" ? prev : next));
      const active = next.state === "ok" ? liveRun(next.trace) : null;
      const going = next.state === "ok" && (active !== null || next.incident.status === "open" || next.incident.status === "triaging");
      setLive(going);
      if (going && !demo) timer.current = setTimeout(() => void tick(), active?.status === "interrupted" ? POLL_WAITING_MS : POLL_RUNNING_MS);
    };
    refresh.current = () => {
      clearTimeout(timer.current);
      void tick();
    };
    void tick();
    return () => {
      cancelled = true;
      abort.abort();
      clearTimeout(timer.current);
    };
  }, [fetchAll, demo]);

  return (
    <>
      {demo ? <DemoRibbon /> : null}
      <main id="main">
        <section aria-labelledby="trace-title">
          <div className="wrap">
            <p><Link className="back" href={l.href} data-testid="trace-back">{tt("tr.back")}</Link></p>
            <div className="sec-head">
              <h1 className="page-title" id="trace-title">{tt("tr.title")}</h1>
              {demo ? <SourceBadge source="synthetic" /> : null}
              {view.state === "ok" ? <span className={live ? "pill pill--live pill--brand" : "pill"} data-testid="trace-live">{t(live ? "board.live" : "board.paused")}</span> : null}
            </div>
            <p className="sec-sub">{tt("tr.sub")}</p>
            {view.state === "loading" ? (
              <div className="card state" role="status" data-testid="trace-loading"><p>{tt("tr.loading")}</p><div className="sk" /><div className="sk" /></div>
            ) : view.state === "not_found" ? (
              <div className="card state" role="status" data-testid="trace-not-found">
                <Icon name="unplug" size={40} />
                <h2 className="h3">{tt("tr.nf.title")}</h2>
                <p className="muted">{tt("tr.nf.body")}</p>
              </div>
            ) : view.state === "not_connected" ? (
              <div className="card state" role="status" data-testid="trace-not-connected">
                <Icon name="unplug" size={40} />
                <h2 className="h3">{t("ops.nc.title")}</h2>
                <p className="muted">{t("ops.nc.body")}</p>
              </div>
            ) : (
              <>
                <Header incident={view.incident} />
                <IncidentOperatorLinks incidentId={view.incident.incident_id} />
                <Timeline incident={view.incident} trace={view.trace} demo={demo} />
              </>
            )}
          </div>
        </section>
      </main>
    </>
  );
}

function linkedLine(lang: string, n: number, tt: (k: TraceKey, v?: Record<string, string | number>) => string): string {
  if (n <= 0) return tt("tr.verdicts.zero");
  if (lang === "ar") return tt("tr.verdicts.n", { n: arLinkedChecks(n) });
  return n === 1 ? tt("tr.verdicts.one") : tt("tr.verdicts.n", { n });
}

function Header({ incident }: { incident: Incident }) {
  const { t, lang } = usePrefs();
  const tt = useTT();
  const title = pick(lang, incident.summary) || translateMaybe(lang, "type", incident.type);
  const rawReason = pick(lang, incident.severity_reason);
  const reason = rawReason.includes("[text removed]") || rawReason.includes("[أُزيل النص]") ? "" : rawReason;
  return (
    <article className="card incident" data-testid="trace-incident">
      <div className="inc-head" data-sev={incident.severity}>
        <span className="sev"><SeverityMark severity={incident.severity} size={20} />{t("sev")}: {t(`sev.${incident.severity}`)}</span>
        <h2 dir="auto" data-testid="trace-incident-title">{title}</h2>
        <SourceBadge source={incident.source} />
        <span className="pill">{translateMaybe(lang, "type", incident.type)}</span>
        <span className="pill" data-testid="trace-incident-status">{t(`is.${incident.status}`)}</span>
      </div>
      <div className="inc-grid">
        <div>
          {reason ? <p dir="auto">{reason}</p> : null}
          <p className="small" data-testid="trace-linked-count">{linkedLine(lang, incident.linked_verdicts.length, tt)}</p>
          <details className="tech-details" data-testid="trace-technical">
            <summary>{tt("tr.technical")}</summary>
            <div className="kv">
              <span>{tt("tr.id")}: <span className="mono" translate="no">{incident.incident_id}</span></span>
              {incident.brand_id ? <span>{tt("tr.brand")}: <span className="mono" translate="no">{incident.brand_id}</span></span> : null}
              {incident.rule_ids.length ? <span>{tt("tr.rules")}: <span className="mono" translate="no">{incident.rule_ids.join(", ")}</span></span> : null}
              {(incident.channels ?? []).map((c) => <span key={c} data-testid="incident-channel" translate="no">channel: <span className="mono">{c}</span></span>)}
            </div>
            <h3>{tt("tr.verdicts")}</h3>
            {incident.linked_verdicts.length === 0 ? <p className="muted">{t("i.none")}</p> : (
              <ul className="ind" data-testid="trace-verdicts">
                {incident.linked_verdicts.map((v) => <li key={v}><span className="mono" translate="no">{v}</span>{incident.source === "synthetic" ? null : <> <EvidencePackButton verdictId={v} final compact /></>}</li>)}
              </ul>
            )}
          </details>
        </div>
        <div>
          <h3>{t("i.ind")}</h3>
          {incident.indicators.length === 0 ? <p className="muted">{t("i.none")}</p> : (
            <ul className="ind">
              {incident.indicators.map((x, i) => (
                <li key={i}>
                  <span className="mono" translate="no">{x.value_defanged}</span>
                  <small>{x.kind} · {t("i.first")} {formatTime(lang, x.first_seen)}</small>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </article>
  );
}

function Timeline({ incident, trace, demo }: { incident: Incident; trace: AgentTrace; demo: boolean }) {
  const tt = useTT();
  const steps = flatSteps(trace);
  if (steps.length === 0) {
    // Accurate from the data: no run yet and the incident is still open/triaging means queued; a run without steps has just started.
    const key: TraceKey = trace.runs.length > 0 && trace.runs.some((r) => r.status === "running") ? "tr.starting" : trace.runs.length === 0 && (incident.status === "open" || incident.status === "triaging") ? "tr.queued" : "tr.empty";
    return <div className="card state" role="status" data-testid="trace-empty" data-state={key}><p>{tt(key)}</p></div>;
  }
  const runNo = new Map(trace.runs.map((r, i) => [r.run_id, i + 1]));
  const lastSeq = steps[steps.length - 1]!.step.seq;
  let prevRun = "";
  return (
    <ol className="trace" data-testid="trace-timeline">
      {steps.map(({ run, step }) => {
        const head = run.run_id !== prevRun && trace.runs.length > 1;
        prevRun = run.run_id;
        const waiting = step.status === "interrupted";
        const pending = incident.actions.filter((a) => a.status === "awaiting_approval");
        return (
          <li key={step.seq} className="trace-item" data-node={step.node} data-status={step.status} data-testid="trace-step">
            {head ? <p className="trace-run small" data-testid="trace-run">{tt("tr.run", { n: runNo.get(run.run_id) ?? 0 })} · {tt(`tr.status.${run.status}`)}</p> : null}
            {waiting ? (
              <WaitCard step={step} interrupt={run.interrupt} actions={pending} active={step.seq === lastSeq && pending.length > 0} demo={demo} />
            ) : (
              <StepCard step={step} />
            )}
          </li>
        );
      })}
    </ol>
  );
}

const money = (usd: number) => `$${usd.toFixed(4)}`;

function ToolChips({ tools }: { tools: TraceTool[] }) {
  const tt = useTT();
  if (tools.length === 0) return null;
  return (
    <ul className="chips" aria-label="tools">
      {tools.map((tool, i) => (
        <li key={i} className={`chip chip--${tool.mode}${tool.status === "error" ? " chip--err" : ""}${tool.origin === "rule_fallback" ? " chip--rule" : ""}`} data-testid="trace-tool" data-mode={tool.mode} data-origin={tool.origin ?? undefined}>
          <Icon name={MODE_ICON[tool.mode]} size={16} />
          <span className="mono" translate="no">{tool.name}</span>
          <span>{tool.origin === "rule_fallback" ? tt("tr.rule_draft") : tt(`tr.mode.${tool.mode}` as TraceKey)}</span>
        </li>
      ))}
    </ul>
  );
}

function StepCard({ step }: { step: TraceStep }) {
  const { lang } = usePrefs();
  const tt = useTT();
  const text = lang === "ar" ? step.summary_ar || step.summary_en : step.summary_en || step.summary_ar;
  const llm = step.llm;
  const route = !llm || llm.route === "none" || llm.fallback_template ? "none" : llm.route;
  return (
    <div className="card trace-card">
      <div className="trace-top">
        <span className="trace-dot"><Icon name={NODE_ICON[step.node]} size={22} /></span>
        <h3>{tt(`tr.node.${step.node}`)}</h3>
        <span className="pill mono" data-testid="step-duration">{step.duration_ms} ms</span>
        <span className={step.status === "failed" ? "pill pill--bad" : step.status === "running" ? "pill pill--live pill--brand" : "pill"} data-testid="step-status">{tt(`tr.status.${step.status}`)}</span>
      </div>
      {text ? <p dir="auto" className="trace-sum"><UntrustedText value={text} /></p> : null}
      <ToolChips tools={step.tools} />
      {step.generated_by ? <p className="small" data-testid="step-generated" data-by={step.generated_by}>{tt(`tr.gen.${step.generated_by}` as TraceKey)}</p> : null}
      {llm ? (
        <div className="trace-llm">
          <span className={`pill route route--${route}`} data-testid="llm-route" data-route={route}>{tt(`tr.route.${route}` as TraceKey)}</span>
          {llm.model && route !== "none" ? <span className="mono small" translate="no">{llm.model}</span> : null}
          <span className="small">{tt("tr.tokens")}: <b className="mono">{llm.tokens_in}/{llm.tokens_out}</b></span>
          <span className="small">{tt("tr.cost")}: <b className="mono">{money(llm.cost_usd)}</b></span>
          {llm.repaired ? <span className="pill">{tt("tr.repaired")}</span> : null}
          {llm.fallback_template ? <span className="pill pill--wait">{tt("tr.fallback")}</span> : null}
        </div>
      ) : null}
      <p className="small trace-budget">
        {tt("tr.budget")}: <span className="mono">{step.budget.steps_used} · {step.budget.tokens_used} · {step.budget.elapsed_ms} ms</span>
        {step.error_code ? <> · {tt("tr.error")}: <span className="mono" translate="no">{step.error_code}</span></> : null}
      </p>
    </div>
  );
}

function WaitCard({ step, interrupt, actions, active, demo }: { step: TraceStep; interrupt: TraceInterrupt | null; actions: { action_id: string; tool: string }[]; active: boolean; demo: boolean }) {
  const { lang } = usePrefs();
  const tt = useTT();
  const l = { href: demo ? "/ops?demo=1" : "/ops" };
  return (
    <div className="card trace-card trace-wait" data-testid="trace-interrupt">
      <div className="trace-top">
        <span className="trace-dot"><Icon name="hand" size={22} /></span>
        <h3>{tt("tr.wait.title")}</h3>
        <span className="pill pill--wait pill--live">{tt(`tr.node.${step.node}`)}</span>
        {interrupt?.waiting_since ? <span className="small">{tt("tr.wait.since")} {formatTime(lang, interrupt.waiting_since)}</span> : null}
      </div>
      <p>{tt("tr.wait.body")}</p>
      <ToolChips tools={step.tools} />
      {interrupt ? <p className="small"><span className="mono" translate="no">{translateMaybe(lang, "tool", interrupt.tool)}</span>{interrupt.pending_count && interrupt.pending_count > 1 ? ` (${interrupt.pending_count})` : ""}</p> : null}
      {active ? (
        <div className="op-btns">
          <ul className="chips" data-testid="trace-pending-actions">
            {actions.map((a) => <li key={a.action_id} className="chip chip--external_draft" translate="no">{translateMaybe(lang, "tool", a.tool)}</li>)}
          </ul>
          <p className="small" data-testid="trace-readonly">{tt("tr.wait.nokey")}</p>
          <Link className="btn btn--sm" href={l.href} data-testid="trace-ops-link">{tt("tr.wait.ops")}</Link>
        </div>
      ) : null}
    </div>
  );
}

/** Body of `/api/public/incidents/{id}`: `{ incident, trace }`, both already allow-listed server-side and re-checked by the strict guards. */
function parsePublicIncident(raw: unknown): { incident: Incident; trace: AgentTrace } | null {
  if (typeof raw !== "object" || raw === null) return null;
  const body = raw as { incident?: unknown; trace?: unknown };
  const incident = parseIncident(body.incident);
  const trace = parseAgentTrace(body.trace);
  return incident && trace ? { incident, trace } : null;
}
