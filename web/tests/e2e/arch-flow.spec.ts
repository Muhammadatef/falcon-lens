/**
 * Animated architecture diagrams (components/arch/FlowDiagram): they render with a logo or badge and a label on
 * every box, the player works (play, pause, step, replay), the caption follows the step, a box opens the detail
 * panel, reduced motion gives the static fully labelled version, nothing scrolls sideways, and axe finds nothing
 * serious. Runs on the phone and the desktop project, in Arabic and English.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { BASEER_FLOW, DIR_FLOW, DSPY_FLOW, MAIN_FLOW, ROUTE_FLOW, nodesOf } from "../../lib/arch-flow";
import { expect, forceCaps, setPrefs, test } from "./helpers";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const stepOf = async (page: Page, id: string) => Number(await page.getByTestId(`flow-${id}`).getAttribute("data-step"));
async function seek(page: Page, id: string, ms: number) {
  await page.getByTestId(`flow-${id}`).evaluate((el, t) => el.dispatchEvent(new CustomEvent("fl-flow-seek", { detail: t })), ms);
}
async function serious(page: Page, selector: string) {
  const found = await new AxeBuilder({ page }).include(selector).withTags(WCAG).analyze();
  return found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
}

for (const lang of ["ar", "en"] as const) {
  test.describe(`main architecture ${lang}`, () => {
    test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang }));

    test("renders three layers; every box has a badge, a label and a second line; the logo footnote is shown", async ({ page }) => {
      await page.goto("/docs");
      const fig = page.getByTestId("flow-main");
      await fig.scrollIntoViewIfNeeded();
      await expect(fig).toHaveAttribute("data-built", "true");
      for (const band of ["voice", "agents", "platform"]) await expect(page.getByTestId(`flow-main-band-${band}`)).toBeVisible();
      const tops = await Promise.all(["voice", "agents", "platform"].map(async (b) => (await page.getByTestId(`flow-main-band-${b}`).boundingBox())!.y));
      expect(tops[0]!).toBeLessThan(tops[1]!);
      expect(tops[1]!).toBeLessThan(tops[2]!);
      const nodes = nodesOf(MAIN_FLOW);
      await expect(fig.locator(".af-node")).toHaveCount(nodes.length);
      for (const n of nodes) {
        const box = page.getByTestId(`flow-main-node-${n.id}`);
        await expect(box.locator(".tb")).toHaveCount(1);
        await expect(box.locator(".af-node-text b")).toHaveText(n.label[lang]);
        await expect(box.locator(".af-node-text small")).toHaveText(n.sub[lang]);
      }
      // Real logos are inline paths from the vendored files; tools without one get a text badge.
      await expect(page.getByTestId("flow-main-node-p_redis").locator('.tb[data-kind="logo"] svg path')).toHaveCount(1);
      await expect(page.getByTestId("flow-main-node-p_phoenix").locator('.tb[data-kind="mono"]')).toHaveText("Px");
      await expect(page.getByTestId("flow-main-logo-note")).toHaveText(lang === "ar" ? "الشعارات ملك لأصحابها، وتُعرَض للتعريف بالأدوات المستخدمة فقط." : "Logos belong to their owners; shown to identify the tools used.");
      await expect(page.getByTestId("flow-main-wires").locator("path.af-wire-on")).toHaveCount(MAIN_FLOW.steps.length - 1);
      expect((await page.getByTestId("flow-main-node-s_approval").boundingBox())!.height).toBeGreaterThanOrEqual(44);
      expect(await overflow(page)).toBeLessThanOrEqual(0);
    });

    test("plays by itself, pauses, resumes, steps and replays; the caption follows the step", async ({ page }) => {
      await page.goto("/docs");
      const fig = page.getByTestId("flow-main");
      await fig.scrollIntoViewIfNeeded();
      await expect(fig).toHaveAttribute("data-status", "playing");
      await expect.poll(() => stepOf(page, "main"), { timeout: 10_000 }).toBeGreaterThanOrEqual(1);
      const toggle = page.getByTestId("flow-main-toggle");
      await expect(toggle).toHaveAttribute("aria-pressed", "true");
      await toggle.click();
      await expect(fig).toHaveAttribute("data-status", "paused");
      const held = await stepOf(page, "main");
      await page.waitForTimeout(1700);
      expect(await stepOf(page, "main")).toBe(held);
      await expect(page.getByTestId("flow-main-caption")).toContainText(MAIN_FLOW.steps[held]!.caption[lang]);
      await expect(page.getByTestId(`flow-main-node-${MAIN_FLOW.steps[held]!.node}`)).toHaveAttribute("data-state", "active");

      await page.getByTestId("flow-main-next").click();
      expect(await stepOf(page, "main")).toBe(held + 1);
      await expect(page.getByTestId("flow-main-caption")).toContainText(MAIN_FLOW.steps[held + 1]!.caption[lang]);
      await expect(page.getByTestId(`flow-main-node-${MAIN_FLOW.steps[held]!.node}`)).toHaveAttribute("data-state", "done");
      await page.getByTestId("flow-main-prev").click();
      expect(await stepOf(page, "main")).toBe(held);

      await toggle.click();
      await expect(fig).toHaveAttribute("data-status", "playing");
      await expect.poll(() => stepOf(page, "main"), { timeout: 10_000 }).toBeGreaterThan(held);

      // Seek to the end: the run stops by itself; Replay starts again from the first step.
      await seek(page, "main", Number(await fig.getAttribute("data-duration")) + 10);
      await expect(fig).toHaveAttribute("data-status", "done");
      expect(await stepOf(page, "main")).toBe(MAIN_FLOW.steps.length - 1);
      await page.getByTestId("flow-main-replay").click();
      await expect(fig).toHaveAttribute("data-status", "playing");
      await expect.poll(() => stepOf(page, "main")).toBeLessThan(3);
    });

    test("a box opens the detail panel (full panel or tool card); Esc closes it and returns focus", async ({ page }) => {
      await page.goto("/docs");
      const node = page.getByTestId("flow-main-node-arbiter");
      await node.scrollIntoViewIfNeeded();
      await node.click();
      const panel = page.getByTestId("arch-panel");
      await expect(panel).toHaveAttribute("data-node", "arbiter");
      await expect(panel.getByTestId("cap-badge")).toBeVisible();
      await expect(page.getByTestId("flow-main")).not.toHaveAttribute("data-status", "playing");
      await page.keyboard.press("Escape");
      await expect(panel).toBeHidden();
      await expect(node).toBeFocused();

      const caddy = page.getByTestId("flow-main-node-p_caddy");
      await caddy.focus();
      await page.keyboard.press("Enter");
      await expect(panel).toHaveAttribute("data-node", "p_caddy");
      await expect(panel).toContainText("Caddy");
      await expect(panel.getByTestId("cap-badge")).toBeVisible();
      await expect(panel.getByTestId("arch-code-link")).toHaveAttribute("href", /^https:\/\/github\.com\/[^/]+\/falcon-lens\/blob\/main\/infra\/gateway\/Caddyfile$/);
      await expect(panel).not.toContainText("infra/gateway");
      await page.getByTestId("arch-panel-close").click();
      await expect(panel).toBeHidden();
    });

    test("the text version lists every step and every part", async ({ page }) => {
      await page.goto("/docs");
      const alt = page.getByTestId("flow-main-alt");
      await alt.locator("summary").first().click();
      await expect(alt.locator(".af-alt-steps > li")).toHaveCount(MAIN_FLOW.steps.length);
      await expect(alt.locator(".af-alt-band li")).toHaveCount(nodesOf(MAIN_FLOW).length);
      await expect(alt.locator(".af-alt-steps > li").first()).toHaveText(MAIN_FLOW.steps[0]!.caption[lang]);
      await expect(alt.locator("details.al-layer")).toHaveCount(3);
      expect(await overflow(page)).toBeLessThanOrEqual(0);
    });

    test("reduced motion: static, fully labelled, the whole path drawn, no play button", async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto("/docs");
      const fig = page.getByTestId("flow-main");
      await fig.scrollIntoViewIfNeeded();
      await expect(fig).toHaveAttribute("data-motion", "static");
      await expect(fig).toHaveAttribute("data-status", "idle");
      await expect(page.getByTestId("flow-main-toggle")).toHaveCount(0);
      await expect(page.getByTestId("flow-main-replay")).toHaveCount(0);
      await expect(fig.locator(".af-dots")).toBeHidden();
      const offsets = await page.getByTestId("flow-main-wires").locator("path.af-wire-on").evaluateAll((els) => els.map((e) => Number(e.getAttribute("stroke-dashoffset"))));
      expect(offsets.length).toBe(MAIN_FLOW.steps.length - 1);
      expect(offsets.every((o) => o === 0)).toBe(true);
      // Every box is visible with its label, and the boxes on the path carry their number.
      for (const n of nodesOf(MAIN_FLOW)) await expect(page.getByTestId(`flow-main-node-${n.id}`).locator(".af-node-text b")).toBeVisible();
      await expect(fig.locator(".af-no")).toHaveCount(MAIN_FLOW.steps.length);
      await expect(page.getByTestId("flow-main-node-s_approval").locator(".af-no")).toHaveText(String(MAIN_FLOW.steps.length));
      expect(await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length)).toBe(0);
      await page.waitForTimeout(1600);
      expect(await stepOf(page, "main")).toBe(-1);
      // The steps can still be read one at a time, and the hint says so (it never asks for a Play button that is not there).
      await expect(page.getByTestId("flow-main-caption")).toHaveText(lang === "ar" ? "استخدم «الخطوة التالية» لتقرأ المسار خطوة بخطوة." : "Use Next step to read the path one step at a time.");
      await page.getByTestId("flow-main-next").click();
      await expect(page.getByTestId("flow-main-caption")).toContainText(MAIN_FLOW.steps[0]!.caption[lang]);
      await expect(page.getByTestId("flow-main-node-v_mic")).toHaveAttribute("data-state", "active");
      expect(await serious(page, '[data-testid="flow-main"]')).toEqual([]);
    });
  });
}

test.describe("agent diagrams on /docs/agents", () => {
  for (const lang of ["ar", "en"] as const) {
    test(`Baseer, Dir', the model route and the DSPy pipeline render with logos and step (${lang})`, async ({ page, context, baseURL }) => {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/docs/agents");
      for (const spec of [BASEER_FLOW, DIR_FLOW, ROUTE_FLOW, DSPY_FLOW]) {
        const fig = page.getByTestId(`flow-${spec.id}`);
        await fig.scrollIntoViewIfNeeded();
        await expect(fig.locator(".af-node")).toHaveCount(nodesOf(spec).length);
        await expect(fig.locator(".af-node .tb")).toHaveCount(nodesOf(spec).length);
        await seek(page, spec.id, 3 * 1300 + 700);
        await expect(page.getByTestId(`flow-${spec.id}-caption`)).toContainText(spec.steps[3]!.caption[lang]);
        await expect(page.getByTestId(`flow-${spec.id}-node-${spec.steps[3]!.node}`)).toHaveAttribute("data-state", "active");
        await expect(page.getByTestId(`flow-${spec.id}-logo-note`)).toBeVisible();
      }
      await expect(page.getByTestId("flow-dir-group-stategraph").locator('.af-group-title .tb[data-logo="langgraph"]')).toHaveCount(1);
      await expect(page.getByTestId("flow-route-node-r_claude").locator('.tb[data-logo="claude"]')).toHaveCount(1);
      expect(await overflow(page)).toBeLessThanOrEqual(0);
    });
  }

  test("the lane diagram shows tool badges and its walk-through steps on demand only", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/docs/agents");
    const lanes = page.getByTestId("arch-diagram");
    await lanes.scrollIntoViewIfNeeded();
    await expect(page.getByTestId("arch-node-bus").locator('.tb[data-logo="redis"]')).toHaveCount(1);
    await expect(page.getByTestId("arch-node-cloud").locator('.tb[data-logo="claude"]')).toHaveCount(1);
    await expect(lanes.locator('.an-item[data-flow="true"]')).toHaveCount(0);
    await page.getByTestId("arch-walk-full-next").click();
    await expect(page.getByTestId("arch-node-t0").locator("xpath=..")).toHaveAttribute("data-flow", "true");
    await expect(page.getByTestId("arch-walk-full-count")).toContainText("1");
    await page.getByTestId("arch-walk-full-toggle").click();
    await expect.poll(() => lanes.locator('.an-item[data-flow="true"] .an').getAttribute("data-testid"), { timeout: 6000 }).toBe("arch-node-t1");
    await page.getByTestId("arch-walk-full-toggle").click();
    await expect(page.getByTestId("arch-walk-full-toggle")).toHaveAttribute("aria-pressed", "false");
  });

  test("status follows the capability flags: DSPy is In progress until its flag is true", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await forceCaps(context, baseURL!, "false");
    await page.goto("/docs/agents");
    await expect(page.getByTestId("flow-dspy-node-y_opt").locator(".af-prog")).toHaveText("In progress");
    await expect(page.getByTestId("flow-route-node-r_claude").locator(".af-prog")).toHaveText("In progress");
    await forceCaps(context, baseURL!, "true");
    await page.goto("/docs/agents");
    await expect(page.getByTestId("flow-dspy-node-y_opt").locator(".af-prog")).toHaveCount(0);
    await expect(page.getByTestId("flow-dspy-node-y_opt")).toContainText("Status: Live");
  });
});

for (const [lang, theme] of [["ar", "dark"], ["en", "light"], ["ar", "light"], ["en", "dark"]] as const) {
  test(`axe: no serious finding on the animated diagrams (${lang}/${theme})`, async ({ page, context, baseURL }) => {
    test.setTimeout(120_000);
    await setPrefs(context, baseURL!, { lang, theme });
    for (const [path, ids] of [["/docs", ["main"]], ["/agents", ["main"]], ["/docs/agents", ["main", "baseer", "dir", "route", "dspy"]]] as const) {
      await page.goto(path);
      await page.evaluate(() => document.fonts.ready);
      for (const id of ids) {
        const fig = page.getByTestId(`flow-${id}`);
        await fig.scrollIntoViewIfNeeded();
        // Mid-run (one box active, some done), with the build-in finished.
        await seek(page, id, 4 * 1300 + 700);
        await page.waitForTimeout(1700);
        expect(await serious(page, `[data-testid="flow-${id}"]`), `${path} ${id}`).toEqual([]);
      }
      expect(await overflow(page), path).toBeLessThanOrEqual(0);
    }
  });
}
