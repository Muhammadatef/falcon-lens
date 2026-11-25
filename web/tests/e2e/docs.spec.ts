/**
 * /docs landing and the eight technical pages, the /authorities trim, and the privacy claims
 * (web/design/v2/IMPLEMENTATION_TASKS.md W2-07 and W2-09).
 */
import results from "../../lib/results.generated.json";
import { fmtThreshold } from "../../lib/docs-data";
import { badgeWord, onAllOnStack, onDefaultStack } from "./flags";
import { forceCaps, expect, setPrefs, test } from "./helpers";

const SLUGS = ["architecture", "agents", "cascade", "arbiter", "security", "evals", "integration", "privacy"] as const;
const ROUTES = ["/docs", ...SLUGS.map((s) => `/docs/${s}`), "/authorities", "/privacy"];

test.describe("docs landing", () => {
  test("eight cards, each links to a page that loads", async ({ page, request }) => {
    await page.goto("/docs");
    const cards = page.getByTestId("docs-cards").locator("li");
    await expect(cards).toHaveCount(8);
    const hrefs = await cards.locator("a.docs-read").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    expect(hrefs).toEqual(SLUGS.map((s) => `/docs/${s}`));
    for (const href of hrefs) expect((await request.get(href!)).status(), href!).toBe(200);
  });

  test("an unknown slug is a 404", async ({ page }) => {
    expect((await page.goto("/docs/not-a-page"))?.status()).toBe(404);
    expect((await page.goto("/docs/..%2F..%2Fetc"))?.status()).toBe(404);
  });

  test("the old agents URL redirects permanently to /docs/agents", async ({ request, page }) => {
    const res = await request.get("/architecture/agents", { maxRedirects: 0 });
    expect(res.status()).toBe(308);
    expect(res.headers()["location"]).toMatch(/\/docs\/agents$/);
    await page.goto("/architecture/agents");
    await expect(page).toHaveURL(/\/docs\/agents$/);
  });

  test("the current page is marked: side list on desktop, breadcrumb on a phone", async ({ page }) => {
    await page.goto("/docs/cascade");
    const side = page.getByTestId("docs-side");
    if (await side.isVisible()) {
      await expect(side.locator('a[aria-current="page"]')).toHaveAttribute("href", "/docs/cascade");
      await expect(side.locator("a")).toHaveCount(9);
    } else {
      await expect(page.locator(".docs-crumb [aria-current='page']")).toBeVisible();
      await expect(page.locator('.docs-crumb a[href="/docs"]')).toBeVisible();
    }
  });
});

