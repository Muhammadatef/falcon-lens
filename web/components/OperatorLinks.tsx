"use client";

import { obT } from "@/lib/i18n-obs";
import { checkWindow, grafanaLogsUrl, grafanaOverviewUrl, phoenixHomeUrl, phoenixTraceUrl, prometheusAlertsUrl, grafanaHomeUrl, type TimeWindow } from "@/lib/observability";
import { usePrefs } from "@/lib/prefs";
import { useOperatorObs } from "@/lib/use-obs";

interface Props {
  /** `vd_...` for a check, `inc_...` for an incident. */
  id: string;
  kind: "verdict" | "incident";
  /** W3C trace id from the verdict or the latest agent run; absent when tracing was off. */
  traceId?: string;
  /** When the check finished (ISO) and how long it took, for the Grafana time range. */
  createdAt?: string;
  latencyMs?: number;
  /** Incidents: explicit window (epoch ms). */
  window?: TimeWindow | null;
}

const LIST = { display: "flex", flexWrap: "wrap", gap: "0.5rem 1.25rem", listStyle: "none", padding: 0, margin: 0 } as const;

/** Operator-only deep links to this check's / incident's trace in Phoenix and its logs and dashboard in Grafana. Renders nothing for the public. */
export function OperatorLinks({ id, kind, traceId, createdAt, latencyMs, window: win }: Props) {
  const { lang } = usePrefs();
  const cfg = useOperatorObs();
  if (!cfg) return null;
  const range = win ?? (createdAt ? checkWindow(createdAt, latencyMs ?? 0) : null);
  const trace = phoenixTraceUrl(cfg, traceId);
  const logs = grafanaLogsUrl(cfg, id, range, kind);
  return (
    <aside className="card" data-testid="operator-links" aria-label={obT(lang, "ob.title")} style={{ marginBlock: "1rem" }}>
      <p className="small">{obT(lang, "ob.title")}</p>
      <ul style={LIST}>
        <li>
          {trace ? (
            <a href={trace} target="_blank" rel="noopener noreferrer" data-testid="link-phoenix">{obT(lang, "ob.trace")}</a>
          ) : (
            <span className="small" data-testid="no-trace">{obT(lang, "ob.notrace")}</span>
          )}
        </li>
        {logs ? (
          <li><a href={logs} target="_blank" rel="noopener noreferrer" data-testid="link-grafana-logs">{obT(lang, "ob.logs")}</a></li>
        ) : null}
        <li><a href={grafanaOverviewUrl(cfg, range)} target="_blank" rel="noopener noreferrer" data-testid="link-grafana-dash">{obT(lang, "ob.dash")}</a></li>
      </ul>
    </aside>
  );
}

/** Incident page: links for the latest agent run that carries a trace id; Grafana window spans all runs. */
export function IncidentOperatorLinks({ incidentId, runs }: { incidentId: string; runs: { trace_id?: string; started_at: string; finished_at: string | null }[] }) {
  const starts = runs.map((r) => Date.parse(r.started_at)).filter(Number.isFinite);
  const ends = runs.map((r) => Date.parse(r.finished_at ?? r.started_at)).filter(Number.isFinite);
  const win = starts.length && ends.length ? { from: Math.min(...starts) - 60_000, to: Math.max(...ends) + 120_000 } : null;
  const traceId = [...runs].reverse().find((r) => r.trace_id)?.trace_id;
  return <OperatorLinks id={incidentId} kind="incident" traceId={traceId} window={win} />;
}

/** Small trace icon for a /history row (operators only). */
export function RowTraceLink({ traceId }: { traceId?: string }) {
  const { lang } = usePrefs();
  const cfg = useOperatorObs();
  const href = cfg ? phoenixTraceUrl(cfg, traceId) : null;
  if (!href) return null;
  const label = obT(lang, "ob.row");
  return (
    <a className="pill" href={href} target="_blank" rel="noopener noreferrer" data-testid="row-trace-link" aria-label={label} title={label}>
      <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M2 3h5v3H2zM9 10h5v3H9zM7 4.5h2.5V11.5" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
    </a>
  );
}

/** /ops "Monitoring" card: the three local tools. Shown with an operator key only. */
export function MonitoringCard() {
  const { lang } = usePrefs();
  const cfg = useOperatorObs();
  if (!cfg) return null;
  return (
    <section className="card" data-testid="monitoring-card" aria-labelledby="monitoring-title">
      <h2 id="monitoring-title">{obT(lang, "ob.mon.title")}</h2>
      <p className="small">{obT(lang, "ob.mon.sub")}</p>
      <ul style={LIST}>
        <li><a href={grafanaHomeUrl(cfg)} target="_blank" rel="noopener noreferrer" data-testid="mon-grafana">{obT(lang, "ob.mon.grafana")}</a></li>
        <li><a href={prometheusAlertsUrl(cfg)} target="_blank" rel="noopener noreferrer" data-testid="mon-prometheus">{obT(lang, "ob.mon.alerts")}</a></li>
        <li><a href={phoenixHomeUrl(cfg)} target="_blank" rel="noopener noreferrer" data-testid="mon-phoenix">{obT(lang, "ob.mon.phoenix")}</a></li>
      </ul>
    </section>
  );
}
