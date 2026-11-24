import { DEMO_CAMPAIGNS, DEMO_INCIDENT } from "../../lib/demo";
import { XSS } from "../fixtures";
import { expect, newIncidentId, test, useBoards } from "./helpers";

const liveCampaign = (id: string, patch: Record<string, unknown> = {}) => ({ ...DEMO_CAMPAIGNS[0], campaign_id: id, source: "live", ...patch });
const liveIncident = (id: string, patch: Record<string, unknown> = {}) => ({ ...DEMO_INCIDENT, incident_id: id, source: "live", ...patch });

test.describe("campaign board", () => {
  test("endpoint missing (404): honest 'not connected yet', no fake data", async ({ page }) => {
    await page.goto("/campaigns");
    await expect(page.getByTestId("board-not-connected")).toContainText("غير متصلة بعد");
    await expect(page.getByTestId("campaign-card")).toHaveCount(0);
    await expect(page.getByTestId("demo-ribbon")).toHaveCount(0);
  });

  test("public route: renders from the server-side feed, strips operator-only fields, key never reaches the browser", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { campaigns: [liveCampaign(newIncidentId())] });
    const seen: string[] = [];
    page.on("request", (r) => seen.push(`${r.url()} ${r.headers()["x-api-key"] ?? ""}`));
    await page.goto("/campaigns");
    await expect(page.getByTestId("campaign-card")).toHaveCount(1);
    expect(seen.some((u) => u.includes("/api/public/campaigns"))).toBe(true);
    expect(seen.some((u) => /\/v1\/campaigns/.test(u) || u.includes("test-read-key"))).toBe(false);
    const res = await page.request.get("/api/public/campaigns");
    expect(res.status()).toBe(200);
    const raw = await res.text();
    for (const secret of ["SECRET-DRAFT", "SECRET-APPROVER", "evil.example", "actions", "test-read-key"]) expect(raw).not.toContain(secret);
  });

  test("upstream rejects the service key (401): honest 'not connected'", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { campaigns: [liveCampaign(newIncidentId())], rejectKey: true });
    await page.goto("/campaigns");
    await expect(page.getByTestId("board-not-connected")).toBeVisible();
    await expect(page.getByTestId("campaign-card")).toHaveCount(0);
  });

  test("empty list: empty state", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { campaigns: [] });
    await page.goto("/campaigns");
    await expect(page.getByTestId("board-empty")).toBeVisible();
  });

  test("live campaigns render, the stream adds one, and hostile titles stay text", async ({ page, context, request, baseURL }) => {
    const first = newIncidentId();
    const second = newIncidentId();
    await useBoards(context, request, baseURL!, {
      campaigns: [liveCampaign(first)],
      campaignEvents: [liveCampaign(second, { severity: "critical", count: 2, title: { ar: `حملة ${XSS.img}`, en: `Campaign ${XSS.img}` }, advice: { ar: XSS.script, en: XSS.script } })],
    });
    await page.goto("/campaigns");
    await expect(page.getByTestId("campaign-card")).toHaveCount(1);
    await expect(page.getByTestId("campaign-card").first()).toContainText("بنك الصقر التجريبي");
    await expect(page.getByTestId("live-pill")).toContainText("مباشر");
    await expect(page.getByTestId("source-badge")).toHaveCount(0);

    await expect(page.getByTestId("campaign-card")).toHaveCount(2);
    // Critical sorts first.
    await expect(page.getByTestId("campaign-card").first()).toContainText(XSS.img);
    await expect(page.locator("main img, main script, main a")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("?demo=1 shows synthetic campaigns under the DEMO DATA ribbon", async ({ page }) => {
    await page.goto("/campaigns?demo=1");
    await expect(page.getByTestId("demo-ribbon")).toContainText("DEMO DATA");
    await expect(page.getByTestId("campaign-card")).toHaveCount(3);
    await expect(page.getByTestId("source-badge").first()).toContainText("اصطناعية");
  });
});

test.describe("operator incident board", () => {
  test("endpoint missing: 'not connected yet'", async ({ page }) => {
    await page.goto("/ops");
    await expect(page.getByTestId("ops-not-connected")).toBeVisible();
    await expect(page.getByTestId("incident-card")).toHaveCount(0);
  });

  test("needs the operator key; approve posts the decision and updates in place", async ({ page, context, request, baseURL }) => {
    const id = newIncidentId();
    const key = await useBoards(context, request, baseURL!, { incidents: [liveIncident(id)], requireKey: "op-test-key" });
    await page.goto("/ops");
    await expect(page.getByTestId("ops-unauthorized")).toBeVisible();

    await page.getByTestId("key-input").fill("op-test-key");
    await page.getByTestId("key-input").press("Enter");
    await expect(page.getByTestId("incident-card")).toHaveCount(1);
    await expect(page.getByTestId("incident-status")).toContainText("بانتظار الموافقة");
    await expect(page.getByTestId("incident-action")).toHaveCount(3);
    await expect(page.getByTestId("incident-card")).toContainText("falcon-demo-bank-secure[.]test");
    await expect(page.getByTestId("incident-card").locator("a:not([data-testid='trace-link']):not([data-testid='incident-title-link'])")).toHaveCount(0);
    // The key is never placed in the URL or a cookie.
    expect(page.url()).not.toContain("op-test-key");
    expect((await context.cookies()).some((c) => c.value.includes("op-test-key"))).toBe(false);

    await page.getByTestId("approve").click();
    await expect(page.getByTestId("approve")).toHaveCount(0);
    await expect(page.getByTestId("action-status").last()).toContainText("تمت الموافقة");
    const log = await (await request.get(`/__mock/boards?key=${key}`)).json();
    expect(log.decisions).toEqual([{ incident: id, action: "act_takedown_001", decision: "approve" }]);
  });

  test("a new incident arrives over the stream; hostile strings stay text", async ({ page, context, request, baseURL }) => {
    const incoming = newIncidentId();
    await useBoards(context, request, baseURL!, {
      incidents: [],
      incidentEvents: [liveIncident(incoming, { updated_at: "2026-11-22T11:00:00Z", summary: { ar: `ملخص ${XSS.img}`, en: `Summary ${XSS.img}` }, timeline: [{ at: "2026-11-22T10:02:00Z", what: `Event ${XSS.script}` }], indicators: [{ kind: "url", value_defanged: XSS.jsUrl, first_seen: "2026-11-22T10:02:00Z" }] })],
    });
    await page.goto("/ops");
    await expect(page.getByTestId("ops-empty")).toBeVisible();
    await expect(page.getByTestId("incident-card")).toHaveCount(1);
    await expect(page.getByTestId("incident-card")).toContainText(XSS.img);
    await expect(page.getByTestId("incident-card")).toContainText(XSS.script);
    await expect(page.locator("main img, main script, main a:not([data-testid='trace-link']):not([data-testid='incident-title-link'])")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  });

  test("AI model route panel: shows the route, switches it with the operator key, and states the local-privacy note", async ({ page, context, request, baseURL }) => {
    const key = await useBoards(context, request, baseURL!, { incidents: [], requireKey: "op-test-key" });
    await page.goto("/ops");
    await expect(page.getByTestId("llm-route-panel")).toHaveCount(0); // no key, no panel
    await page.getByTestId("key-input").fill("op-test-key");
    await page.getByTestId("key-input").press("Enter");
    await expect(page.getByTestId("llm-route-panel")).toBeVisible();
    await expect(page.getByTestId("route-effective")).toContainText(/Cloud LLM|نموذج لغوي سحابي/);
    await expect(page.getByTestId("route-model")).toHaveText("inkling-2-mini-chat");
    await expect(page.getByTestId("route-note")).toContainText("لا تغادر هذا الجهاز");
    await page.getByTestId("route-select").selectOption("local");
    await page.getByTestId("route-model-select").selectOption("qwen3.8:27b");
    await page.getByTestId("route-save").click();
    await expect(page.getByTestId("route-msg")).toBeVisible();
    await expect(page.getByTestId("route-effective")).toContainText("محلي");
    await expect(page.getByTestId("route-model")).toHaveText("qwen3.8:27b");
    const log = await (await request.get(`/__mock/boards?key=${key}`)).json();
    expect(log.routePuts).toEqual([{ mode: "local", local_model: "qwen3.8:27b" }]);
    expect(page.url()).not.toContain("op-test-key");
  });

  test("?demo=1: synthetic incident, approve changes nothing outside the page", async ({ page }) => {
    await page.goto("/ops?demo=1");
    await expect(page.getByTestId("demo-ribbon")).toBeVisible();
    await expect(page.getByTestId("incident-card")).toHaveCount(1);
    await page.getByTestId("reject").click();
    await expect(page.getByTestId("action-notice")).toContainText("لم يُرسَل أي شيء");
  });
});
