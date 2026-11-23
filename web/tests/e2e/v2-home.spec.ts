/**
 * Web v2, part A: navigation and redirects, Home (two AI agents, outcomes, proof strip), Sentinel ticker,
 * /agents and Results. Badges are tested with the capability flags forced false AND true: the mock gateway
 * routes the `mock_caps` cookie to an app instance whose /v1/meta reports every flag as that value.
 */
import type { BrowserContext, Page } from "@playwright/test";
import { DEMO_CAMPAIGNS } from "../../lib/demo";
import { formatRate } from "../../lib/fp-regress";
import fp from "../../lib/fp-regress.generated.json";
import results from "../../lib/results.generated.json";
import { formatCi, formatMetric } from "../../lib/results";
import { XSS } from "../fixtures";
import { expect, newIncidentId, setPrefs, test, useBoards } from "./helpers";

const forceCaps = (context: BrowserContext, baseURL: string, mode: "false" | "true") => context.addCookies([{ name: "mock_caps", value: mode, url: baseURL }]);
const metrics = (results as unknown as { data: { metrics: Record<string, number | number[]> } }).data.metrics;
const fpData = (fp as unknown as { data: { by_serves_web: { serves_web_page: { n: number; false_positive_rate: { value: number; ci95: number[] } } }; false_positive_rate: { value: number; ci95: number[] }; counts: Record<string, number> } }).data;
const camp = (id: string, patch: Record<string, unknown> = {}) => ({ ...DEMO_CAMPAIGNS[0], campaign_id: id, source: "live", ...patch });

async function noHorizontalScroll(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

test.describe("navigation and redirects (W2-02)", () => {
  test("both redirects are permanent (308)", async ({ request }) => {
    const a = await request.get("/how-it-works", { maxRedirects: 0 });
    expect(a.status()).toBe(308);
    expect(a.headers().location).toBe("/agents");
    const b = await request.get("/architecture/agents", { maxRedirects: 0 });
    expect(b.status()).toBe(308);
    expect(b.headers().location).toBe("/docs/agents");
    const landed = await request.get("/how-it-works");
    expect(landed.status()).toBe(200);
  });

  test("header order, aria-current on each route, campaigns and incident board only in the footer", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/");
    const links = await page.locator("header nav a").evaluateAll((els) => els.map((e) => e.getAttribute("href")));
    expect(links).toEqual(["/", "/agents", "/results", "/authorities", "/docs", "/privacy"]);
    await expect(page.locator('footer a[href="/campaigns"]')).toHaveCount(1);
    await expect(page.locator('footer a[href="/ops"]')).toHaveCount(1);
    for (const href of ["/", "/agents", "/results", "/authorities", "/privacy"]) {
      await page.goto(href);
      await expect(page.locator('header nav a[aria-current="page"]')).toHaveAttribute("href", href);
      await expect(page.locator('header nav a[aria-current="page"]')).toHaveCount(1);
    }
  });

  test("the brand never wraps and nothing scrolls sideways, in both languages", async ({ page, context, baseURL }) => {
    for (const lang of ["ar", "en"] as const) {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/");
      const box = await page.locator("header .brand span").first().boundingBox();
      const line = await page.locator("header .brand span").first().evaluate((el) => parseFloat(getComputedStyle(el).lineHeight));
      expect(box!.height, lang).toBeLessThan(line * 2.2); // one line of the name (the small caption is hidden on a phone)
      await noHorizontalScroll(page);
    }
  });

  test("the menu opens, closes with Escape and returns focus (phone)", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByTestId("menu-toggle");
    test.skip(!(await toggle.isVisible()), "the menu button is a phone and tablet control");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toBeFocused();
  });
});

