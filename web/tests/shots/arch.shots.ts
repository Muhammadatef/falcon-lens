/**
 * Screenshots of the interactive architecture (not assertions):
 *   pnpm build && SHOTS=1 pnpm exec playwright test --project=shots tests/shots/arch.shots.ts
 * Output: web/design/app-shots/arch/*.png
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, setPrefs, test } from "../e2e/helpers";

const OUT = join(process.cwd(), "design", "app-shots", "arch");
mkdirSync(OUT, { recursive: true });

for (const [lang, width, height, tag] of [["ar", 390, 844, "ar-390"], ["en", 1440, 900, "en-1440"]] as const) {
  test(`architecture ${tag}`, async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang, theme: "dark" });
    await page.setViewportSize({ width, height });
    await page.goto("/docs/agents");
    await page.evaluate(() => document.fonts.ready);
    await page.getByTestId("arch-diagram").scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(OUT, `diagram-closed-${tag}.png`), animations: "disabled" });
    const node = page.getByTestId("arch-node-t2");
    await node.scrollIntoViewIfNeeded();
    if (width >= 720) {
      await node.hover();
      await expect(page.getByTestId("arch-tip-t2")).toBeVisible();
      await page.screenshot({ path: join(OUT, `diagram-tooltip-${tag}.png`), animations: "disabled" });
    }
    await node.click();
    await expect(page.getByTestId("arch-panel")).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: join(OUT, `diagram-panel-${tag}.png`), animations: "disabled" });
  });
}
