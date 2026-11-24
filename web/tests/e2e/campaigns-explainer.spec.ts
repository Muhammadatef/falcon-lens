import AxeBuilder from "@axe-core/playwright";
import { expect, setPrefs, test } from "./helpers";

for (const lang of ["ar", "en"] as const) {
  test.describe(`campaigns explainer ${lang}`, () => {
    test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang }));

    test("intro shows, panel collapses/expands, board still renders mock items, axe clean", async ({ page }) => {
      await page.goto("/campaigns?demo=1");
      await expect(page.getByTestId("campaign-card").first()).toBeVisible();
      await expect(page.getByTestId("campaign-explainer")).toBeVisible();
      const toggle = page.getByTestId("cx-toggle");
      const panel = page.getByTestId("cx-panel");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(panel).toBeHidden();
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(panel).toBeVisible();
      await expect(panel.getByRole("link")).toHaveAttribute("href", "/docs/agents");
      await expect(page.getByTestId("campaign-card").first()).toBeVisible();
      const found = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      expect(found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
      await page.screenshot({ path: `test-results/campaigns-explainer-${lang}.png`, fullPage: true });
    });

    test("header nav lists Campaigns with aria-current, panel has inner padding and shares the board width", async ({ page }) => {
      await page.goto("/campaigns?demo=1");
      const vw = page.viewportSize()!.width;
      if (vw < 900) await page.getByTestId("menu-toggle").click();
      const link = page.locator("#site-nav a[href='/campaigns']");
      await expect(link).toHaveText(lang === "ar" ? "الحملات" : "Campaigns");
      await expect(link).toHaveAttribute("aria-current", "page");
      await page.getByTestId("cx-toggle").click();
      const panel = page.getByTestId("cx-panel");
      expect(await panel.evaluate((e) => parseFloat(getComputedStyle(e).paddingInlineStart))).toBeGreaterThanOrEqual(16);
      const pb = (await panel.boundingBox())!;
      const tb = (await page.getByTestId("cx-toggle").boundingBox())!;
      const start = (b: { x: number; width: number }) => (lang === "ar" ? b.x + b.width : b.x);
      expect(Math.abs(start(pb) - start(tb))).toBeLessThan(2);
      await expect(page.locator(".cx-steps li .cx-n")).toHaveCount(4);
      await page.screenshot({ path: `test-results/campaigns-layout-${lang}-${vw}.png`, fullPage: true });
    });
  });
}
