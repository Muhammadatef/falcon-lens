/**
 * Agent names (Baseer | بصير = Investigator, Dir' | درع = Sentinel) and the voice-assistant content:
 * /agents, /docs/agents, /history, /voice in both languages, axe with zero serious or critical findings.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, setPrefs, test } from "./helpers";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
async function axe(page: Page) {
  const found = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  return found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
}

for (const lang of ["ar", "en"] as const) {
  test.describe(`agent names ${lang}`, () => {
    test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang }));

    test("/agents names both agents, shows the Talk to Falcon card, axe clean", async ({ page }) => {
      await page.goto("/agents");
      await expect(page.getByTestId("lane-inv")).toContainText("بصير");
      await expect(page.getByTestId("lane-sen")).toContainText("درع");
      if (lang === "en") {
        await expect(page.getByTestId("lane-inv")).toContainText("Investigator");
        await expect(page.getByTestId("lane-sen")).toContainText("Sentinel");
      }
      const card = page.getByTestId("agents-voice-card");
      await expect(card).toContainText("يا فالكون");
      await expect(card).toContainText(lang === "ar" ? "تكلّم مع الصقر" : "Talk to Falcon");
      expect(await axe(page)).toEqual([]);
    });

    test("/docs/agents has the voice path with seven ordered steps and the architecture voice nodes, axe clean", async ({ page }) => {
      await page.goto("/docs/agents");
      const voice = page.getByTestId("voice-doc");
      await expect(voice).toContainText("يا فالكون");
      await expect(page.getByTestId("voice-flow").locator("li")).toHaveCount(7);
      await expect(voice).toContainText("/api/voice");
      await expect(voice).toContainText(lang === "ar" ? "«بصير»" : "Baseer");
      await expect(voice).toContainText(lang === "ar" ? "«درع»" : "Dir'");
      await expect(voice).not.toContainText(/\bsafe\b|آمن/i);
      expect(await axe(page)).toEqual([]);
    });

    test("/history tabs name the agents, axe clean", async ({ page }) => {
      await page.goto("/history");
      await expect(page.getByTestId("tab-checks")).toContainText("بصير");
      await expect(page.getByTestId("tab-incidents")).toContainText("درع");
      expect(await axe(page)).toEqual([]);
    });

    test("/voice page loads in both languages, axe clean", async ({ page }) => {
      await page.goto("/voice");
      await expect(page.locator("h1")).toBeVisible();
      expect(await axe(page)).toEqual([]);
    });
  });
}
