import AxeBuilder from "@axe-core/playwright";
import { XSS } from "../fixtures";
import { expect, setPrefs, test, useBoards } from "./helpers";

const item = (n: string, patch: Record<string, unknown> = {}) => ({
  candidate_id: `hc_01JC8Z9Q3M5N7P2R4T6V8W0XY${n}`,
  domain_defanged: `falcon-demo-bank-${n.toLowerCase()}[.]test`,
  brand_id: "falcon_demo_bank",
  brand_name: { ar: "بنك الصقر التجريبي", en: "Falcon Demo Bank" },
  discovery: "ct",
  permutation_kind: null,
  reasons: ["brand_token_in_cert", "cert_fresh"],
  first_seen: "2026-11-24T20:00:00Z",
  verdict: "dangerous",
  incident_id: "inc_01JC8Z9Q3M5N7P2R4T6V8W0XYZ",
  found_before_report: true,
  time_to_detection_s: 120,
  time_to_detection_basis: "cert_not_before",
  source: "fixture",
  ...patch,
});

const META = {
  enabled: true,
  paused: false,
  interval_min: 15,
  last_cycle_at: "2026-11-24T20:10:00Z",
  sources: [
    { id: "permutation", kind: "permutation", status: "live", terms_url: null },
    { id: "ct_lookup", kind: "ct", status: "disabled", terms_url: "https://crt.sh/" },
    { id: "fixture", kind: "ct", status: "live", terms_url: null },
    { id: "search", kind: "search", status: "ready_needs_key", terms_url: null },
    { id: "ads", kind: "ads", status: "ready_needs_key", terms_url: null },
    { id: "maps", kind: "maps", status: "ready_needs_key", terms_url: null },
  ],
};

test.describe("hunting feed on /campaigns", () => {
  test("not connected: honest state, no data", async ({ page }) => {
    await page.goto("/campaigns");
    await expect(page.getByTestId("hunt-not-connected")).toBeVisible();
    await expect(page.getByTestId("hunt-item")).toHaveCount(0);
  });

  test("empty: written empty state and source chips", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { campaigns: [], hunt: { items: [], counts: {}, meta: META } });
    await page.goto("/campaigns");
    await expect(page.getByTestId("hunt-empty")).toBeVisible();
    await expect(page.getByTestId("hunt-source-maps")).toContainText("جاهز، يحتاج مفتاح API");
    await expect(page.getByTestId("hunt-source-search")).toContainText("جاهز، يحتاج مفتاح API");
    await expect(page.getByTestId("hunt-source-ads")).toContainText("جاهز، يحتاج مفتاح API");
  });

  test("confirmed rows: defanged plain text, badges, XSS inert, no link, unconfirmed as a count, axe clean", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, {
      campaigns: [],
      hunt: {
        items: [
          item("A"),
          item("B", { found_before_report: false, verdict: "suspicious", source: "live", time_to_detection_basis: null }),
          item("C", { reasons: [XSS.img] }), // off-contract: dropped
          item("D", { domain_defanged: `${XSS.script}[.]test` }), // off-contract: dropped
        ],
        counts: { confirmed: 2, new: 5, cleared: 1 },
        meta: META,
      },
    });
    await page.goto("/campaigns");
    await expect(page.getByTestId("hunt-item")).toHaveCount(2);
    const first = page.getByTestId("hunt-item").first();
    await expect(first.getByTestId("hunt-domain")).toHaveText("falcon-demo-bank-a[.]test");
    await expect(first.getByTestId("hunt-confirmed")).toContainText("أكّده بصير");
    await expect(first.getByTestId("hunt-before")).toHaveText("رُصد قبل أي بلاغ");
    await expect(first.getByTestId("source-badge")).toBeVisible(); // TEST FIXTURE label
    await expect(first.getByTestId("hunt-ttd")).toContainText("منذ إصدار الشهادة");
    const second = page.getByTestId("hunt-item").nth(1);
    await expect(second.getByTestId("hunt-before")).toHaveCount(0);
    await expect(second.getByTestId("hunt-ttd")).toHaveCount(0); // no basis, no number
    await expect(page.getByTestId("hunt-unconfirmed")).toContainText("6");
    await expect(page.locator("[data-testid=hunt-feed] a, [data-testid=hunt-feed] img, [data-testid=hunt-feed] script")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
    const raw = await (await page.request.get("/api/public/hunt")).text();
    for (const secret of ["SECRET-LIVE-NAME", "prescore", "test-read-key", "onerror"]) expect(raw).not.toContain(secret);
    const found = await new AxeBuilder({ page }).include("[data-testid=hunt-feed]").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(found.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  });

  test("English: same row, LTR", async ({ page, context, request, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await useBoards(context, request, baseURL!, { campaigns: [], hunt: { items: [item("A")], counts: { confirmed: 1 }, meta: META } });
    await page.goto("/campaigns");
    await expect(page.getByTestId("hunt-before")).toHaveText("Found before any report");
    await expect(page.getByTestId("hunt-confirmed")).toContainText("Confirmed by Baseer");
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  });
});

test.describe("hunting operator panel on /ops", () => {
  test("needs the operator key; pause and resume go through PUT /v1/admin/hunt", async ({ page, context, request, baseURL }) => {
    const key = await useBoards(context, request, baseURL!, {
      incidents: [],
      requireKey: "op-test-key",
      hunt: {
        items: [],
        counts: { new: 3, confirmed: 1 },
        meta: META,
        adminItems: [{ candidate_id: "hc_01JC8Z9Q3M5N7P2R4T6V8W0XYE", domain_defanged: "falcon-demo-bank-pay[.]test", brand_id: "falcon_demo_bank", status: "new", prescore: 45, verdict: null, first_seen: "2026-11-24T20:00:00Z", provenance: { source: "fixture" } }],
      },
    });
    await page.goto("/ops");
    await expect(page.getByTestId("hunt-ops-panel")).toHaveCount(0);
    await page.getByTestId("key-input").fill("op-test-key");
    await page.getByTestId("key-input").press("Enter");
    await expect(page.getByTestId("hunt-ops-panel")).toBeVisible();
    await expect(page.getByTestId("hunt-ops-state")).toContainText("مفعّل");
    await expect(page.getByTestId("hunt-ops-quota")).toContainText("20");
    await expect(page.getByTestId("hunt-ops-row")).toHaveCount(1);
    await expect(page.getByTestId("hunt-ops-counts")).toContainText("3");
    await page.getByTestId("hunt-ops-toggle").click();
    await expect(page.getByTestId("hunt-ops-state")).toContainText("موقوف مؤقتاً");
    await page.getByTestId("hunt-ops-toggle").click();
    await expect(page.getByTestId("hunt-ops-state")).not.toContainText("موقوف");
    const log = await (await request.get(`/__mock/boards?key=${key}`)).json();
    expect(log.huntPuts).toEqual([true, false]);
    await expect(page.locator("[data-testid=hunt-ops-panel] a")).toHaveCount(0);
  });
});
