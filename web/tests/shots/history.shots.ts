import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/** On demand: SHOTS=1 SHOTS_DIR=/abs/dir pnpm exec playwright test --project=shots tests/shots/history.shots.ts */
const DIR = process.env.SHOTS_DIR ?? "/tmp/fl-shots";

test("history and check trace (demo data)", async ({ page, context, baseURL }) => {
  mkdirSync(DIR, { recursive: true });
  await context.addCookies([{ name: "fl_lang", value: "ar", url: baseURL! }]);
  for (const [name, size] of [["phone", { width: 390, height: 844 }], ["desktop", { width: 1440, height: 900 }]] as const) {
    await page.setViewportSize(size);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/history?demo=1");
    await page.getByTestId("check-row").first().waitFor();
    await page.screenshot({ path: join(DIR, `history-checks-${name}.png`), fullPage: true });
    await page.goto("/history?demo=1&tab=incidents");
    await page.getByTestId("tab-incidents").click();
    await page.getByTestId("incident-row").first().waitFor();
    await page.screenshot({ path: join(DIR, `history-incidents-${name}.png`), fullPage: true });
    await page.goto("/checks/vd_01KB0DEM0DATA0000000000001?demo=1");
    await page.getByTestId("check-tier").first().waitFor();
    await page.screenshot({ path: join(DIR, `check-trace-${name}.png`), fullPage: true });
  }
});
