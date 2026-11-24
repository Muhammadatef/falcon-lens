import AxeBuilder from "@axe-core/playwright";
import { DEMO_DANGEROUS, DEMO_INCIDENT } from "../../lib/demo";
import { DEMO_TRACE } from "../../lib/demo-trace";
import { expect, newIncidentId, newVerdictId, setPrefs, test, useBoards } from "./helpers";

const TID = "0123456789abcdef0123456789abcdef";
const PROJECT = "UHJvamVjdDox";
const PHOENIX = "http://127.0.0.1:6006";
const GRAFANA = "http://127.0.0.1:3001";

const summary = (id: string, patch: Record<string, unknown> = {}) => ({
  verdict_id: id,
  created_at: "2026-11-24T10:00:00Z",
  input_type: "url",
  display: "hxxps://falcon-demo-bank-secure[.]test",
  verdict: "dangerous",
  risk_score: 97,
  degraded: false,
  degraded_reasons: [],
  tier_reached: "T2",
  model_route: "none",
  source: "live",
  agent: { tiers_run: ["T0", "T1", "T2"], extractor_ran: false, investigator_ran: false, tool_calls: 2, llm_calls: 0 },
  ...patch,
});

/** An operator is someone whose key is in sessionStorage (set on /ops). */
const asOperator = (page: import("@playwright/test").Page) => page.addInitScript(() => window.sessionStorage.setItem("fl_operator_key", "op-test-key"));