test.describe("home: two AI agents (W2-03)", () => {
  test("the headline names the AI agents in both languages; no tier codes before a check", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("AI agents");
    expect(await page.locator("body").innerText()).not.toMatch(/\bT[0-3]\b/);
    await setPrefs(context, baseURL!, { lang: "ar" });
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("ذكاء اصطناعي");
    expect(await page.locator("body").innerText()).not.toMatch(/\bT[0-3]\b/);
    await noHorizontalScroll(page);
  });

  test("all flags false: the AI second look and the Sentinel show In progress in the hero; sections too", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await forceCaps(context, baseURL!, "false");
    await page.goto("/");
    const inv = page.locator('[data-testid^="agent-"][data-agent="inv"]:visible');
    const sen = page.locator('[data-testid^="agent-"][data-agent="sen"]:visible');
    await expect(inv.getByTestId("cap-badge")).toContainText("In progress");
    await expect(sen.getByTestId("cap-badge")).toContainText("In progress");
    await expect(inv.getByTestId("cap-badge")).toHaveAttribute("data-live", "false");
    await expect(page.getByTestId("meet-inv").getByTestId("cap-badge")).toContainText("In progress");
    await expect(page.getByTestId("meet-sen").getByTestId("cap-badge")).toContainText("In progress");
    await expect(page.getByTestId("sentinel-ticker").getByTestId("cap-badge")).toContainText("In progress");
    // kind tabs carry a badge when their flag is false
    await expect(page.getByTestId("check-form").getByTestId("cap-badge").first()).toBeVisible();
  });

  test("all flags true: Live badges, no In progress in the hero", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await forceCaps(context, baseURL!, "true");
    await page.goto("/");
    const inv = page.locator('[data-testid^="agent-"][data-agent="inv"]:visible');
    const sen = page.locator('[data-testid^="agent-"][data-agent="sen"]:visible');
    await expect(inv.getByTestId("cap-badge")).toContainText("Live");
    await expect(sen.getByTestId("cap-badge")).toContainText("Live");
    await expect(page.getByTestId("meet").getByTestId("cap-badge")).toHaveCount(2);
    await expect(page.getByTestId("meet").getByText("In progress")).toHaveCount(0);
    await expect(page.getByTestId("sentinel-ticker").getByTestId("cap-badge")).toHaveCount(0);
  });

  test("under reduced motion the radar and lens are static", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    expect(await page.locator(".rg-sweepdiv").first().evaluate((el) => getComputedStyle(el).display)).toBe("none");
    expect(await page.locator(".lens-sweep").first().evaluate((el) => getComputedStyle(el).display)).toBe("none");
  });

  test("four outcomes, the meet section and the authority band are present, and no text says safe", async ({ page, context, baseURL }) => {
    for (const lang of ["ar", "en"] as const) {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/");
      await expect(page.getByTestId("outcomes").locator("li")).toHaveCount(4);
      await expect(page.getByTestId("auth-band")).toContainText(lang === "ar" ? "غير مربوط" : "Not connected");
      const text = await page.locator("main").innerText();
      expect(text).not.toMatch(/\bsafe\b/i);
      expect(text).not.toMatch(/(^|[\s«])آمن(ة)?([\s».,:]|$)/);
    }
  });
});

test.describe("sentinel ticker (W2-04)", () => {
  test("counts equal the mocked data; latest title shown", async ({ page, context, request, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await useBoards(context, request, baseURL!, {
      campaigns: [camp(newIncidentId(), { count: 3, last_seen: "2026-11-20T10:00:00Z", title: { en: "Older wave", ar: "موجة أقدم" } }), camp(newIncidentId(), { count: 4, last_seen: "2026-11-22T10:00:00Z", title: { en: "Newest wave", ar: "موجة أحدث" } })],
    });
    await page.goto("/");
    await expect(page.getByTestId("ticker-count")).toHaveText("Active campaigns: 2 · Linked checks: 7");
    await expect(page.getByTestId("ticker-latest")).toHaveText("Newest wave");
    await expect(page.getByTestId("ticker-demo")).toHaveCount(0);
  });

  test("a non-live source is labelled DEMO DATA", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { campaigns: [camp(newIncidentId(), { source: "synthetic" })] });
    await page.goto("/");
    await expect(page.getByTestId("ticker-demo")).toBeVisible();
  });

  test("empty and unreachable states show no number", async ({ page, context, request, baseURL }) => {
    await page.goto("/"); // no board registered: the mock answers 404
    await expect(page.getByTestId("ticker-offline")).toBeVisible();
    await expect(page.getByTestId("sentinel-ticker")).not.toContainText(/\d/);
    await useBoards(context, request, baseURL!, { campaigns: [] });
    await page.goto("/");
    await expect(page.getByTestId("ticker-empty")).toBeVisible();
    await expect(page.getByTestId("ticker-count")).toHaveCount(0);
  });

  test("a hostile campaign title renders as text", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { campaigns: [camp(newIncidentId(), { title: { ar: `حملة ${XSS.img}`, en: `Campaign ${XSS.img}` } })] });
    let dialog = false;
    page.on("dialog", () => { dialog = true; });
    await page.goto("/");
    await expect(page.getByTestId("ticker-latest")).toContainText("<img");
    await expect(page.getByTestId("sentinel-ticker").locator("img")).toHaveCount(0);
    expect(dialog).toBe(false);
  });
});

