/**
 * v2 part B screenshots (not assertions): the check result (phone, Arabic) and the Docs area.
 *   pnpm build && SHOTS=1 pnpm exec playwright test --project=shots tests/shots/v2b.shots.ts
 * Output: web/design/v2/shots-impl/*.png
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { dangerousStream, nwsStream } from "../fixtures";
import { expect, newVerdictId, registerScenario, setPrefs, submitText, test, token } from "../e2e/helpers";

const OUT = join(process.cwd(), "design", "v2", "shots-impl");
mkdirSync(OUT, { recursive: true });
const shot = (page: Page, name: string, fullPage = true) => page.screenshot({ path: join(OUT, `${name}.png`), fullPage, animations: "disabled" });

test.describe.configure({ mode: "serial" });

for (const kind of ["dangerous", "no-warning-signs"] as const) {
  test(`result ${kind} phone ar`, async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: kind === "dangerous" ? dangerousStream(id) : nwsStream(id) });
    await page.goto("/?demo=1");
    await submitText(page, `https://falcon-demo-bank${kind === "dangerous" ? "-secure" : ""}.test/login?c=${t}`);
    await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final");
    await page.waitForTimeout(1500);
    await page.getByTestId("result").scrollIntoViewIfNeeded();
    await shot(page, `check-${kind}-ar-390`);
  });
}

test("docs desktop en", async ({ page, context, baseURL }) => {
  await setPrefs(context, baseURL!, { lang: "en" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/docs");
  await page.evaluate(() => document.fonts.ready);
  await shot(page, "docs-en-1440");
  await page.goto("/docs/cascade");
  await shot(page, "docs-cascade-en-1440");
});
