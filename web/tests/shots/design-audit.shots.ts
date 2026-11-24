import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/** On demand: SHOTS=1 SHOTS_DIR=/abs/dir pnpm exec playwright test --project=shots tests/shots/design-audit.shots.ts */
const DIR = process.env.SHOTS_DIR ?? "/tmp/fl-shots";
const PAGES: [string, string][] = [
  ["results", "/results"],
  ["history", "/history?demo=1"],
  ["campaigns", "/campaigns?demo=1"],
  ["check", "/checks/vd_01KB0DEM0DATA0000000000001?demo=1"],
  ["authorities", "/authorities"],
  ["privacy", "/privacy"],
  ["ops", "/ops"],
  ["home", "/"],
];

test("design audit after-shots", async ({ page, context, baseURL }) => {
  test.setTimeout(600_000);
  mkdirSync(DIR, { recursive: true });
  for (const lang of ["ar", "en"] as const) {
    for (const theme of ["dark", "light"] as const) {
      await context.addCookies([{ name: "fl_lang", value: lang, url: baseURL! }, { name: "fl_theme", value: theme, url: baseURL! }]);
      for (const width of [390, 1280, 1440]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
        await page.emulateMedia({ reducedMotion: "reduce" });
        for (const [name, path] of PAGES) {
          if (width !== 1440 && theme === "light" && name !== "results" && name !== "check") continue;
          await page.goto(path);
          await page.waitForTimeout(400);
          await page.screenshot({ path: join(DIR, `${name}-${lang}-${theme}-${width}.png`), fullPage: true });
        }
      }
    }
  }
});
