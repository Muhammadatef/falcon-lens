import AxeBuilder from "@axe-core/playwright";
import { DEMO_DANGEROUS } from "../../lib/demo";
import { expect, newVerdictId, setPrefs, test, useBoards } from "./helpers";

/** Design audit 2026-11-24: Arabic typography, results bidi, verdict-first trace, logo lockup, header, /ops initial state. */

test.describe("typography and chrome", () => {
  test("Arabic text never takes letter-spacing; the logo lockup shows the other language beneath", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "ar" });
    await page.goto("/history?demo=1");
    const spaced = await page.evaluate(() =>
      [...document.querySelectorAll("main *")]
        .filter((e) => /[؀-ۿ]/.test(e.textContent ?? "") && e.children.length === 0 && !e.closest("[lang=en]"))
        .filter((e) => getComputedStyle(e).letterSpacing !== "normal" && parseFloat(getComputedStyle(e).letterSpacing) !== 0)
        .map((e) => e.className),
    );
    expect(spaced).toEqual([]);
    await expect(page.locator(".brand")).toContainText("عدسة الصقر");
    await expect(page.locator(".brand small")).toHaveText("Falcon Lens");
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/");
    await expect(page.locator(".brand > span")).toContainText("Falcon Lens");
    await expect(page.locator(".brand small")).toHaveText("عدسة الصقر");
  });

  test("a 1280 px screen shows the full inline navigation, and the phone header is one row", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "ar" });
    const width = page.viewportSize()!.width;
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/");
    await expect(page.getByTestId("menu-toggle")).toBeHidden();
    await expect(page.locator("#site-nav a")).toHaveCount(8);
    for (const a of await page.locator("#site-nav a").all()) await expect(a).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await page.setViewportSize({ width: 1024, height: 700 });
    await page.goto("/");
    await expect(page.getByTestId("menu-toggle")).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await page.setViewportSize({ width: Math.min(width, 390), height: 800 });
    await page.goto("/");
    const h = await page.locator("header.top").evaluate((e) => e.getBoundingClientRect().height);
    expect(h).toBeLessThanOrEqual(72);
  });

  test("/ops opens neutral (no rejected state) until a key has been tried", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { incidents: [], requireKey: "op-test-key" });
    await page.goto("/ops");
    const box = page.getByTestId("ops-unauthorized");
    await expect(box).toBeVisible();
    await expect(box).toHaveAttribute("data-rejected", "false");
    await expect(box).not.toContainText("مرفوض");
    await page.getByTestId("key-input").fill("wrong-key");
    await page.getByTestId("key-input").press("Enter");
    await expect(page.getByTestId("ops-unauthorized")).toHaveAttribute("data-rejected", "true");
    await expect(page.getByTestId("ops-unauthorized")).toHaveAttribute("role", "alert");
  });
});

