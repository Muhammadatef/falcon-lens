/**
 * /results KPI sections: headline KPIs (validation | test), real vs synthetic, held-out live false alarms by date,
 * attacks per category and cost & operations. Both languages, phone and desktop, axe, badges, honesty wording.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import extra from "../../lib/results-extra.generated.json";
import { expect, setPrefs, test } from "./helpers";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
async function serious(page: Page) {
  const found = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  return found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
}
/** Open a collapsible section (closed by default on phone, opened on desktop after mount). */
async function openFold(page: Page, id: string) {
  const d = page.getByTestId(id);
  await expect(d).toBeVisible();
  if ((await d.getAttribute("open")) === null) await d.locator("summary").first().click();
  await expect(d).toHaveAttribute("open", "");
}
const x = extra as unknown as { fpHistory: { artifact: string }[]; redteam: Record<string, { categories: Record<string, { cases: number; harmful: number; answered: number }> }> };

for (const lang of ["ar", "en"] as const) {
  test.describe(`results KPI ${lang}`, () => {
    test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang }));

    test("headline KPI grid shows validation and test side by side with an explanation each", async ({ page }) => {
      await page.goto("/results");
      const grid = page.getByTestId("kpi-grid");
      await expect(grid).toBeVisible();
      for (const k of ["recall", "precision", "f1", "accuracy", "fpr", "roc_auc", "pr_auc", "ece", "official"]) await expect(page.getByTestId(`kpi-${k}`), k).toBeVisible();
      for (const k of ["recall", "precision", "fpr", "ece"]) {
        for (const sp of ["val", "test"]) await expect(page.getByTestId(`metric-${sp}-${k}`), `${sp} ${k}`).toContainText(/\d/);
      }
      await expect(page.getByTestId("kpi-precision")).toContainText(lang === "en" ? "Of the links we warned about, how many were really scams" : "من الروابط التي حذّرنا منها");
      await expect(page.getByTestId("kpi-recall")).toContainText("95%");
      await expect(page.getByTestId("kpi-scope")).toBeVisible();
      await expect(grid.locator(".prov-badge").first()).toHaveAttribute("data-badge", "REAL");
    });

    test("real and synthetic stay in two columns, every metric badged", async ({ page }) => {
      await page.goto("/results");
      const real = page.getByTestId("rs-real");
      const synth = page.getByTestId("rs-synthetic");
      await expect(real).toBeVisible();
      await expect(synth).toBeVisible();
      await expect(real.locator('.prov-badge[data-badge="REAL"]').first()).toBeVisible();
      await expect(real.locator('.prov-badge:not([data-badge="REAL"])')).toHaveCount(0);
      await expect(synth.locator('.prov-badge[data-badge="FIXTURE"]').first()).toBeVisible();
      await expect(synth.locator('.prov-badge[data-badge="SYNTHETIC"]').first()).toBeVisible();
      await expect(synth.locator('.prov-badge[data-badge="REAL"]')).toHaveCount(0);
      // every metric card carries a badge
      const cards = page.locator('[data-testid^="rs-"][data-testid*="-recall"], [data-testid^="rs-"][data-testid*="-fpr"]');
      expect(await cards.count()).toBeGreaterThan(3);
      for (const card of await cards.all()) await expect(card.locator(".prov-badge")).toHaveCount(1);
      if (page.viewportSize()!.width >= 1024) {
        const a = await real.boundingBox();
        const b = await synth.boundingBox();
        expect(Math.abs(a!.y - b!.y)).toBeLessThan(40);
      }
    });

    test("held-out live false alarms: every run listed, newest first and highlighted, sparkline drawn", async ({ page }) => {
      await page.goto("/results");
      await openFold(page, "fp-history");
      await expect(page.getByTestId("fp-spark").locator("svg polyline")).toHaveCount(2);
      const rows = page.getByTestId("fp-history").locator("tbody tr");
      await expect(page.getByTestId("fp-history").locator(":scope > .fold-body > .tbl-wrap tbody tr")).toHaveCount(3);
      await page.getByTestId("fp-all").locator("summary").first().click();
      await expect(rows).toHaveCount(x.fpHistory.length);
      await expect(rows.first()).toHaveAttribute("data-testid", "fp-newest");
      await expect(page.getByTestId("fp-newest")).toHaveCount(1);
      await expect(rows.first()).toContainText("2026-11-23");
      await expect(page.getByTestId("fp-note")).toBeVisible();
      await rows.first().locator("summary").click();
      await expect(rows.first().locator("details li").first()).toBeVisible();
    });

    test("attacks: harmful count always beside the answered count, for every category", async ({ page }) => {
      await page.goto("/results");
      await openFold(page, "attacks");
      const ext = x.redteam.extended!.categories;
      for (const [cat, v] of Object.entries(ext)) {
        const row = page.getByTestId(`atk-extended-${cat}`);
        await expect(row).toContainText(`${v.harmful}`);
        await expect(row).toContainText(`${v.answered}`);
        await expect(row).toContainText(`${v.cases}`);
      }
      await expect(page.getByTestId("atk-production")).toBeVisible();
      await expect(page.getByTestId("atk-note")).toBeVisible();
    });

    test("cost and operations: cost, agreement, extractor per route, stability", async ({ page }) => {
      await page.goto("/results");
      await openFold(page, "ops");
      await expect(page.getByTestId("ops-cloud_usd_per_check")).toContainText("$");
      await expect(page.getByTestId("ops-local_usd_per_check")).toContainText("0");
      await expect(page.getByTestId("ops-exact_label_agreement")).toContainText("%");
      await expect(page.getByTestId("ops-extractor-cloud")).toBeVisible();
      await expect(page.getByTestId("ops-extractor-local")).toBeVisible();
      await expect(page.getByTestId("ops-ai_on_all_three_identical")).toBeVisible();
      await expect(page.getByTestId("ops-scope")).toBeVisible();
    });

    test("honesty and layout: never safe, no overflow, axe has no serious issues", async ({ page }) => {
      await page.goto("/results");
      const body = await page.locator("main").innerText();
      expect(body).not.toMatch(/\bsafe\b|آمن/i);
      expect(body).not.toMatch(/Abu Dhabi Police|شرطة أبوظبي/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
      expect(await serious(page)).toEqual([]);
      for (const id of ["fp-history", "attacks", "ops", "areas"]) await openFold(page, id);
      expect(await serious(page), "all sections open").toEqual([]);
    });

    test("phone page is short with the folds closed, and the folds open by keyboard", async ({ page }) => {
      test.skip((page.viewportSize()?.width ?? 1440) >= 720, "phone only");
      await page.goto("/results");
      for (const id of ["fp-history", "attacks", "ops", "areas"]) await expect(page.getByTestId(id)).not.toHaveAttribute("open", "");
      const height = await page.evaluate(() => document.documentElement.scrollHeight);
      expect(height, `phone page height ${height}px`).toBeLessThan(8000);
      await expect(page.getByTestId("kpi-grid")).toBeVisible();
      await expect(page.getByTestId("real-synthetic")).toBeVisible();
      await page.getByTestId("attacks").locator("summary").focus();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("attacks")).toHaveAttribute("open", "");
    });
  });
}
