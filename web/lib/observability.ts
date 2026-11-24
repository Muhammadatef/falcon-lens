/**
 * Operator-only deep links into the local observability tools (Arize Phoenix traces, Grafana logs and
 * dashboards, Prometheus alerts). These tools run on the operator's machine and are never exposed
 * publicly; the links are rendered only when an operator key is present in sessionStorage (set on /ops).
 * Pure functions, no network: the base URLs come from `/api/obs-config` (server env, read at request time).
 */
import { INCIDENT_ID_RE, VERDICT_ID_RE } from "./contracts";

export const TRACE_ID_RE = /^[0-9a-f]{32}$/;
/** Phoenix's id of the built-in `default` project (a GraphQL global id, base64 of "Project:1"). */
export const DEFAULT_PHOENIX_PROJECT_ID = "UHJvamVjdDox";
const PROJECT_ID_RE = /^[A-Za-z0-9=_-]{1,64}$/;
/** 127.0.0.1, not localhost: localhost resolves to IPv6 first on the dev Mac and the ports bind IPv4 only. */
export const DEFAULTS = { phoenix: "http://127.0.0.1:6006", grafana: "http://127.0.0.1:3001", prometheus: "http://127.0.0.1:9090" } as const;

export interface ObsConfig {
  phoenix: string;
  grafana: string;
  prometheus: string;
  phoenixProject: string;
}

/** Keeps only an http(s) origin (+ optional path prefix); anything else falls back to the default. */
export function cleanBase(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback;
  try {
    const u = new URL(value.trim());
    if (u.protocol !== "http:" && u.protocol !== "https:") return fallback;
    if (u.username || u.password || u.search || u.hash) return fallback;
    return `${u.origin}${u.pathname.replace(/\/+$/, "")}`;
  } catch {
    return fallback;
  }
}

export function configFromEnv(env: Record<string, string | undefined>): ObsConfig {
  const project = env.FL_PHOENIX_PROJECT_ID?.trim() ?? "";
  return {
    phoenix: cleanBase(env.FL_PHOENIX_UI_URL, DEFAULTS.phoenix),
    grafana: cleanBase(env.FL_GRAFANA_UI_URL, DEFAULTS.grafana),
    prometheus: cleanBase(env.FL_PROMETHEUS_UI_URL, DEFAULTS.prometheus),
    phoenixProject: PROJECT_ID_RE.test(project) ? project : DEFAULT_PHOENIX_PROJECT_ID,
  };
}

/** Re-validates a config received over the wire (never trust it blindly). */
export function parseConfig(raw: unknown): ObsConfig | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const project = typeof r.phoenixProject === "string" && PROJECT_ID_RE.test(r.phoenixProject) ? r.phoenixProject : DEFAULT_PHOENIX_PROJECT_ID;
  return { phoenix: cleanBase(r.phoenix, DEFAULTS.phoenix), grafana: cleanBase(r.grafana, DEFAULTS.grafana), prometheus: cleanBase(r.prometheus, DEFAULTS.prometheus), phoenixProject: project };
}

/** Phoenix UI deep link to one trace, or null when the id is not a W3C trace id. */
export function phoenixTraceUrl(cfg: ObsConfig, traceId: string | undefined | null): string | null {
  if (typeof traceId !== "string" || !TRACE_ID_RE.test(traceId)) return null;
  return `${cfg.phoenix}/projects/${encodeURIComponent(cfg.phoenixProject)}/traces/${traceId}`;
}

export function phoenixHomeUrl(cfg: ObsConfig): string {
  return `${cfg.phoenix}/projects/${encodeURIComponent(cfg.phoenixProject)}`;
}

export interface TimeWindow {
  from: number;
  to: number;
}

const MIN = 60_000;

/** Time window around a check: from (finished - duration - 1 min) to (finished + 2 min), epoch ms. Null for bad input. */
export function checkWindow(createdAt: string, latencyMs: number): TimeWindow | null {
  const end = Date.parse(createdAt);
  if (!Number.isFinite(end)) return null;
  const dur = Number.isFinite(latencyMs) && latencyMs > 0 ? Math.min(latencyMs, 30 * MIN) : 0;
  return { from: end - dur - MIN, to: end + 2 * MIN };
}

/** Grafana Explore on Loki, filtered to one verdict (or incident) id over `win`. Null for an invalid id. */
export function grafanaLogsUrl(cfg: ObsConfig, id: string, win: TimeWindow | null, kind: "verdict" | "incident" = "verdict"): string | null {
  const ok = kind === "verdict" ? VERDICT_ID_RE.test(id) : INCIDENT_ID_RE.test(id);
  if (!ok) return null;
  const expr = `{service=~".+"} |= "${id}"`;
  const range = win ? { from: String(Math.round(win.from)), to: String(Math.round(win.to)) } : { from: "now-6h", to: "now" };
  const panes = { a: { datasource: "loki", queries: [{ refId: "A", expr, queryType: "range", datasource: { type: "loki", uid: "loki" } }], range } };
  return `${cfg.grafana}/explore?schemaVersion=1&panes=${encodeURIComponent(JSON.stringify(panes))}&orgId=1`;
}

/** Command overview dashboard (uid `fl-command-overview`) around `win`. */
export function grafanaOverviewUrl(cfg: ObsConfig, win: TimeWindow | null): string {
  const q = win ? `?orgId=1&from=${Math.round(win.from)}&to=${Math.round(win.to)}` : "?orgId=1";
  return `${cfg.grafana}/d/fl-command-overview/${q}`;
}

export const grafanaHomeUrl = (cfg: ObsConfig): string => `${cfg.grafana}/dashboards`;
export const prometheusAlertsUrl = (cfg: ObsConfig): string => `${cfg.prometheus}/alerts`;