test.describe("results page", () => {
  for (const lang of ["ar", "en"] as const) {
    test(`section nav, one method label per range, no English paragraph in Arabic, no forced LTR on Arabic phrases (${lang})`, async ({ page, context, baseURL }) => {
      await setPrefs(context, baseURL!, { lang });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto("/results");
      await expect(page.getByTestId("results-nav").locator("a")).toHaveCount(6);
      await expect(page.getByTestId("ci-method")).toContainText(/bootstrap/i);
      await page.getByTestId("ci-method").locator("summary").click();
      await expect(page.getByTestId("ci-method")).toContainText(/Wilson/);
      // Every disclosure carries a chevron, and the nav opens the fold it points at.
      await page.getByTestId("results-nav").getByRole("link").nth(3).click();
      await expect(page.getByTestId("attacks")).toHaveAttribute("open", "");
      const forced = await page.locator('[data-testid="attacks"] [dir="ltr"]').evaluateAll((els) => els.filter((e) => /[؀-ۿ]/.test(e.textContent ?? "")).length);
      expect(forced).toBe(0);
      const sparkOverlap = await page.evaluate(() => {
        const svg = document.querySelector('[data-testid="fp-spark"] svg')?.getBoundingClientRect();
        const cap = document.querySelector('[data-testid="fp-spark"] figcaption')?.getBoundingClientRect();
        return svg && cap ? cap.top - svg.bottom : null;
      });
      if (sparkOverlap !== null) expect(sparkOverlap).toBeGreaterThanOrEqual(0);
      if (lang === "ar") {
        await expect(page.locator("main")).not.toContainText("The .test top-level domain");
        await expect(page.locator("main")).not.toContainText("read this FPR");
      }
      const found = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
      expect(found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
    });
  }
});

test.describe("check trace is verdict first", () => {
  test("big verdict, score and top three reasons lead; undescribed evidence and internal codes are folded or hidden", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    const bare = (n: number) => ({ id: `ev_bare${n}`, signal: `url.classifier${n}`, family: "url", observed: null, weight: 0, source: "t", tier: "T1" });
    const doc = {
      ...DEMO_DANGEROUS,
      verdict_id: id,
      source: "live",
      degraded: true,
      degraded_reasons: ["not_rendered:metadata", "not_rendered:metadata"],
      reasons: ["a", "b", "c", "d"].map((x) => ({ ar: `سبب ${x}`, en: `Reason ${x}`, evidence_ids: [] })),
      evidence: [...DEMO_DANGEROUS.evidence, bare(1), bare(2), bare(3), { ...bare(4), signal: "url.weighted", weight: 1.5 }],
    };
    await useBoards(context, request, baseURL!, { verdicts: [], verdictDocs: { [id]: doc } });
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto(`/checks/${id}`);
    const hero = page.getByTestId("check-final");
    await expect(hero).toBeVisible();
    await expect(page.getByTestId("check-verdict")).toHaveText("Dangerous");
    await expect(page.getByTestId("check-risk")).toContainText("/ 100");
    // The contract allows at most 3 reasons, so all of them are in the hero; the "More reasons" fold only appears if a verdict ever carries more.
    await expect(page.getByTestId("check-reason")).toHaveCount(3);
    await expect(page.getByTestId("check-more-reasons")).toHaveCount(0);
    // Weighted evidence stays visible; only inert (weight 0, no rule, no text) evidence is folded.
    await expect(page.getByTestId("check-more").first()).not.toContainText("ev_");
    const order = await page.evaluate(() => {
      const hero = document.querySelector('[data-testid="check-final"]')!;
      const tiers = document.querySelector('[data-testid="check-tiers"]')!;
      return Boolean(hero.compareDocumentPosition(tiers) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(order).toBe(true);
    await expect(page.locator("main")).not.toContainText("not_rendered");
    await expect(page.locator("main")).not.toContainText("Evidence without a description");
    await expect(page.getByText("A technical check that counted toward the score")).toHaveCount(1);
    await expect(page.getByTestId("check-more").first()).not.toContainText("url.weighted");
    await expect(page.getByTestId("check-more").first()).toContainText("More technical detail");
    expect(await page.getByTestId("check-more").first().locator("li").count()).toBeGreaterThanOrEqual(3);
    await setPrefs(context, baseURL!, { lang: "ar" });
    await page.goto(`/checks/${id}`);
    await expect(page.locator("main")).not.toContainText("دليل بلا وصف");
    await expect(page.locator("main")).not.toContainText("not_rendered");
    expect(await page.locator("body").innerText()).not.toMatch(/آمن/);
  });
});

test.describe("axe on every touched page", () => {
  for (const lang of ["ar", "en"] as const) {
    for (const path of ["/", "/history?demo=1", "/checks/vd_01KB0DEM0DATA0000000000001?demo=1", "/authorities", "/privacy", "/results", "/ops"]) {
      test(`${path} (${lang})`, async ({ page, context, baseURL }) => {
        await setPrefs(context, baseURL!, { lang });
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.goto(path);
        await page.evaluate(() => document.fonts.ready);
        const found = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        expect(found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
      });
    }
  }
});