test.describe("docs content restates the repo documents", () => {
  test("agents: Investigator state machine, Sentinel StateGraph with checkpointer and interrupt, images load with alt text", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/docs/agents");
    await expect(page.getByTestId("investigator")).toContainText("state machine");
    await expect(page.getByTestId("investigator")).toContainText("typed");
    await expect(page.getByTestId("sentinel")).toContainText("LangGraph StateGraph");
    await expect(page.getByTestId("sentinel")).toContainText("Postgres checkpointer");
    await expect(page.getByTestId("sentinel")).toContainText("interrupt()");
    for (const img of await page.locator(".figure img").all()) {
      await img.scrollIntoViewIfNeeded();
      await expect(img).toHaveAttribute("alt", /.{20,}/);
      await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
    }
    // The two agent figures are animated diagrams now (tests/e2e/arch-flow.spec.ts), not static images.
    expect(await page.locator(".figure img").count()).toBe(0);
    await expect(page.getByTestId("investigator").getByTestId("flow-baseer")).toBeVisible();
    await expect(page.getByTestId("sentinel").getByTestId("flow-dir")).toBeVisible();
  });

  test("architecture: the diagram loads from the site's own origin in both languages", async ({ page, context, baseURL }) => {
    for (const lang of ["ar", "en"] as const) {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/docs/architecture");
      const img = page.locator(".docs-figure img");
      await img.scrollIntoViewIfNeeded();
      expect((await img.getAttribute("alt"))!.length).toBeGreaterThan(30);
      expect(await img.getAttribute("src")).toBe("/images/architecture.svg");
      await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
    }
  });

  test("cascade: four tier cards (T0 to T3) moved here from Home", async ({ page }) => {
    await page.goto("/docs/cascade");
    await expect(page.getByTestId("tier-cards").locator(".how-card")).toHaveCount(4);
    for (const tag of ["T0", "T1", "T2", "T3"]) await expect(page.getByTestId("tier-cards")).toContainText(tag);
  });

  test("arbiter: thresholds are the bundled artifact's values, nothing typed", async ({ page }) => {
    await page.goto("/docs/arbiter");
    const file = results as unknown as { available?: boolean; data?: { thresholds?: Record<string, number> } };
    if (!file.available) return void (await expect(page.getByTestId("thresholds-pending")).toBeVisible());
    const t = file.data!.thresholds!;
    const box = page.getByTestId("thresholds");
    await expect(box).toContainText(fmtThreshold(t.tau_low!));
    await expect(box).toContainText(fmtThreshold(t.tau_high!));
    for (const h of ["H1", "H2", "H3", "H4", "H5", "H6"]) await expect(page.locator("main")).toContainText(h);
  });

  test("evals: provenance shows the artifact name", async ({ page }) => {
    await page.goto("/docs/evals");
    const file = results as unknown as { available?: boolean; artifact?: string };
    if (!file.available) return void (await expect(page.getByTestId("provenance-pending")).toBeVisible());
    await expect(page.getByTestId("provenance")).toContainText(file.artifact!);
  });

  test("every doc page cites its source documents in the repository", async ({ page }) => {
    for (const slug of SLUGS.filter((s) => s !== "agents")) {
      await page.goto(`/docs/${slug}`);
      const links = page.getByTestId("doc-sources").locator("a");
      expect(await links.count(), slug).toBeGreaterThan(0);
      for (const a of await links.all()) {
        await expect(a).toHaveAttribute("href", /^https:\/\/github\.com\/[^/]+\/falcon-lens\/blob\/main\/docs\/|contracts\//);
        await expect(a).toHaveAttribute("rel", "noopener noreferrer");
      }
    }
  });

  test("integration: still says ready to connect, not connected, and no endorsement", async ({ page, context, baseURL }) => {
    for (const lang of ["en", "ar"] as const) {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/docs/integration");
      await expect(page.getByTestId("not-connected-doc")).toContainText(lang === "en" ? "Ready to connect. Not connected." : "جاهز للربط، وغير مربوط");
      await expect(page.locator("main")).toContainText(lang === "en" ? "no existing integration" : "أي ربط قائم");
      await expect(page.locator("main")).not.toContainText(/is endorsed|يحمل تأييداً/);
    }
  });
});

test.describe("capability badges on docs follow the flags (default stack: bundled values)", () => {
  test("integration surfaces, the security card and T3 carry the flag's word", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/docs/integration");
    const rows = page.locator(".tbl tbody tr");
    for (const [i, id] of ["rest_api", "mcp", "stix"].entries()) await expect(rows.nth(i).getByTestId("cap-badge")).toContainText(badgeWord(onDefaultStack(id), "en"));
    await expect(rows.nth(3).getByTestId("cap-badge")).toHaveCount(0);
    await expect(page.locator("#mcp").getByTestId("cap-badge")).toContainText(badgeWord(onDefaultStack("mcp"), "en"));
    await page.goto("/docs");
    await expect(page.getByTestId("docs-cards").locator("li").nth(4).getByTestId("cap-badge")).toContainText(badgeWord(onDefaultStack("injection_defence"), "en"));
    await page.goto("/docs/cascade");
    await expect(page.getByTestId("tier-cards").locator(".how-card").nth(3).getByTestId("cap-badge")).toContainText(badgeWord(onDefaultStack("investigator"), "en"));
  });
});

