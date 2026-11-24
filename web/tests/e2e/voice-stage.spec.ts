/* eslint-disable @typescript-eslint/no-explicit-any */
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { DEMO_INCIDENT } from "../../lib/demo";
import { dangerousStream, nwsStream } from "../fixtures";
import { expect, newIncidentId, newVerdictId, registerScenario, setPrefs, test, token, useBoards } from "./helpers";
import { installMocks, say } from "./voice-mocks";

/** STAGE_SHOTS_DIR=<dir> saves screenshots of every combination; the assertions run either way. */
const SHOTS = process.env.STAGE_SHOTS_DIR;
const SIZES = [{ w: 1280, h: 720 }, { w: 1920, h: 1080 }];

test.describe("voice stage layout: projector view, no page scroll during a run", () => {
  test.setTimeout(180_000);
  test.skip(({ viewport }) => (viewport?.width ?? 0) < 1000, "stage layout is for wide screens; the phone layout is covered by voice.spec.ts");

  for (const lang of ["ar", "en"] as const) {
    for (const theme of ["dark", "light"] as const) {
      test(`${lang} ${theme}: three messages, Sentinel card, summary; presenter off and on`, async ({ page, request, context, baseURL }) => {
        const t = token();
        const ids = [newVerdictId(), newVerdictId(), newVerdictId()];
        const msgs = [
          `Your account is suspended, verify now ${t}1 https://falcon-demo-bank-secure.test/login`,
          `Parcel fee unpaid ${t}2 http://falcon-demo-bank-parcel.test/pay`,
          `Hi, dinner at eight? ${t}3`,
        ];
        await registerScenario(request, { match: `${t}1`, verdictId: ids[0], steps: dangerousStream(ids[0]!) });
        await registerScenario(request, { match: `${t}2`, verdictId: ids[1], steps: dangerousStream(ids[1]!) });
        await registerScenario(request, { match: `${t}3`, verdictId: ids[2], steps: nwsStream(ids[2]!) });
        const inc = newIncidentId();
        await useBoards(context, request, baseURL!, { incidents: [{ ...DEMO_INCIDENT, incident_id: inc, source: "live", linked_verdicts: ids }] });
        await setPrefs(context, baseURL!, { lang, theme });
        await installMocks(page);
        await page.addInitScript((clip) => { (window as any).__clip = clip; }, msgs.join("\n\n"));

        await page.setViewportSize({ width: 1280, height: 720 });
        await page.goto("/voice");
        await page.getByTestId("voice-on").click();
        await say(page, lang === "ar" ? "check-ar" : "check-en");

        // No vertical page scroll at any moment of the run (sampled), and Stop stays on screen.
        const overflow = async () => page.evaluate(() => ({ doc: document.documentElement.scrollHeight - window.innerHeight, body: document.body.scrollHeight - window.innerHeight }));
        const stopInView = async () => page.getByTestId("voice-stop").evaluate((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; });
        const sampling = (async () => {
          for (let i = 0; i < 40; i++) {
            const o = await overflow();
            expect(o.doc, "document scroll overflow during run").toBeLessThanOrEqual(0);
            expect(o.body).toBeLessThanOrEqual(0);
            expect(await stopInView()).toBe(true);
            await page.waitForTimeout(250);
          }
        })();
        await expect(page.getByTestId("voice-sentinel")).toBeVisible({ timeout: 60_000 });
        await expect(page.getByTestId("voice-todo")).toBeVisible({ timeout: 30_000 });
        await sampling;

        // Grouped per message: three heads, each with its verdict chip; finished messages collapse to one line with a trace link.
        await expect(page.locator('[data-testid="voice-step"][data-head="true"]')).toHaveCount(3);
        await expect(page.getByTestId("voice-group-chip")).toHaveCount(3);
        await expect(page.getByTestId("voice-group-trace")).toHaveCount(3);
        expect(await page.locator('[data-testid="voice-step"][data-sub="true"]').first().isHidden()).toBe(true);
        expect(await page.locator("main").innerText()).not.toMatch(/آمن|\bsafe\b/i);
        // The step panel shows the newest step (it scrolls, the page does not).
        const cur = page.locator('[data-testid="voice-step"][data-current="true"]');
        await expect(cur).toBeInViewport();
        expect((await overflow()).doc).toBeLessThanOrEqual(0);

        if (process.env.DUMP) console.log(JSON.stringify(await page.locator('[data-testid="voice-step"]').evaluateAll((els) => els.map((e) => [e.getAttribute("data-msg"), e.getAttribute("data-head"), e.getAttribute("data-collapsed"), getComputedStyle(e).display, (e.textContent ?? "").slice(0, 40)]))));
        const dir = SHOTS ?? "";
        if (dir) mkdirSync(dir, { recursive: true });
        for (const size of SIZES) {
          for (const stage of [false, true]) {
            await page.setViewportSize({ width: size.w, height: size.h });
            const on = (await page.getByTestId("voice-presenter").getAttribute("aria-pressed")) === "true";
            if (on !== stage) await page.getByTestId("voice-presenter").click();
            if (stage) await expect(page.locator("html")).toHaveAttribute("data-stage", "1");
            else await expect(page.locator("html")).not.toHaveAttribute("data-stage", "1");
            if (stage) await expect(page.locator("header.top")).toBeHidden();
            else await expect(page.locator("header.top")).toBeVisible();
            await page.waitForTimeout(700);
            expect((await overflow()).doc, `${size.w}x${size.h} stage=${stage}`).toBeLessThanOrEqual(0);
            expect(await stopInView()).toBe(true);
            // The preview marker is still visible in presenter mode (truth rule).
            await expect(page.getByTestId("voice-preview")).toBeVisible();
            if (dir) await page.screenshot({ path: join(dir, `${lang}-${theme}-${size.w}x${size.h}-${stage ? "presenter" : "normal"}.png`) });
          }
        }
        if (theme === "dark" || lang === "ar") {
          const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
          expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
        }
      });
    }
  }

  test("?stage=1 opens in presenter mode", async ({ page }) => {
    await installMocks(page);
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/voice?stage=1");
    await expect(page.locator("html")).toHaveAttribute("data-stage", "1");
    await expect(page.locator("header.top")).toBeHidden();
    await expect(page.getByTestId("voice-preview")).toBeVisible();
    await expect(page.getByTestId("voice-stop")).toBeInViewport();
  });
});