test.describe("operator observability links", () => {
  test("check page: operator sees the Phoenix trace link and the Grafana logs and dashboard links with exact hrefs", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    await useBoards(context, request, baseURL!, { verdicts: [], verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id, source: "live", trace_id: TID, created_at: "2026-11-24T10:00:00Z", latency_ms: 4000 } } });
    await setPrefs(context, baseURL!, { lang: "en" });
    await asOperator(page);
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("operator-links")).toBeVisible();
    await expect(page.getByTestId("link-phoenix")).toHaveAttribute("href", `${PHOENIX}/projects/${PROJECT}/traces/${TID}`);
    const logs = new URL((await page.getByTestId("link-grafana-logs").getAttribute("href"))!);
    expect(logs.origin).toBe(GRAFANA);
    expect(logs.pathname).toBe("/explore");
    const panes = JSON.parse(logs.searchParams.get("panes")!);
    expect(panes.a.queries[0].expr).toBe(`{service=~".+"} |= "${id}"`);
    const from = Date.parse("2026-11-24T10:00:00Z") - 4000 - 60_000;
    const to = Date.parse("2026-11-24T10:00:00Z") + 120_000;
    expect(panes.a.range).toEqual({ from: String(from), to: String(to) });
    await expect(page.getByTestId("link-grafana-dash")).toHaveAttribute("href", `${GRAFANA}/d/fl-command-overview/?orgId=1&from=${from}&to=${to}`);
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations).toEqual([]);
  });

  test("check page without a trace id: says so, still offers Grafana", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    await useBoards(context, request, baseURL!, { verdicts: [], verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id, source: "live" } } });
    await asOperator(page);
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("no-trace")).toBeVisible();
    await expect(page.getByTestId("link-phoenix")).toHaveCount(0);
    await expect(page.getByTestId("link-grafana-logs")).toBeVisible();
  });

  test("public visitor sees no operator links and the config endpoint is never requested", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    const inc = newIncidentId();
    await useBoards(context, request, baseURL!, {
      verdicts: [summary(id, { trace_id: TID })],
      verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id, source: "live", trace_id: TID } },
      incidents: [{ ...DEMO_INCIDENT, incident_id: inc, source: "live" }],
      traces: { [inc]: [{ ...DEMO_TRACE, incident_id: inc, thread_id: inc, runs: [{ ...DEMO_TRACE.runs[0], trace_id: TID }] }] },
    });
    const asked: string[] = [];
    page.on("request", (r) => void (r.url().includes("/api/obs-config") && asked.push(r.url())));
    for (const path of [`/checks/${id}`, `/incidents/${inc}`, "/history", "/ops"]) {
      await page.goto(path);
      await page.waitForTimeout(1500); // let any client effect run (SSE keeps the network busy)
      await expect(page.getByTestId("operator-links")).toHaveCount(0);
      await expect(page.getByTestId("row-trace-link")).toHaveCount(0);
      await expect(page.getByTestId("monitoring-card")).toHaveCount(0);
      expect(await page.locator("body").innerHTML()).not.toContain(PHOENIX);
    }
    expect(asked).toEqual([]);
    // The public API never carries the trace id, and the operator routes refuse anonymous callers.
    expect(await (await request.get(`/api/public/checks/${id}`)).text()).not.toContain(TID);
    expect(await (await request.get(`/api/public/checks`)).text()).not.toContain(TID);
    expect(await (await request.get(`/api/public/incidents/${inc}`)).text()).not.toContain(TID);
    for (const path of ["/api/obs-config", `/api/ops/trace-ids?verdicts=${id}`, `/api/ops/incident-traces?incidents=${inc}`]) expect((await request.get(path)).status()).toBe(401);
  });

  test("history rows: operator gets a small trace icon per check that has a trace id", async ({ page, context, request, baseURL }) => {
    const a = newVerdictId();
    const b = newVerdictId();
    await useBoards(context, request, baseURL!, { verdicts: [summary(a), summary(b, { created_at: "2026-11-24T09:00:00Z" })], verdictDocs: { [a]: { ...DEMO_DANGEROUS, verdict_id: a, trace_id: TID }, [b]: { ...DEMO_DANGEROUS, verdict_id: b } } });
    await asOperator(page);
    await page.goto("/history");
    await expect(page.getByTestId("check-row")).toHaveCount(2);
    await expect(page.getByTestId("row-trace-link")).toHaveCount(1);
    await expect(page.locator(`[data-check-id="${a}"] [data-testid="row-trace-link"]`)).toHaveAttribute("href", `${PHOENIX}/projects/${PROJECT}/traces/${TID}`);
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations).toEqual([]);
  });

  test("incident page: links to the latest run's trace and the incident's logs", async ({ page, context, request, baseURL }) => {
    const inc = newIncidentId();
    await useBoards(context, request, baseURL!, {
      incidents: [{ ...DEMO_INCIDENT, incident_id: inc, source: "live" }],
      traces: { [inc]: [{ ...DEMO_TRACE, incident_id: inc, thread_id: inc, runs: [{ ...DEMO_TRACE.runs[0], trace_id: TID }] }] },
    });
    await asOperator(page);
    await page.goto(`/incidents/${inc}`);
    await expect(page.getByTestId("link-phoenix")).toHaveAttribute("href", `${PHOENIX}/projects/${PROJECT}/traces/${TID}`);
    const logs = new URL((await page.getByTestId("link-grafana-logs").getAttribute("href"))!);
    expect(JSON.parse(logs.searchParams.get("panes")!).a.queries[0].expr).toBe(`{service=~".+"} |= "${inc}"`);
    const axe = await new AxeBuilder({ page }).include("[data-testid=operator-links]").analyze();
    expect(axe.violations).toEqual([]);
  });

  test("/ops Monitoring card: Grafana dashboards, Prometheus alerts, Phoenix", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { incidents: [], requireKey: "op-test-key" });
    await page.goto("/ops");
    await expect(page.getByTestId("monitoring-card")).toHaveCount(0); // no key, no card
    await page.getByTestId("key-input").fill("op-test-key");
    await page.getByTestId("key-input").press("Enter");
    await expect(page.getByTestId("monitoring-card")).toBeVisible();
    await expect(page.getByTestId("mon-grafana")).toHaveAttribute("href", `${GRAFANA}/dashboards`);
    await expect(page.getByTestId("mon-prometheus")).toHaveAttribute("href", "http://127.0.0.1:9090/alerts");
    await expect(page.getByTestId("mon-phoenix")).toHaveAttribute("href", `${PHOENIX}/projects/${PROJECT}`);
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations).toEqual([]);
  });
});