test.describe("/agents (W2-05)", () => {
  test("one H1, six numbered steps, the docs link; no pattern or tool names", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/agents");
    await expect(page.locator("main h1")).toHaveCount(1);
    await expect(page.locator(".lane-steps li")).toHaveCount(6);
    await expect(page.getByTestId("agents-docs-link")).toHaveAttribute("href", "/docs/agents");
    await expect(page.getByTestId("handoff")).toBeVisible();
    const text = await page.locator("main").innerText();
    for (const banned of ["LangGraph", "T3", "state machine", "StateGraph"]) expect(text).not.toContain(banned);
    expect(text).not.toMatch(/\bsafe\b/i);
  });

  test("flags false: step 2 and the Sentinel lane say In progress", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await forceCaps(context, baseURL!, "false");
    await page.goto("/agents");
    await expect(page.getByTestId("lane-inv").getByTestId("cap-badge")).toHaveCount(1);
    await expect(page.getByTestId("lane-inv").getByTestId("cap-badge")).toContainText("In progress");
    await expect(page.getByTestId("lane-sen").getByTestId("cap-badge")).toContainText("In progress");
  });

  test("flags true: both say Live", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await forceCaps(context, baseURL!, "true");
    await page.goto("/agents");
    await expect(page.getByTestId("lane-inv").getByTestId("cap-badge")).toContainText("Live");
    await expect(page.getByTestId("lane-sen").getByTestId("cap-badge")).toContainText("Live");
  });

  test("Arabic page has no sideways scroll", async ({ page }) => {
    await page.goto("/agents");
    await noHorizontalScroll(page);
  });
});

test.describe("proof strip and results (W2-08, ruling 3)", () => {
  for (const lang of ["ar", "en"] as const) {
    for (const path of ["/", "/results"]) {
      test(`${path} ${lang}: offline numbers equal the artifact, beside their scope line and the live false-alarm figure`, async ({ page, context, baseURL }) => {
        await setPrefs(context, baseURL!, { lang });
        await page.goto(path);
        const proof = page.getByTestId(path === "/" ? "proof-home" : "proof-results");
        const recall = metrics["test.recall"] as number;
        const fpr = metrics["test.fpr"] as number;
        await expect(proof.getByTestId("proof-recall")).toContainText(formatMetric("recall", recall, lang));
        await expect(proof.getByTestId("proof-recall")).toContainText(formatCi({ key: "recall", value: recall, lo: (metrics["test.recall_ci95"] as number[])[0]!, hi: (metrics["test.recall_ci95"] as number[])[1]! }, lang));
        await expect(proof.getByTestId("proof-fpr")).toContainText(formatMetric("fpr", fpr, lang));
        await expect(proof.getByTestId("proof-official")).toContainText(String(metrics["test.official_false_dangerous"]));
        // scope line, always beside the numbers, with the artifact name and the test size
        await expect(proof.getByTestId("proof-scope")).toContainText(String(metrics["test.n"]));
        await expect(proof.getByTestId("proof-scope")).toContainText((results as { artifact: string }).artifact);
        await expect(proof.getByTestId("proof-scope")).toContainText(lang === "ar" ? "مرحلة تحليل العنوان فقط" : "Address-analysis stage only");
        // the live held-out measurement, with range and n, next to it
        const web = fpData.by_serves_web.serves_web_page;
        const live = proof.getByTestId("live-fp");
        await expect(live.getByTestId("live-fp-web")).toContainText(String(web.n));
        await expect(live.getByTestId("live-fp-web")).toContainText(formatRate(web.false_positive_rate.value, lang));
        await expect(live.getByTestId("live-fp-web")).toContainText(formatRate(web.false_positive_rate.ci95[0]!, lang));
        await expect(live.getByTestId("live-fp-web")).toContainText(formatRate(web.false_positive_rate.ci95[1]!, lang));
        await expect(live.getByTestId("live-fp-all")).toContainText(String(Object.values(fpData.counts).reduce((a, b) => a + b, 0)));
        await expect(live.getByTestId("live-fp-all")).toContainText(formatRate(fpData.false_positive_rate.value, lang));
        // Western digits in Arabic
        if (lang === "ar") expect(await proof.innerText()).not.toMatch(/[٠-٩]/);
        // no speed figure anywhere on these pages
        expect(await page.locator("main").innerText()).not.toMatch(/\b\d+(\.\d+)?\s?(ms|ثانية|seconds)\b/i);
      });
    }
  }

  test("results: tables, not-measured list, provenance and the evaluation docs link", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/results");
    await expect(page.getByTestId("split-test")).toBeVisible();
    await expect(page.getByTestId("not-evaluated")).toBeVisible();
    await expect(page.locator('main a[href="/docs/evals"]')).toBeVisible();
    // message_path.* is never shown (spec flag 4)
    expect(await page.locator("main").innerText()).not.toContain("message_path");
  });
});
