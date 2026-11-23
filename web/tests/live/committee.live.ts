/**
 * Committee walkthrough against a RUNNING stack (read-only: only submits checks of reserved
 * `.test` fixture names and loads pages).
 *   LIVE_BASE_URL=https://localhost:8443 pnpm exec playwright test --project=live
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, setPrefs, submitText, test, token } from "../e2e/helpers";

const FINAL = { timeout: 60_000 };

test("a Falcon Demo Bank lookalike is rated dangerous, with reasons and a next step", async ({ page }) => {
  await page.goto("/");
  await submitText(page, `http://falcon-demo-bank-secure.test/login?c=${token()}`);
  await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final", FINAL);
  await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
  expect(await page.getByTestId("verdict-card").locator("ol li, .reasons li").count()).toBeGreaterThan(0);
  await expect(page.getByTestId("impersonated")).toContainText("بنك الصقر التجريبي");
  await expect(page.getByTestId("result").locator("a")).toHaveCount(0);
});

test("the official fixture gets 'no warning signs' with the caution reminder, never 'safe'", async ({ page }) => {
  await page.goto("/");
  await submitText(page, "http://falcon-demo-bank.test/");
  await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final", FINAL);
  await expect(page.getByTestId("verdict-word")).toHaveText("لم نجد علامات تحذير");
  await expect(page.getByTestId("verdict-card")).toContainText("ابقَ حذراً");
  expect(await page.getByTestId("result").innerText()).not.toMatch(/آمن|\bsafe\b/i);
});

test("a message carrying a fixture link reaches a final verdict", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("kind-message").click();
  await submitText(page, `عميلنا العزيز، تم إيقاف حسابك. أكمل التحقق الآن: http://falcon-demo-bank-secure.test/verify?c=${token()}`);
  await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final", FINAL);
  await expect(page.getByTestId("verdict-word")).toBeVisible();
});

test("campaign and incident boards render a real state (not an error page)", async ({ page }) => {
  await page.goto("/campaigns");
  await expect(page.locator("main h1, main h2").first()).toBeVisible();
  await expect(page.getByTestId("board-not-connected").or(page.getByTestId("board-empty")).or(page.getByTestId("campaigns"))).toBeVisible();
  await page.goto("/ops");
  await expect(page.getByTestId("ops-unauthorized").or(page.getByTestId("ops-not-connected")).or(page.getByTestId("ops-empty")).or(page.getByTestId("incident-card").first())).toBeVisible();
});

test("language and theme toggles flip direction, persist across reload", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await page.getByTestId("theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("share-target: GET fallback pre-fills the box without checking; cross-site POST is refused", async ({ page, request }) => {
  await page.goto(`/share?text=${encodeURIComponent("http://falcon-demo-bank-secure.test/x")}`);
  await expect(page).toHaveURL(/\/\?text=/);
  await expect(page.getByTestId("check-input")).toHaveValue(/falcon-demo-bank-secure\.test/);
  await expect(page.getByTestId("result")).toHaveCount(0);
  const refused = await request.post("/share", { headers: { "sec-fetch-site": "cross-site" }, multipart: { text: "x" }, maxRedirects: 0 });
  expect(refused.status()).toBe(303);
  expect(refused.headers()["location"]).toBe("/");
});

for (const path of ["/", "/how-it-works", "/architecture/agents", "/results", "/authorities", "/privacy", "/campaigns", "/ops", "/missing-page"]) {
  test(`${path} through the gateway: axe has no serious or critical violation`, async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "ar" });
    await page.goto(path);
    await page.evaluate(() => document.fonts.ready);
    const found = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  });
}
