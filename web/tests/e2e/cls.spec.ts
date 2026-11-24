import { DEMO_CAMPAIGNS, DEMO_INCIDENT } from "../../lib/demo";
import { expect, newIncidentId, newVerdictId, test, useBoards } from "./helpers";

/**
 * Cumulative Layout Shift on the live boards. The list endpoints answer late (as on a real
 * connection), so the loading placeholder is replaced by the real list while the page is watched.
 * Target: CLS < 0.1 on phone and desktop.
 */
const CLS_BUDGET = 0.1;

async function watchShifts(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number };
    w.__cls = 0;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as { value: number; hadRecentInput: boolean }[]) if (!e.hadRecentInput) w.__cls += e.value;
    }).observe({ type: "layout-shift", buffered: true });
  });
}
const cls = (page: import("@playwright/test").Page) => page.evaluate(() => (window as unknown as { __cls: number }).__cls);

async function delayed(page: import("@playwright/test").Page, glob: string, ms = 700) {
  await page.route(glob, async (route) => {
    await new Promise((r) => setTimeout(r, ms));
    await route.continue();
  });
}

const summary = (id: string, i: number) => ({
  verdict_id: id,
  created_at: `2026-11-24T10:0${i}:00Z`,
  input_type: "url",
  display: "hxxps://falcon-demo-bank-secure[.]test",
  verdict: "dangerous",
  risk_score: 97,
  degraded: false,
  degraded_reasons: [],
  tier_reached: "T2",
  model_route: "none",
  source: "fixture",
  agent: { tiers_run: ["T0", "T1", "T2"], extractor_ran: false, investigator_ran: false, tool_calls: 2, llm_calls: 0 },
});

test.describe("layout stability", () => {
  test("/campaigns: loading placeholder to live list shifts less than 0.1", async ({ page, context, request, baseURL }) => {
    const campaigns = [0, 1, 2].map((n) => ({ ...DEMO_CAMPAIGNS[0], campaign_id: newIncidentId(), source: "fixture", count: 3 + n }));
    await useBoards(context, request, baseURL!, { campaigns });
    await watchShifts(page);
    await delayed(page, "**/api/public/campaigns");
    await page.goto("/campaigns");
    await expect(page.getByTestId("board-loading")).toBeVisible();
    await expect(page.getByTestId("campaign-card")).toHaveCount(3);
    await page.waitForTimeout(500);
    const value = await cls(page);
    console.log(`CLS /campaigns ${test.info().project.name}: ${value.toFixed(4)}`);
    expect(value).toBeLessThan(CLS_BUDGET);
  });

  test("/history: loading placeholder to live rows shifts less than 0.1", async ({ page, context, request, baseURL }) => {
    const verdicts = [0, 1, 2, 3, 4, 5].map((i) => summary(newVerdictId(), i));
    await useBoards(context, request, baseURL!, { verdicts, incidents: [{ ...DEMO_INCIDENT, incident_id: newIncidentId(), source: "fixture" }] });
    await watchShifts(page);
    await delayed(page, "**/api/public/checks");
    await page.goto("/history");
    await expect(page.getByTestId("history-loading")).toBeVisible();
    await expect(page.getByTestId("check-row")).toHaveCount(6);
    await page.waitForTimeout(500);
    const value = await cls(page);
    console.log(`CLS /history ${test.info().project.name}: ${value.toFixed(4)}`);
    expect(value).toBeLessThan(CLS_BUDGET);
  });
});
