import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/** On demand: SHOTS=1 SHOTS_DIR=/abs/dir pnpm exec playwright test --project=shots tests/shots/fable-polish.shots.ts */
const DIR = process.env.SHOTS_DIR ?? "/tmp/fl-shots";
const PAGES: [string, string][] = [
  ["agents", "/agents"],
  ["docs", "/docs"],
  ["docs-agents", "/docs/agents"],
  ["docs-architecture", "/docs/architecture"],
  ["voice", "/voice"],
  ["incident", "/incidents/inc_01KB0DEM0DATA0000000000002?demo=1"],
];

test("design polish after-shots", async ({ page, context, baseURL }) => {
  test.setTimeout(600_000);
  mkdirSync(DIR, { recursive: true });
  for (const lang of ["ar", "en"] as const) {
    for (const theme of ["dark", "light"] as const) {
      await context.addCookies([{ name: "fl_lang", value: lang, url: baseURL! }, { name: "fl_theme", value: theme, url: baseURL! }]);
      for (const width of [390, 1440]) {
        if (theme === "light" && width === 390) continue;
        await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
        await page.emulateMedia({ reducedMotion: "reduce" });
        for (const [name, path] of PAGES) {
          await page.goto(path);
          await page.waitForTimeout(400);
          const layers = page.getByTestId("arch-layers");
          if (await layers.count()) await layers.screenshot({ path: join(DIR, `layers-${name}-${lang}-${theme}-${width}.png`) });
          await page.screenshot({ path: join(DIR, `${name}-${lang}-${theme}-${width}.png`), fullPage: true });
        }
      }
    }
  }
});
