/**
 * Mobile readiness (owner P0): every public page on a real phone profile (iPhone 15 on WebKit, Pixel 7 on Chromium),
 * both languages and themes: no horizontal scroll, no console errors, primary controls at least 44 px, wide content
 * (tables, code, SVG) scrolling inside its own box, a working menu, axe clean. Screenshots go to test-results.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, setPrefs, test } from "./helpers";

const PATHS = ["/", "/voice", "/agents", "/campaigns", "/history?demo=1", "/checks/vd_01KB0DEM0DATA0000000000001?demo=1", "/results", "/authorities", "/privacy", "/docs", "/docs/agents", "/docs/cascade", "/docs/architecture", "/ops"];
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const IGNORED_CONSOLE = /Failed to load resource|favicon|net::ERR|the server responded with a status of (401|403|404|502|503)/i;

async function scan(page: Page) {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const visible = (el: Element) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
    };
    /** True when an ancestor (below body) clips or scrolls horizontally, so the wide child is contained. */
    const contained = (el: Element) => {
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const o = getComputedStyle(p).overflowX;
        if (o === "auto" || o === "scroll" || o === "hidden" || o === "clip") return true;
      }
      return false;
    };
    const wide: string[] = [];
    for (const el of document.querySelectorAll("body *")) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if ((r.right > vw + 1 || r.left < -1) && !contained(el) && !el.closest("[aria-hidden='true'], svg")) wide.push(`${el.tagName.toLowerCase()}.${String((el as HTMLElement).className).slice(0, 40)} "${(el.textContent ?? "").trim().slice(0, 40)}" ${Math.round(r.left)}..${Math.round(r.right)}`);
    }
    const small: string[] = [];
    for (const el of document.querySelectorAll("header button, header a, .btn, button[type=submit], main button, nav a")) {
      if (!visible(el) || el.closest("[aria-hidden='true']")) continue;
      const r = el.getBoundingClientRect();
      if (r.height < 43.5 || r.width < 43.5) small.push(`${el.tagName.toLowerCase()}.${String((el as HTMLElement).className).slice(0, 30)}[${(el.textContent ?? "").trim().slice(0, 20) || el.getAttribute("aria-label")}] ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
    const clipped: string[] = [];
    for (const el of document.querySelectorAll("h1, h2, h3, p, li, button, a, label")) {
      if (!visible(el) || (el as HTMLElement).clientWidth <= 2) continue; // 1 px boxes are the screen-reader-only live regions
      const s = getComputedStyle(el);
      if ((s.overflow === "hidden" || s.textOverflow === "ellipsis") && el.scrollWidth > el.clientWidth + 1 && s.whiteSpace !== "normal" && s.display !== "inline") clipped.push(`${el.tagName.toLowerCase()}:${(el.textContent ?? "").trim().slice(0, 30)}`);
    }
    const doc = document.scrollingElement!;
    return { overflow: doc.scrollWidth - window.innerWidth, wide: wide.slice(0, 8), small: [...new Set(small)].slice(0, 12), clipped: clipped.slice(0, 8) };
  });
}

for (const lang of ["ar", "en"] as const) {
  for (const theme of ["dark", "light"] as const) {
    test.describe(`mobile ${lang}/${theme}`, () => {
      test.beforeEach(async ({ context, baseURL }) => setPrefs(context, baseURL!, { lang, theme }));
      for (const path of PATHS) {
        test(`${path}`, async ({ page, guard }, info) => {
          const errors: string[] = [];
          page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
          page.on("console", (m) => {
            if (m.type() === "error" && !IGNORED_CONSOLE.test(m.text())) errors.push(m.text());
          });
          await page.goto(path);
          await page.evaluate(() => document.fonts.ready);
          await page.waitForTimeout(1200); // let the entrance animations finish before measuring contrast
          const r = await scan(page);
          expect(r.overflow, "horizontal scroll").toBeLessThanOrEqual(1);
          expect(r.wide, "elements past the viewport edge").toEqual([]);
          expect(r.small, "tap targets under 44 px").toEqual([]);
          expect(r.clipped, "clipped text").toEqual([]);
          const serious = (await new AxeBuilder({ page }).withTags(WCAG).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
          expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
          expect(errors).toEqual([]);
          if (lang === "ar" && theme === "dark") {
            // Last step: WebKit's screenshot code adds an inline <style>, which is Playwright's, not the page's, so it is not a CSP finding.
            const before = guard.csp.length;
            const beforeInPage = await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp.length);
            await page.screenshot({ path: `test-results-mobile/${info.project.name}-${path.replace(/[^a-z0-9]+/gi, "_")}.png`, fullPage: true, caret: "initial", animations: "allow" });
            await page.waitForTimeout(600);
            guard.csp.length = before;
            await page.evaluate((n) => ((window as unknown as { __csp: string[] }).__csp.length = n), beforeInPage);
          }
        });
      }
    });
  }
}

test.describe("mobile chrome", () => {
  test("menu opens and closes, language and theme toggles are reachable", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "ar", theme: "dark" });
    await page.goto("/");
    const menu = page.getByTestId("menu-toggle");
    await expect(menu).toBeVisible();
    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator("#site-nav")).toBeVisible();
    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await page.getByTestId("lang-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    // On a phone the theme switch lives inside the menu.
    await menu.click();
    await page.getByTestId("theme-toggle-menu").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });

  test("the check box and button are reachable on the first screen", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en", theme: "dark" });
    await page.goto("/");
    const input = page.locator("main textarea, main input[type=text], main input[type=url]").first();
    await expect(input).toBeVisible();
    const box = await input.boundingBox();
    expect(box!.y + box!.height).toBeLessThan(page.viewportSize()!.height);
    await input.fill("hello");
    const btn = page.locator("main button[type=submit], main .btn--primary").first();
    await expect(btn).toBeVisible();
    await btn.scrollIntoViewIfNeeded();
    expect((await btn.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  });
});
