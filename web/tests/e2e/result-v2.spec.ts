/**
 * v2 check result: verdict, plain reasons, what to do, report, ONE collapsed Technical details row, and the
 * "The Investigator is checking…" activity card (web/design/v2/DESIGN_SPEC.md 3.2). Mocked SSE, fixture data only.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { DEMO_DANGEROUS, DEMO_NWS } from "../../lib/demo";
import { XSS, dangerousStream, nwsStream, withId, xssVerdict } from "../fixtures";
import { badgeWord, onAllOnStack, onDefaultStack } from "./flags";
import { forceCaps, expect, newVerdictId, registerScenario, setPrefs, submitText, test, token } from "./helpers";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const axe = async (page: Page) =>
  (await new AxeBuilder({ page }).withTags(WCAG).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);

async function run(page: Page, request: Parameters<typeof registerScenario>[0], kind: "danger" | "nws", wait = true) {
  const id = newVerdictId();
  const t = token();
  await registerScenario(request, { match: t, verdictId: id, steps: kind === "danger" ? dangerousStream(id) : nwsStream(id) });
  await page.goto("/");
  await submitText(page, `https://falcon-demo-bank${kind === "danger" ? "-secure" : ""}.test/?c=${t}`);
  if (wait) await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final");
}

test.describe("checking state: the Investigator is working", () => {
  test("title names the agent, steps advance with the stream, no provisional 'no warning signs'", async ({ page, request }) => {
    await run(page, request, "nws", false);
    await expect(page.getByTestId("activity-title")).toContainText("المحقّق");
    await expect(page.getByTestId("act-wait")).toContainText("لا تضغط على الرابط");
    await expect(page.getByTestId("act-step-T0")).toHaveAttribute("data-status", "done");
    await expect(page.getByTestId("act-step-T1")).toHaveAttribute("data-status", /running|done/);
    // The partial verdicts of this stream say no_warning_signs; nothing may say so before `final`.
    expect(await page.getByTestId("result").innerText()).not.toContain("لم نجد علامات تحذير");
    await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final");
    await expect(page.getByTestId("activity-title")).toContainText("أنهى «المحقّق» الفحص خلال");
    await expect(page.getByTestId("act-wait")).toHaveCount(0);
  });

  test("English title and no tier codes in the activity card", async ({ page, request, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await run(page, request, "danger", false);
    await expect(page.getByTestId("activity-title")).toContainText("The Investigator is checking your link");
    await expect(page.getByTestId("activity")).not.toContainText(/\bT[0-3]\b/);
    await expect(page.getByTestId("activity-title")).toContainText("The Investigator finished in");
  });
});

test.describe("dangerous result: everything a resident needs is visible without opening Technical details", () => {
  test("plate, three reasons, actions and three channels; ids, rules, score and tiers only after opening", async ({ page, request }) => {
    await run(page, request, "danger");
    await expect(page.getByTestId("verdict-plate")).toBeInViewport();
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("reasons").locator("li")).toHaveCount(3);
    await expect(page.getByTestId("act-now")).toBeVisible();
    await expect(page.getByTestId("act-acted")).toBeVisible();
    await expect(page.getByTestId("act-report").locator(".channel")).toHaveCount(3);
    await expect(page.getByTestId("act-report")).toContainText("999");
    await expect(page.getByTestId("act-report")).toContainText("2026-11-22");
    await expect(page.getByTestId("tech-details")).toBeVisible();

    const shown = await page.getByTestId("result").innerText();
    expect(shown).not.toMatch(/ev_[a-z0-9]/i);
    expect(shown).not.toContain("قاعدة حاسمة");
    expect(shown).not.toContain("97 / 100");
    expect(shown).not.toMatch(/\bT[0-3]\b/);

    await page.getByTestId("tech-summary").click();
    const opened = await page.getByTestId("result").innerText();
    expect(opened).toMatch(/ev_dom0age001/);
    expect(opened).toContain("97 / 100");
    expect(opened).toMatch(/\bT2\b/);
    expect(opened).toMatch(/H1/);
    await expect(page.getByTestId("tech-details").locator('a[href="/docs/cascade"]')).toBeVisible();
  });

  test("reading order: plate, why, caution/now, acted, report, technical details (strict one column on a phone; now and acted may share a row on desktop)", async ({ page, request, isMobile }) => {
    // Reduced motion: the reasons and actions rise in with a stagger, and a transform in flight would skew the measured tops.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await run(page, request, "danger");
    await page.waitForTimeout(500);
    const y = async (sel: string) => (await page.locator(sel).first().boundingBox())!.y;
    const ids = ["verdict-plate", "reasons", "act-now", "act-acted", "act-report", "tech-details"];
    const order = [];
    for (const id of ids) order.push(await y(`[data-testid="${id}"]`));
    if (isMobile) {
      // Phone: one column, strictly top to bottom (spec 3.2).
      for (let i = 1; i < order.length; i++) expect(order[i]!, `${ids[i]} below ${ids[i - 1]}`).toBeGreaterThan(order[i - 1]!);
    } else {
      // Desktop: the two action cards sit side by side (spec 3.2: the verdict column is unchanged, activity is the side column).
      for (let i = 1; i < order.length; i++) expect(order[i]!, `${ids[i]} not above ${ids[i - 1]}`).toBeGreaterThanOrEqual(order[i - 1]! - 1);
      expect(order[4]!, "report below the action cards").toBeGreaterThan(order[3]!);
      expect(order[5]!, "technical details below the report").toBeGreaterThan(order[4]!);
    }
  });

  test("Technical details toggles from the keyboard with Enter and Space", async ({ page, request }) => {
    await run(page, request, "danger");
    const details = page.getByTestId("tech-details");
    await page.getByTestId("tech-summary").focus();
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("open", "");
    await page.keyboard.press("Space");
    await expect(details).not.toHaveAttribute("open", "");
  });

  test("a citation highlights its evidence row inside the opened panel", async ({ page, request }) => {
    await run(page, request, "danger");
    await page.getByTestId("tech-summary").click();
    await page.getByTestId("cite").filter({ hasText: "ev_dom0age001" }).click();
    const row = page.locator('[data-testid="evidence-row"][data-evidence="ev_dom0age001"]');
    await expect(row).toHaveClass(/hit/);
    await expect(row).toBeInViewport();
  });

  test("the verdict plate is readable within two seconds of the final event, even with a 4x slower CPU", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict: withId(DEMO_DANGEROUS, id) }] });
    await page.goto("/");
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toBeVisible({ timeout: 2000 });
    await expect(page.getByTestId("verdict-plate")).toBeInViewport({ timeout: 2000 });
  });

  test("reasons are plain text: XSS payloads are inert and the details panel stays closed", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict: xssVerdict(id) }] });
    await page.goto("/");
    await submitText(page, `https://evil.test/?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("reasons")).toContainText(XSS.script);
    await expect(page.getByTestId("reasons").locator("img, script, svg, a, [onerror], [onload]")).toHaveCount(0);
    await expect(page.getByTestId("tech-details")).not.toHaveAttribute("open", "");
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  });
});

test.describe("no warning signs found", () => {
  test("caution before the actions; slate-blue plate, no tick, no green", async ({ page, request }) => {
    await run(page, request, "nws");
    await expect(page.getByTestId("verdict-word")).toHaveText("لم نجد علامات تحذير");
    const order = await page.locator(".acts > .act").evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-testid")));
    expect(order.slice(0, 2)).toEqual(["caution", "act-now"]);
    const rgb = await page.getByTestId("verdict-plate").evaluate((el) => {
      const probe = document.createElement("span");
      probe.style.color = getComputedStyle(el).backgroundColor;
      document.body.append(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      return c;
    });
    const [r, g, b] = (rgb.match(/\d+/g) ?? []).map(Number) as [number, number, number];
    expect(b, `plate colour ${rgb}`).toBeGreaterThan(g); // blue family, never green
    expect(g > r + 20 && g > b).toBe(false);
    expect(await page.getByTestId("verdict-plate").locator("svg.icon path").count()).toBeGreaterThan(0);
    expect(await page.getByTestId("result").innerText()).not.toMatch(/✓|✔|\bsafe\b/i);
  });
});

test.describe("activity card badges follow the capability flags (default stack: bundled values)", () => {
  test("AI second look and the Sentinel line carry the flag's word", async ({ page, request }) => {
    await run(page, request, "nws");
    const t3 = page.getByTestId("act-step-T3").getByTestId("cap-badge");
    if (onDefaultStack("investigator")) await expect(t3).toHaveCount(0);
    else await expect(t3).toContainText(badgeWord(false, "ar"));
    await expect(page.getByTestId("act-sentinel").getByTestId("cap-badge")).toContainText(badgeWord(onDefaultStack("sentinel_agent"), "ar"));
  });
});

test.describe("activity card badges with every flag true", () => {
  test("T3 skipped reads 'Not needed' with no badge; the Sentinel line follows its flag", async ({ page, request, context, baseURL }) => {
    await forceCaps(context, baseURL!, "true");
    await setPrefs(context, baseURL!, { lang: "ar" });
    await run(page, request, "nws");
    await expect(page.getByTestId("act-step-T3")).toHaveAttribute("data-status", "skipped");
    await expect(page.getByTestId("act-step-T3")).toContainText("لم تكن لازمة");
    await expect(page.getByTestId("act-step-T3").getByTestId("cap-badge")).toHaveCount(0);
    await expect(page.getByTestId("act-sentinel").getByTestId("cap-badge")).toContainText(badgeWord(onAllOnStack("sentinel_agent"), "ar"));
  });
});

test.describe("reduced motion", () => {
  test("the hand-off dot does not animate", async ({ page, request }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await run(page, request, "danger");
    expect(await page.locator(".act-handoff").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
    await expect(page.getByTestId("verdict-word")).toBeVisible();
  });
});

for (const lang of ["ar", "en"] as const) {
  for (const theme of ["dark", "light"] as const) {
    test.describe(`axe on the result ${lang}/${theme}`, () => {
      test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang, theme }));
      for (const kind of ["danger", "nws"] as const) {
        test(`${kind}: 0 serious or critical, closed and open, no overflow`, async ({ page, request }) => {
          const id = newVerdictId();
          const t = token();
          const verdict = kind === "danger" ? withId(DEMO_DANGEROUS, id) : withId(DEMO_NWS, id);
          await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict }] });
          await page.goto("/");
          await submitText(page, `https://falcon-demo-bank.test/?c=${t}`);
          await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final");
          await page.evaluate(() => document.fonts.ready);
          await page.waitForTimeout(700); // the plate and reasons rise in; axe must measure the settled colours
          expect(await axe(page)).toEqual([]);
          await page.getByTestId("tech-summary").click();
          await page.waitForTimeout(400); // let the 160 ms fade-in finish: axe must measure the settled colours
          expect(await axe(page)).toEqual([]);
          expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
        });
      }
    });
  }
}

test.describe("degraded because the page could not be opened", () => {
  test("a plain 'treat it with caution' message, not an implied finding of risk", async ({ page, request, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    const id = newVerdictId();
    const t = token();
    const verdict = withId(DEMO_DANGEROUS, id, { verdict: "suspicious", risk_score: 50, impersonated_brand: null, degraded: true, degraded_reasons: ["not_rendered:dns_failure"], reasons: [], tier_reached: "T1" });
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict }] });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank.test/?c=${t}`);
    await expect(page.getByTestId("page-not-opened")).toContainText("No website answers at this address — treat it with caution");
    await expect(page.getByTestId("page-not-opened")).toContainText("Do not enter any details there. Open the organisation's official app or website yourself instead.");
    await expect(page.getByTestId("degraded")).toHaveCount(0);
  });
});

test.describe("the page-not-opened message never sits under a dangerous headline", () => {
  test("verdict dangerous + degraded for a not-rendered reason: no message", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    const verdict = withId(DEMO_DANGEROUS, id, { degraded: true, degraded_reasons: ["not_rendered:timeout"] });
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict }] });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("page-not-opened")).toHaveCount(0);
  });

  test("Arabic wording is exact for a suspicious, not-rendered verdict", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    const verdict = withId(DEMO_DANGEROUS, id, { verdict: "suspicious", risk_score: 50, impersonated_brand: null, degraded: true, degraded_reasons: ["not_rendered:timeout"], reasons: [], tier_reached: "T1" });
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict }] });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank.test/?c=${t}`);
    await expect(page.getByTestId("page-not-opened")).toContainText("لم نتمكن من فتح الصفحة نفسها، فلم نتحقق مما فيها. وهذا لا يعني أن الرابط موثوق؛ فلا تُدخل فيه أي بيانات، وافتح التطبيق أو الموقع الرسمي للجهة بنفسك.");
  });

  test("Arabic DNS wording is exact and only for a dns_failure reason", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    const verdict = withId(DEMO_DANGEROUS, id, { verdict: "suspicious", risk_score: 50, impersonated_brand: null, degraded: true, degraded_reasons: ["not_rendered:dns_failure"], reasons: [], tier_reached: "T1" });
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict }] });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank.test/?c=${t}`);
    await expect(page.getByTestId("page-not-opened")).toContainText("اسم هذا العنوان لا يقود إلى أي موقع حالياً، فلم نجد صفحة لنفتحها. قد يكون الرابط مكتوباً بشكل خاطئ أو أُغلق الموقع. لا تُدخل فيه أي بيانات، وافتح التطبيق أو الموقع الرسمي للجهة بنفسك.");
  });
});
