/**
 * Screenshot capture of the real app against the mock gateway (not assertions).
 *   pnpm build && SHOTS=1 pnpm exec playwright test --project=shots
 * Output: web/design/app-shots/*.png
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { DEMO_CAMPAIGNS, DEMO_INCIDENT } from "../../lib/demo";
import { dangerousStream, degradedVerdict, nwsStream } from "../fixtures";
import { newIncidentId, newVerdictId, registerScenario, setPrefs, submitText, test, token, useBoards, expect } from "../e2e/helpers";

// Playwright runs from web/ (where playwright.config.ts lives).
const OUT = join(process.cwd(), "design", "app-shots");
mkdirSync(OUT, { recursive: true });

const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };
const shot = (page: Page, name: string, fullPage = false) => page.screenshot({ path: join(OUT, `${name}.png`), fullPage, animations: "disabled" });
const settle = (page: Page) => page.waitForTimeout(1200);

test.describe.configure({ mode: "serial" });

test("hero", async ({ page, context, baseURL }) => {
  await page.setViewportSize(PHONE);
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  await shot(page, "01-hero-390-ar-night");
  await page.setViewportSize(DESKTOP);
  await shot(page, "01-hero-1440-ar-night");
  await setPrefs(context, baseURL!, { lang: "en", theme: "light" });
  await page.goto("/");
  await shot(page, "01-hero-1440-en-sand");
  await page.setViewportSize(PHONE);
  await shot(page, "01-hero-390-en-sand");
});

test("dangerous: streaming then final", async ({ page, request }) => {
  await page.setViewportSize(PHONE);
  const id = newVerdictId();
  const t = token();
  const steps = dangerousStream(id).map((s, i) => ({ ...s, delayMs: i === 2 ? 4000 : s.delayMs }));
  await registerScenario(request, { match: t, verdictId: id, steps });
  await page.goto("/");
  await submitText(page, `https://falcon-demo-bank-secure.test/login?c=${t}`);
  await expect(page.getByTestId("provisional-chip")).toBeVisible();
  await page.waitForTimeout(900);
  await shot(page, "02-check-streaming-390-ar-night");
  await expect(page.getByTestId("verdict-word")).toBeVisible();
  await settle(page);
  await page.getByTestId("result").scrollIntoViewIfNeeded();
  await page.evaluate(() => document.getElementById("check")?.scrollIntoView({ block: "start" }));
  await shot(page, "03-check-dangerous-390-ar-night");
  await shot(page, "03-check-dangerous-390-ar-night-full", true);
  await page.setViewportSize(DESKTOP);
  await page.evaluate(() => document.getElementById("check")?.scrollIntoView({ block: "start" }));
  await shot(page, "03-check-dangerous-1440-ar-night");
  await page.getByTestId("lang-toggle").click();
  await page.getByTestId("theme-toggle").click();
  await settle(page);
  await page.evaluate(() => document.getElementById("check")?.scrollIntoView({ block: "start" }));
  await shot(page, "03-check-dangerous-1440-en-sand");
});

test("no warning signs, degraded, rate limit", async ({ page, request }) => {
  await page.setViewportSize(PHONE);
  const id = newVerdictId();
  const t = token();
  await registerScenario(request, { match: t, verdictId: id, steps: nwsStream(id) });
  await page.goto("/");
  await submitText(page, `https://falcon-demo-bank.test/?c=${t}`);
  await expect(page.getByTestId("verdict-word")).toBeVisible();
  await settle(page);
  await page.evaluate(() => document.getElementById("check")?.scrollIntoView({ block: "start" }));
  await shot(page, "04-check-no-warning-signs-390-ar-night");
  await shot(page, "04-check-no-warning-signs-390-ar-night-full", true);

  const id2 = newVerdictId();
  const t2 = token();
  await registerScenario(request, { match: t2, verdictId: id2, steps: [{ delayMs: 100, verdict: degradedVerdict(id2) }] });
  await page.goto("/");
  await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t2}`);
  await expect(page.getByTestId("degraded")).toBeVisible();
  await settle(page);
  await page.evaluate(() => document.getElementById("check")?.scrollIntoView({ block: "start" }));
  await shot(page, "05-check-degraded-390-ar-night");

  const t3 = token();
  await registerScenario(request, { match: t3, status: 429, retryAfter: 30 });
  await page.goto("/");
  await submitText(page, `https://x.test/${t3}`);
  await expect(page.getByTestId("problem")).toBeVisible();
  await settle(page);
  await page.evaluate(() => document.getElementById("check")?.scrollIntoView({ block: "start" }));
  await shot(page, "06-check-rate-limited-390-ar-night");
});

test("boards", async ({ page, context, request, baseURL }) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/campaigns");
  await expect(page.getByTestId("board-not-connected")).toBeVisible();
  await shot(page, "07-campaigns-not-connected-1440-ar-night");

  await useBoards(context, request, baseURL!, {
    campaigns: DEMO_CAMPAIGNS.map((c, i) => ({ ...c, campaign_id: newIncidentId(), source: "live", count: c.count + i })),
    incidents: [{ ...DEMO_INCIDENT, incident_id: newIncidentId(), source: "live" }],
  });
  await page.goto("/campaigns");
  await expect(page.getByTestId("campaign-card")).toHaveCount(3);
  await settle(page);
  await shot(page, "08-campaigns-live-1440-ar-night");
  await page.setViewportSize(PHONE);
  await shot(page, "08-campaigns-live-390-ar-night", true);

  await page.goto("/ops");
  await expect(page.getByTestId("incident-card")).toHaveCount(1);
  await settle(page);
  await shot(page, "09-ops-390-ar-night", true);
  await page.setViewportSize(DESKTOP);
  await shot(page, "09-ops-1440-ar-night", true);

  await page.goto("/campaigns?demo=1");
  await expect(page.getByTestId("campaign-card")).toHaveCount(3);
  await shot(page, "10-campaigns-demo-ribbon-1440-ar-night");
});
