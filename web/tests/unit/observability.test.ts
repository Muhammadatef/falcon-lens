import { describe, expect, it } from "vitest";
import { parseSummary } from "../../lib/history";
import {
  DEFAULT_PHOENIX_PROJECT_ID,
  DEFAULTS,
  checkWindow,
  cleanBase,
  configFromEnv,
  grafanaLogsUrl,
  grafanaOverviewUrl,
  parseConfig,
  phoenixTraceUrl,
} from "../../lib/observability";
import { toPublicCheckSummary, toPublicTrace } from "../../lib/public-history";

const CFG = configFromEnv({});
const VID = "vd_01KB0DEM0DATA0000000000001";
const TID = "0123456789abcdef0123456789abcdef";

describe("observability links", () => {
  it("defaults use 127.0.0.1, never localhost", () => {
    expect(CFG.phoenix).toBe("http://127.0.0.1:6006");
    expect(CFG.grafana).toBe("http://127.0.0.1:3001");
    expect(CFG.phoenixProject).toBe(DEFAULT_PHOENIX_PROJECT_ID);
    expect(Object.values(DEFAULTS).join()).not.toContain("localhost");
  });

  it("config comes from env and falls back on anything that is not a plain http(s) origin", () => {
    expect(configFromEnv({ FL_PHOENIX_UI_URL: "http://127.0.0.1:6107/", FL_GRAFANA_UI_URL: "https://g.example/graf/" }).phoenix).toBe("http://127.0.0.1:6107");
    expect(configFromEnv({ FL_GRAFANA_UI_URL: "https://g.example/graf/" }).grafana).toBe("https://g.example/graf");
    for (const bad of ["javascript:alert(1)", "ftp://x", "http://u:p@h", "http://h/?a=1", "not a url", ""]) expect(cleanBase(bad, "http://fallback")).toBe("http://fallback");
    expect(configFromEnv({ FL_PHOENIX_PROJECT_ID: "bad id/../" }).phoenixProject).toBe(DEFAULT_PHOENIX_PROJECT_ID);
    expect(parseConfig({ phoenix: "javascript:1", grafana: 3, phoenixProject: "x y" })).toEqual(CFG);
    expect(parseConfig(null)).toBeNull();
  });

  it("builds the Phoenix trace URL only for a valid W3C trace id", () => {
    expect(phoenixTraceUrl(CFG, TID)).toBe(`http://127.0.0.1:6006/projects/${DEFAULT_PHOENIX_PROJECT_ID}/traces/${TID}`);
    for (const bad of [undefined, null, "", "xyz", TID.toUpperCase(), `${TID}0`, TID.slice(1), `${TID.slice(0, 31)}/`, "../../etc/passwd"]) expect(phoenixTraceUrl(CFG, bad)).toBeNull();
  });

  it("builds a Grafana Explore link on Loki with the verdict id, window and proper encoding", () => {
    const win = checkWindow("2026-11-24T10:00:00Z", 4000)!;
    expect(win.to - win.from).toBe(4000 + 60_000 + 120_000);
    const url = grafanaLogsUrl(CFG, VID, win)!;
    expect(url.startsWith("http://127.0.0.1:3001/explore?schemaVersion=1&panes=")).toBe(true);
    const panes = JSON.parse(decodeURIComponent(new URL(url).searchParams.get("panes")!));
    expect(panes.a.datasource).toBe("loki");
    expect(panes.a.queries[0].expr).toBe(`{service=~".+"} |= "${VID}"`);
    expect(panes.a.range).toEqual({ from: String(win.from), to: String(win.to) });
    expect(url).not.toContain('"'); // everything inside panes is percent-encoded
  });

  it("rejects ids that could break out of the LogQL string", () => {
    expect(grafanaLogsUrl(CFG, 'vd_x" or {a=~".+"}', null)).toBeNull();
    expect(grafanaLogsUrl(CFG, VID, null, "incident")).toBeNull();
    expect(grafanaLogsUrl(CFG, "inc_01KB0DEM0DATA0000000000001", null, "incident")).not.toBeNull();
  });

  it("links the Command overview dashboard (uid fl-command-overview) around the check", () => {
    const win = checkWindow("2026-11-24T10:00:00Z", 0)!;
    expect(grafanaOverviewUrl(CFG, win)).toBe(`http://127.0.0.1:3001/d/fl-command-overview/?orgId=1&from=${win.from}&to=${win.to}`);
    expect(grafanaOverviewUrl(CFG, null)).toBe("http://127.0.0.1:3001/d/fl-command-overview/?orgId=1");
    expect(checkWindow("not a date", 5)).toBeNull();
  });
});

describe("trace_id passes the projections only when it is 32 hex", () => {
  const base = { verdict_id: VID, created_at: "2026-11-24T10:00:00Z", input_type: "url", verdict: "dangerous", risk_score: 90, degraded: false, degraded_reasons: [], tier_reached: "T2", model_route: "none", source: "live", agent: {} };
  it("history summary and public summary", () => {
    expect(parseSummary({ ...base, trace_id: TID })?.trace_id).toBe(TID);
    expect(parseSummary({ ...base, trace_id: "<script>" })?.trace_id).toBeUndefined();
    expect(toPublicCheckSummary({ ...base, trace_id: TID })?.trace_id).toBe(TID);
    expect(toPublicCheckSummary({ ...base, trace_id: "nope" })?.trace_id).toBeUndefined();
  });
  it("public agent trace runs", () => {
    const inc = "inc_01KB0DEM0DATA0000000000001";
    const run = { run_id: "run_1", started_at: "2026-11-24T10:00:00Z", finished_at: null, status: "completed", steps: [], interrupt: null };
    const out = toPublicTrace({ incident_id: inc, runs: [{ ...run, trace_id: TID }, { ...run, run_id: "run_2", trace_id: "bad" }] }) as { runs: { trace_id?: string }[] };
    expect(out.runs[0]!.trace_id).toBe(TID);
    expect(out.runs[1]!.trace_id).toBeUndefined();
  });
});
