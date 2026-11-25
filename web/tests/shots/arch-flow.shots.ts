/**
 * Screenshots of the animated architecture diagrams (not assertions):
 *   pnpm build && SHOTS=1 pnpm exec playwright test --project=shots tests/shots/arch-flow.shots.ts
 * Output: web/design/app-shots/arch-flow/*.png
 * Each diagram is seeked to a fixed time with the `fl-flow-seek` event, so the pictures are repeatable.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { setPrefs, test } from "../e2e/helpers";

const OUT = join(process.cwd(), "design", "app-shots", "arch-flow");
mkdirSync(OUT, { recursive: true });

async function seek(page: Page, id: string, ms: number) {
  const fig = page.getByTestId(`flow-${id}`);
  await fig.scrollIntoViewIfNeeded();
  await fig.evaluate((el, t) => el.dispatchEvent(new CustomEvent("fl-flow-seek", { detail: t })), ms);
  await page.waitForTimeout(700);
  return fig;
}

/** A picture of the whole figure: the viewport is made tall enough, so the sticky bars sit where a visitor sees them. */
async function shot(page: Page, id: string, path: string) {
  const fig = page.getByTestId(`flow-${id}`);
  const width = page.viewportSize()!.width;
  const box0 = (await fig.boundingBox())!;
  await page.setViewportSize({ width, height: Math.ceil(box0.height) + 140 });
  await fig.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 110));
  await page.waitForTimeout(300);
  const box = (await fig.boundingBox())!;
  await page.screenshot({ path, animations: "disabled", clip: { x: Math.max(0, box.x - 12), y: Math.max(0, box.y - 12), width: Math.min(width, box.width + 24), height: box.height + 24 } });
}

const CASES = [
  ["ar", "dark", 1440, 1000, "ar-1440-dark"],
  ["en", "dark", 1440, 1000, "en-1440-dark"],
  ["en", "light", 1440, 1000, "en-1440-light"],
  ["ar", "light", 1920, 1080, "ar-1920-light"],
  ["ar", "dark", 390, 844, "ar-390-dark"],
  ["en", "light", 390, 844, "en-390-light"],
] as const;

for (const [lang, theme, width, height, tag] of CASES) {
  test(`main architecture ${tag}`, async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang, theme });
    await page.setViewportSize({ width, height });
    await page.goto("/docs");
    await page.evaluate(() => document.fonts.ready);
    await seek(page, "main", 12 * 1300 + 300);
    if (width === 390) await page.screenshot({ path: join(OUT, `main-${tag}-viewport.png`), animations: "disabled" });
    await shot(page, "main", join(OUT, `main-${tag}.png`));
  });
}

for (const [lang, width, height, tag] of [["en", 1440, 1000, "en-1440"], ["ar", 390, 844, "ar-390"]] as const) {
  test(`agent diagrams ${tag}`, async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang, theme: "dark" });
    await page.setViewportSize({ width, height });
    await page.goto("/docs/agents");
    await page.evaluate(() => document.fonts.ready);
    for (const [id, at] of [["baseer", 7], ["dir", 9], ["route", 4], ["dspy", 5]] as const) {
      await page.setViewportSize({ width, height });
      await seek(page, id, at * 1300 + 300);
      await shot(page, id, join(OUT, `${id}-${tag}.png`));
    }
    const lanes = page.getByTestId("arch-diagram");
    await lanes.scrollIntoViewIfNeeded();
    await page.getByTestId("arch-walk-full-next").click();
    await page.getByTestId("arch-walk-full-next").click();
    await lanes.screenshot({ path: join(OUT, `lanes-${tag}.png`), animations: "disabled" });
  });
}

test("reduced motion: the static, fully labelled version", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 1000 } });
  await setPrefs(context, baseURL!, { lang: "ar", theme: "dark" });
  const page = await context.newPage();
  await page.goto("/docs");
  await page.evaluate(() => document.fonts.ready);
  const fig = page.getByTestId("flow-main");
  await fig.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await shot(page, "main", join(OUT, "main-ar-1440-dark-reduced-motion.png"));
  await context.close();
});
