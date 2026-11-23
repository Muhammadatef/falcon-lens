/**
 * Interactive architecture on /docs/agents (full) and /agents (business): tooltip on hover, panel on click,
 * keyboard flow, RTL, capability badges, axe with the panel open (both languages and themes, phone and desktop).
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { forceCaps, expect, setPrefs, test } from "./helpers";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
async function axe(page: Page) {
  const found = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  return found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ") + " " + (n.any[0]?.message ?? "")).join(" | ")}`);
}
const isPhone = (page: Page) => (page.viewportSize()?.width ?? 1440) < 720;

for (const lang of ["en", "ar"] as const) {
  test.describe(`architecture ${lang}`, () => {
    test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang }));

    test("hover shows a tooltip with a plain and a technical sentence", async ({ page }) => {
      test.skip(isPhone(page), "no hover on a touch phone");
      await page.goto("/docs/agents");
      const node = page.getByTestId("arch-node-t1");
      await node.scrollIntoViewIfNeeded();
      await node.hover();
      const tip = page.getByTestId("arch-tip-t1");
      await expect(tip).toBeVisible();
      await expect(tip.locator("b")).not.toBeEmpty();
      await expect(tip.locator("span")).not.toBeEmpty();
      await expect(node).toHaveAttribute("aria-describedby", "tip-t1");
      await page.keyboard.press("Escape");
      await expect(tip).toBeHidden();
    });

    test("click opens the panel with every section; Esc closes it and returns focus", async ({ page }) => {
      await page.goto("/docs/agents");
      const node = page.getByTestId("arch-node-t3");
      await node.scrollIntoViewIfNeeded();
      await node.click();
      const panel = page.getByTestId("arch-panel");
      await expect(panel).toBeVisible();
      await expect(panel).toHaveAttribute("data-node", "t3");
      await expect(panel.locator("h3")).toHaveCount(8);
      await expect(panel.getByTestId("cap-badge")).toBeVisible();
      await expect(panel.locator(".ap-code code").first()).toContainText("packages/falcon_core/src/falcon_core/agent/investigator.py");
      await expect(panel.locator('a[href="/docs/agents"]')).toBeVisible();
      await expect(page.getByTestId("arch-panel-close")).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(panel).toBeHidden();
      await expect(node).toBeFocused();
    });

    test("keyboard only: focus a node, Enter opens, a related node opens from the panel, Space opens a tool", async ({ page }) => {
      await page.goto("/docs/agents");
      await page.getByTestId("arch-node-t0").focus();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("arch-panel")).toHaveAttribute("data-node", "t0");
      await page.getByTestId("arch-rel-t1").focus();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("arch-panel")).toHaveAttribute("data-node", "t1");
      await page.keyboard.press("Escape");
      await expect(page.getByTestId("arch-panel")).toBeHidden();
      await expect(page.getByTestId("arch-node-t1")).toBeFocused();
      await page.getByTestId("arch-node-block_indicator").focus();
      await page.keyboard.press("Space");
      const panel = page.getByTestId("arch-panel");
      await expect(panel).toHaveAttribute("data-node", "block_indicator");
      await expect(panel).toContainText("ttl_hours");
      await expect(panel).toContainText("make unblock");
    });

    test("the business diagram on /agents opens a plain panel without code paths", async ({ page }) => {
      await page.goto("/agents");
      const node = page.getByTestId("arch-node-approval");
      await node.scrollIntoViewIfNeeded();
      await node.click();
      const panel = page.getByTestId("arch-panel");
      await expect(panel).toBeVisible();
      await expect(panel.locator(".ap-code")).toHaveCount(0);
      await expect(panel.getByTestId("cap-badge")).toBeVisible();
      await expect(page.getByTestId("arch-node-rdap_lookup")).toHaveCount(0);
    });

    test("the DSPy badge is In progress and the section says so; no table without artifacts", async ({ page }) => {
      await page.goto("/docs/agents");
      const why = page.getByTestId("why-dspy-langgraph");
      await expect(why).toContainText("dspy.Predict");
      await expect(why).toContainText("BootstrapFewShot");
      await expect(why).toContainText("MIPROv2");
      await expect(why).toContainText("Phoenix");
      await expect(why).not.toContainText("MLflow");
      await expect(page.getByTestId("dspy-status")).toContainText(lang === "ar" ? "قيد الإنجاز" : "In progress");
      await expect(page.getByTestId("dspy-table")).toHaveCount(0);
    });

    test("panel opens on the inline-end side (left in Arabic, right in English) on a wide screen", async ({ page }) => {
      test.skip(isPhone(page), "bottom sheet on a phone");
      await page.goto("/docs/agents");
      await page.getByTestId("arch-node-arbiter").click();
      const box = (await page.getByTestId("arch-panel").boundingBox())!;
      const width = page.viewportSize()!.width;
      if (lang === "ar") expect(box.x).toBeLessThan(5);
      else expect(box.x + box.width).toBeGreaterThan(width - 5);
    });

    test("a phone gets a bottom sheet and no horizontal overflow", async ({ page }) => {
      test.skip(!isPhone(page), "phone only");
      await page.goto("/docs/agents");
      const node = page.getByTestId("arch-node-assess");
      await node.scrollIntoViewIfNeeded();
      expect((await node.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await node.click();
      const box = (await page.getByTestId("arch-panel").boundingBox())!;
      expect(box.width).toBeGreaterThan(380);
      expect(box.y + box.height).toBeGreaterThan(page.viewportSize()!.height - 2);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  });
}

test.describe("capability badges follow the flags", () => {
  test("all flags true: Live; all false: In progress", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await forceCaps(context, baseURL!, "true");
    await page.goto("/docs/agents");
    await page.getByTestId("arch-node-enrich").click();
    await expect(page.getByTestId("arch-panel").getByTestId("cap-badge")).toContainText("Live");
    await forceCaps(context, baseURL!, "false");
    await page.goto("/docs/agents");
    await page.getByTestId("arch-node-enrich").click();
    await expect(page.getByTestId("arch-panel").getByTestId("cap-badge")).toContainText("In progress");
  });
});

for (const lang of ["ar", "en"] as const) {
  for (const theme of ["dark", "light"] as const) {
    test.describe(`axe with the panel open ${lang}/${theme}`, () => {
      test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang, theme }));
      for (const [path, node] of [["/docs/agents", "t2"], ["/agents", "approval"]] as const) {
        test(`${path}`, async ({ page }) => {
          await page.goto(path);
          await page.evaluate(() => document.fonts.ready);
          expect(await axe(page), "closed").toEqual([]);
          const n = page.getByTestId(`arch-node-${node}`);
          await n.scrollIntoViewIfNeeded();
          await n.click();
          await expect(page.getByTestId("arch-panel")).toBeVisible();
          await page.waitForTimeout(400);
          expect(await axe(page), "panel open").toEqual([]);
        });
      }
    });
  }
}

test.describe("LLM tracing follows its flag", () => {
  test("flags false: In progress; flags true: Live (node, panel and section)", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    for (const [mode, word] of [["false", "In progress"], ["true", "Live"]] as const) {
      await forceCaps(context, baseURL!, mode);
      await page.goto("/docs/agents");
      await page.getByTestId("arch-node-phoenix").click();
      await expect(page.getByTestId("arch-panel").getByTestId("cap-badge")).toContainText(word);
      const why = page.getByTestId("why-dspy-langgraph");
      if (mode === "false") await expect(why).toContainText("do not start the tracer yet");
      else await expect(why).toContainText("Every LLM call is traced");
    }
  });
});
