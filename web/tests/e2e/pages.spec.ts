/**
 * Committee-readiness checks on every page: axe (WCAG 2.2 AA) with zero serious/critical
 * violations, both languages and themes, no horizontal overflow, real <h1>, no placeholder text,
 * the independence disclaimer in both languages, and the judge-facing pages' content.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import capabilities from "../../lib/capabilities.generated.json";
import results from "../../lib/results.generated.json";
import { formatMetric } from "../../lib/results";
import { expect, setPrefs, test } from "./helpers";

const PAGES = ["/", "/how-it-works", "/architecture/agents", "/results", "/authorities", "/privacy", "/campaigns", "/ops", "/this-page-does-not-exist"];
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function axe(page: Page) {
  const found = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  return found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
}

for (const lang of ["ar", "en"] as const) {
  for (const theme of ["dark", "light"] as const) {
    test.describe(`pages ${lang}/${theme}`, () => {
      test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang, theme }));

      for (const path of PAGES) {
        test(`${path}: axe clean, no overflow, one h1, no placeholders`, async ({ page }) => {
          const response = await page.goto(path);
          expect(response?.status()).toBe(path.includes("does-not-exist") ? 404 : 200);
          await expect(page.locator("html")).toHaveAttribute("lang", lang);
          await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
          await page.evaluate(() => document.fonts.ready);
          expect(await axe(page)).toEqual([]);
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
          expect(overflow, "horizontal overflow").toBeLessThanOrEqual(0);
          await expect(page.locator("main h1")).toHaveCount(1);
          const text = await page.locator("body").innerText();
          expect(text).not.toMatch(/lorem|TODO|TBD|FIXME|undefined|\[object/i);
          expect(text).not.toContain("DEMO DATA");
        });
      }
    });
  }
}

test.describe("chrome", () => {
  test("footer states independence in Arabic and English on every language", async ({ page, context, baseURL }) => {
    for (const lang of ["ar", "en"] as const) {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/privacy");
      const footer = page.locator("footer");
      await expect(footer.locator('p[lang="ar"]')).toContainText("لا يمثّل شرطة أبوظبي");
      await expect(footer.locator('p[lang="en"]')).toContainText("not affiliated");
      await expect(footer.locator('p[lang="en"]')).toContainText("not been connected");
    }
  });

  test("header links reach every judge-facing page; the menu works from the keyboard", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByTestId("menu-toggle");
    if (await toggle.isVisible()) {
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await toggle.focus();
      await page.keyboard.press("Enter");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await page.keyboard.press("Escape");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await page.keyboard.press("Enter");
    }
    for (const [href, path] of [["/how-it-works", /how-it-works/], ["/results", /results/], ["/authorities", /authorities/], ["/privacy", /privacy/]] as const) {
      await page.goto("/");
      if (await toggle.isVisible()) await toggle.click();
      await page.locator(`header nav a[href="${href}"]`).click();
      await expect(page).toHaveURL(path);
      await expect(page.locator("main h1")).toBeVisible();
    }
  });

  test("title, description and Open Graph follow the language and carry no external assets", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/how-it-works");
    await expect(page).toHaveTitle("How Falcon Lens works · Falcon Lens | عدسة الصقر");
    await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /in four steps|four steps/);
    await expect(page.locator('meta[property="og:locale"]')).toHaveAttribute("content", "en_GB");
    const og = await page.locator('meta[property="og:image"]').getAttribute("content");
    expect(new URL(og!).pathname).toBe("/og/falcon-lens-og.png");
    await setPrefs(context, baseURL!, { lang: "ar" });
    await page.goto("/how-it-works");
    await expect(page).toHaveTitle(/^كيف تعمل عدسة الصقر · عدسة الصقر \| Falcon Lens$/);
    await expect(page.locator('meta[property="og:locale"]')).toHaveAttribute("content", "ar_AE");
    for (const href of ["/favicon.ico", "/icons/apple-touch-icon.png", "/og/falcon-lens-og.png", "/images/how-it-works.svg", "/images/ai-agents.svg"]) {
      const res = await page.request.get(href);
      expect(res.status(), href).toBe(200);
    }
  });
});

test.describe("judge-facing content", () => {
  test("how it works: four steps, four layers, two agents, both figures load", async ({ page }) => {
    await page.goto("/how-it-works");
    await expect(page.locator(".steps4 li")).toHaveCount(4);
    await expect(page.locator(".how-card")).toHaveCount(4);
    await expect(page.locator(".agent")).toHaveCount(2);
    await page.locator(".figure img").first().scrollIntoViewIfNeeded();
    for (const img of await page.locator(".figure img").all()) {
      await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
    }
  });

  test("architecture: both agents, patterns, layers, rejected alternatives; diagram under reduced motion", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/architecture/agents");
    await expect(page.getByTestId("investigator")).toContainText("state machine");
    await expect(page.getByTestId("sentinel")).toContainText("LangGraph StateGraph");
    await expect(page.getByTestId("investigator").locator(".flow-node")).toHaveCount(9);
    await expect(page.getByTestId("sentinel").locator(".flow-node")).toHaveCount(9);
    await expect(page.getByTestId("sentinel")).toContainText("interrupt()");
    await expect(page.getByTestId("loop-diagram")).toBeVisible();
    await expect(page.getByText("A pure classifier").first()).toBeVisible();
    expect(await page.locator(".loop-dot").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
  });

  test("capability badges come from the single flag source, and copy does not overclaim", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    const flags = capabilities as Record<string, boolean>;
    await page.goto("/how-it-works");
    const badges = page.getByTestId("input-kinds").getByTestId("cap-badge");
    await expect(badges).toHaveCount(4);
    await expect(badges.nth(0)).toContainText("Live");
    for (const [i, id] of ["message_check", "email_check", "image_check"].entries()) {
      await expect(badges.nth(i + 1)).toContainText(flags[id] ? "Live" : "In progress (PR #47)");
    }
    await expect(page.locator("main")).not.toContainText("cannot give it orders");
    await page.goto("/privacy");
    const body = await page.locator("main").innerText();
    expect(body).not.toMatch(/30 days/);
    expect(body).toContain("not yet automated");
    await page.goto("/results");
    await expect(page.getByTestId("draft-classifier")).toHaveCount(flags.t1_measured_model ? 0 : 1);
    await expect(page.locator("main")).toContainText("Scope as recorded");
    await expect(page.locator("main")).toContainText("Code revision");
  });

  test("results: every number on the page comes from the bundled published artifact", async ({ page }) => {
    await page.goto("/results");
    const file = results as unknown as { available?: boolean; data?: { metrics: Record<string, number> } };
    if (!file.available) {
      await expect(page.getByTestId("results-pending")).toBeVisible();
      return;
    }
    const m = file.data!.metrics;
    await expect(page.getByTestId("metric-test-precision")).toContainText(formatMetric("precision", m["test.precision"]!, "ar"));
    await expect(page.getByTestId("metric-test-recall")).toContainText(formatMetric("recall", m["test.recall"]!, "ar"));
    await expect(page.getByTestId("metric-test-official")).toContainText(String(m["test.official_false_dangerous"]));
    await expect(page.getByTestId("split-test")).toContainText("95%");
    await expect(page.getByTestId("not-evaluated")).toBeVisible();
  });

  test("authorities: says ready to connect, not connected, and lists REST, MCP, STIX and webhooks", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/authorities");
    await expect(page.getByTestId("not-connected")).toContainText("Ready to connect, not connected");
    for (const name of ["REST v1", "MCP", "STIX 2.1", "Webhooks"]) await expect(page.getByRole("rowheader", { name })).toBeVisible();
    await expect(page.locator("main")).toContainText("Sovereign mode");
    await expect(page.locator("main")).toContainText("Data boundary");
  });

  test("404 and the error boundary are human and actionable", async ({ page }) => {
    await page.goto("/nope");
    await expect(page.getByTestId("not-found")).toContainText("الصفحة غير موجودة");
    await page.getByRole("link", { name: "العودة إلى الفحص" }).click();
    await expect(page).toHaveURL(/\/$/);
  });
});

test.describe("keyboard and zoom", () => {
  test("the check flow is reachable by keyboard alone and the tab order starts at the skip link", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.locator(".skip")).toBeFocused();
    await page.getByTestId("check-input").fill("http://falcon-demo-bank-secure.test/login");
    await page.getByTestId("check-input").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("check-submit")).toBeFocused();
  });

  test("at 200% zoom (narrow CSS width) nothing overflows", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    for (const path of ["/", "/results", "/authorities", "/how-it-works"]) {
      await page.goto(path);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, path).toBeLessThanOrEqual(0);
    }
  });
});