test.describe("capability badges on docs with every flag true", () => {
  test("security card, T3 and the surfaces read Live (surfaces once the flags are listed in lib/capabilities.ts)", async ({ page, context, baseURL }) => {
    await forceCaps(context, baseURL!, "true");
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/docs");
    await expect(page.getByTestId("docs-cards").locator("li").nth(4).getByTestId("cap-badge")).toContainText("Live");
    await page.goto("/docs/cascade");
    await expect(page.getByTestId("tier-cards").locator(".how-card").nth(3).getByTestId("cap-badge")).toContainText("Live");
    await page.goto("/docs/integration");
    const rows = page.locator(".tbl tbody tr");
    for (const [i, id] of ["rest_api", "mcp", "stix"].entries()) await expect(rows.nth(i).getByTestId("cap-badge")).toContainText(badgeWord(onAllOnStack(id), "en"));
  });

  test("authorities interface flags follow the flags", async ({ page, context, baseURL }) => {
    await forceCaps(context, baseURL!, "true");
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/authorities");
    const badges = page.getByTestId("ifaces").getByTestId("cap-badge");
    await expect(badges).toHaveCount(3);
    for (const [i, id] of ["rest_api", "mcp", "stix"].entries()) await expect(badges.nth(i)).toContainText(badgeWord(onAllOnStack(id), "en"));
  });
});

test.describe("authorities trim", () => {
  test("the status callout is the first thing after the H1; three outcomes; no crest or logo", async ({ page, context, baseURL }) => {
    for (const lang of ["en", "ar"] as const) {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/authorities");
      expect(await page.locator("main h1 + *").getAttribute("data-testid")).toBe("not-connected");
      await expect(page.getByTestId("not-connected")).toContainText(lang === "en" ? "no existing integration" : "لا يوجد أي ربط قائم");
      await expect(page.getByTestId("not-connected")).toContainText(lang === "en" ? "no endorsement" : "تأييد");
      await expect(page.getByTestId("outcomes").locator("li")).toHaveCount(3);
      await expect(page.locator("main img, main picture, main svg[role='img']")).toHaveCount(0);
      await expect(page.locator("main table")).toHaveCount(0);
      await expect(page.locator('main a[href="/docs/integration"]')).toHaveCount(1);
    }
  });

  test("interface badges follow the bundled flags", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/authorities");
    const badges = page.getByTestId("ifaces").getByTestId("cap-badge");
    for (const [i, id] of ["rest_api", "mcp", "stix"].entries()) await expect(badges.nth(i)).toContainText(badgeWord(onDefaultStack(id), "en"));
  });
});

test.describe("privacy claims match docs/PRIVACY.md", () => {
  test("stores hash and defanged link, redacts before cloud, sovereign mode, retention not automated", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/privacy");
    const text = await page.locator("main").innerText();
    for (const claim of ["SHA-256", "defanged copy", "Emirates ID", "IBANs", "Sovereign mode", "not yet automated", "never ask you for personal, banking or ID details"]) expect(text, claim).toContain(claim);
    expect(text).not.toMatch(/injection-guarded|compliance with GDPR|\bsafe\b/i);
  });
});

test.describe("every v2 route: never 'safe', no third-party requests, no inline style attributes in server HTML", () => {
  for (const lang of ["ar", "en"] as const) {
    test(`forbidden words and origins (${lang})`, async ({ page, context, baseURL, request }) => {
      await setPrefs(context, baseURL!, { lang });
      for (const route of ROUTES) {
        await page.goto(route);
        const text = await page.locator("body").innerText();
        expect(text, route).not.toMatch(/\bsafe(ly|r|st)?\b/i);
        expect(text, route).not.toContain("آمن");
        const external = await page.evaluate(() => performance.getEntriesByType("resource").map((r) => r.name).filter((n) => !n.startsWith(location.origin)));
        expect(external, route).toEqual([]);
        const html = await (await request.get(route, { headers: { cookie: `fl_lang=${lang}` } })).text();
        expect(html, route).not.toMatch(/<[a-z][^>]*\sstyle="/i);
      }
    });
  }
});

test.describe("docs keyboard and reduced motion", () => {
  test("landing cards are reachable by keyboard and the page is static under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/docs");
    await page.locator("a.docs-read").first().focus();
    await expect(page.locator("a.docs-read").first()).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/docs\/architecture$/);
    await expect(page.locator("main h1")).toBeVisible();
  });
});
