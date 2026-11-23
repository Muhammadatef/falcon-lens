import { test } from "@playwright/test";

/**
 * Screenshots of the agent trace page against a running stack:
 *   SHOTS=1 SHOT_BASE=https://localhost:58943 SHOT_INCIDENT=inc_... SHOT_KEY=... SHOT_DIR=/abs/dir \
 *     pnpm exec playwright test --project=shots tests/shots/trace.shots.ts
 */
const base = process.env.SHOT_BASE ?? "";
const incident = process.env.SHOT_INCIDENT ?? "";
const key = process.env.SHOT_KEY ?? "";
const dir = process.env.SHOT_DIR ?? ".";

test("trace page shots", async ({ browser }) => {
  test.skip(!base || !incident, "needs SHOT_BASE and SHOT_INCIDENT");
  const context = await browser.newContext({ baseURL: base, ignoreHTTPSErrors: true, viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  await context.addCookies([{ name: "fl_lang", value: "ar", url: base }]);
  const page = await context.newPage();
  await page.addInitScript((k) => window.sessionStorage.setItem("fl_operator_key", k), key);
  await page.goto(`/incidents/${incident}`);
  await page.getByTestId("trace-step").first().waitFor();
  await page.screenshot({ path: `${dir}/trace-ar-top.png` });
  await page.getByTestId("trace-interrupt").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${dir}/trace-ar-interrupt.png` });
  await context.addCookies([{ name: "fl_lang", value: "en", url: base }]);
  await page.reload();
  await page.getByTestId("trace-step").first().waitFor();
  await page.screenshot({ path: `${dir}/trace-en-full.png`, fullPage: true });
  await context.close();
});
