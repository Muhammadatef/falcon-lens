import AxeBuilder from "@axe-core/playwright";
import { DEMO_DANGEROUS, DEMO_INCIDENT } from "../../lib/demo";
import { DEMO_TRACE } from "../../lib/demo-trace";
import { XSS } from "../fixtures";
import { expect, newIncidentId, newVerdictId, setPrefs, test, useBoards } from "./helpers";

const summary = (id: string, patch: Record<string, unknown> = {}) => ({
  verdict_id: id,
  created_at: "2026-11-24T10:00:00Z",
  input_type: "url",
  display: "hxxps://falcon-demo-bank-secure[.]test",
  verdict: "dangerous",
  risk_score: 97,
  degraded: false,
  degraded_reasons: [],
  tier_reached: "T2",
  model_route: "none",
  source: "live",
  agent: { tiers_run: ["T0", "T1", "T2"], extractor_ran: false, investigator_ran: false, tool_calls: 2, llm_calls: 0 },
  ...patch,
});
const incident = (id: string, patch: Record<string, unknown> = {}) => ({ ...DEMO_INCIDENT, incident_id: id, source: "live", ...patch });

test.describe("public history", () => {
  test("loads without any key; both tabs list rows, live rows appear, links navigate", async ({ page, context, request, baseURL }) => {
    const a = newVerdictId();
    const b = newVerdictId();
    const live = newVerdictId();
    const inc = newIncidentId();
    const liveInc = newIncidentId();
    const doc = { ...DEMO_DANGEROUS, verdict_id: a, source: "live" };
    await useBoards(context, request, baseURL!, {
      verdicts: [summary(a), summary(b, { verdict: "no_warning_signs", risk_score: 3, tier_reached: "T1", created_at: "2026-11-24T09:00:00Z", input_type: "message", display: null })],
      verdictEvents: [summary(live, { created_at: "2026-11-24T11:00:00Z", source: "replay" })],
      verdictDocs: { [a]: doc },
      incidents: [incident(inc)],
      incidentEvents: [incident(liveInc, { updated_at: "2099-01-01T00:00:00Z" })],
      traces: { [inc]: [{ incident_id: inc, thread_id: inc, runs: [DEMO_TRACE.runs[0]] }] },
    });
    await page.goto("/history");
    await expect(page.getByTestId("key-input")).toHaveCount(0);
    await expect(page.getByTestId("key-form")).toHaveCount(0);

    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.getByTestId("tab-checks")).toContainText("بصير، المحقّق — الفحوص");
    await expect(page.getByTestId("tab-incidents")).toContainText("درع، الحارس — الحوادث");
    await expect(page.getByTestId("check-row")).toHaveCount(2);
    // The live row streams in, newest first, and replay data is labelled.
    await expect(page.getByTestId("check-row")).toHaveCount(3);
    await expect(page.getByTestId("check-row").first()).toHaveAttribute("data-check-id", live);
    await expect(page.getByTestId("check-row").first().getByTestId("source-badge")).toBeVisible();
    await expect(page.getByTestId("history-live")).toContainText("مباشر");
    await expect(page.getByTestId("check-row").nth(2)).not.toContainText("falcon-demo-bank-secure"); // message: no raw text, no host
    expect(await page.locator("body").innerText()).not.toMatch(/آمن/);

    await page.locator(`[data-check-id="${a}"] [data-testid="check-link"]`).click();
    await expect(page).toHaveURL(new RegExp(`/checks/${a}$`));
    await expect(page.getByTestId("check-tier")).toHaveCount(4);
    await page.getByTestId("check-back").click();
    await expect(page).toHaveURL(/\/history$/);

    await page.getByTestId("tab-incidents").click();
    await expect(page.getByTestId("incident-row")).toHaveCount(1);
    await expect(page.getByTestId("incident-row")).toHaveCount(2); // streamed
    await page.locator(`[data-incident-id="${inc}"] [data-testid="incident-link"]`).click();
    await expect(page).toHaveURL(new RegExp(`/incidents/${inc}$`));
  });

  test("/ops incident cards link to the trace", async ({ page, context, request, baseURL }) => {
    const inc = newIncidentId();
    await useBoards(context, request, baseURL!, { incidents: [incident(inc)], traces: { [inc]: [{ incident_id: inc, thread_id: inc, runs: [DEMO_TRACE.runs[0]] }] } });
    await page.goto("/ops");
    await page.getByTestId("incident-title-link").click();
    await expect(page).toHaveURL(new RegExp(`/incidents/${inc}$`));
  });

  test("endpoint missing: honest 'not connected', no rows", async ({ page }) => {
    await page.goto("/history");
    await expect(page.getByTestId("history-not-connected")).toBeVisible();
    await expect(page.getByTestId("check-row")).toHaveCount(0);
  });

  test("?demo=1 labels synthetic rows; /checks/[id]?demo=1 renders", async ({ page }) => {
    await page.goto("/history?demo=1");
    await expect(page.getByTestId("demo-ribbon")).toContainText("DEMO DATA");
    await expect(page.getByTestId("check-row")).toHaveCount(2);
    await expect(page.getByTestId("source-badge").first()).toBeVisible();
    await page.getByTestId("check-link").first().click();
    await expect(page.getByTestId("check-tier")).toHaveCount(4);
  });
});

test.describe("check trace page", () => {
  test("renders tiers, skipped layer with reason, AI calls and verdict; hostile strings stay inert", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    const doc = {
      ...DEMO_DANGEROUS,
      verdict_id: id,
      source: "live",
      canonical_url: "hxxps://user:pw@falcon-demo-bank-secure[.]test/login?token=SECRET",
      reasons: [{ ar: XSS.img, en: XSS.img, evidence_ids: ["ev_brand0own1"] }],
      trace: [
        { step: 1, kind: "llm", name: "investigator.plan", summary: XSS.script, ms: 812 },
        { step: 2, kind: "tool", name: "whois", summary: XSS.svg, ms: 40 },
      ],
      evidence: DEMO_DANGEROUS.evidence.map((e, i) => (i === 1 ? { ...e, display: { ar: XSS.img, en: XSS.img } } : e)),
    };
    await useBoards(context, request, baseURL!, { verdicts: [], verdictDocs: { [id]: doc } });
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("check-tier")).toHaveCount(4);
    const states = await page.getByTestId("check-tier").evaluateAll((els) => els.map((e) => e.getAttribute("data-state")));
    expect(states).toEqual(["ran", "ran", "ran", "skipped"]); // tier_reached T2
    await expect(page.locator('[data-tier="T3"] [data-testid="check-tier-why"]')).toContainText("حُسم الحكم");
    await expect(page.getByTestId("check-host")).toHaveText("hxxps://falcon-demo-bank-secure[.]test");
    await expect(page.locator("body")).not.toContainText("SECRET");
    await expect(page.locator("body")).not.toContainText("pw@");
    await expect(page.getByTestId("check-ai-call")).toHaveCount(2);
    await expect(page.getByTestId("check-final")).toContainText("خطِر");
    await expect(page.locator("main img, main script, main svg[onload]")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
    expect(await page.locator("body").innerText()).not.toMatch(/آمن/);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("no model call: says so; unknown id and bad id", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    await useBoards(context, request, baseURL!, { verdicts: [], verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id, source: "live", trace: [] } } });
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("check-ai-none")).toBeVisible();
    await page.goto(`/checks/${newVerdictId()}`);
    await expect(page.getByTestId("check-not-found")).toBeVisible();
    expect((await page.goto("/checks/not-an-id"))?.status()).toBe(404);
  });

  test("no key prompt anywhere; the page never asks for one, /ops still does", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    await useBoards(context, request, baseURL!, { incidents: [], verdicts: [], verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id } } });
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("check-tier")).toHaveCount(4);
    await expect(page.getByTestId("key-input")).toHaveCount(0);
    await page.goto("/history");
    await expect(page.getByTestId("key-input")).toHaveCount(0);
    await page.goto("/ops");
    await expect(page.getByTestId("key-input")).toBeVisible();
  });
});

for (const lang of ["ar", "en"] as const) {
  test(`axe: no serious or critical violations on /history and /checks/[id] (${lang})`, async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    const inc = newIncidentId();
    await useBoards(context, request, baseURL!, {
      verdicts: [summary(id), summary(newVerdictId(), { verdict: "suspicious", degraded: true, degraded_reasons: ["sandbox_timeout"], source: "synthetic" })],
      verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id, source: "live", trace: [{ step: 1, kind: "llm", name: "investigator.plan", summary: "x", ms: 5 }] } },
      incidents: [incident(inc)],
    });
    await setPrefs(context, baseURL!, { lang });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const scan = async () => {
      await page.evaluate(() => document.fonts.ready);
      const found = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      return found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
    };
    await page.goto("/history");
    await expect(page.getByTestId("check-row")).toHaveCount(2);
    expect(await scan()).toEqual([]);
    await page.getByTestId("tab-incidents").click();
    await expect(page.getByTestId("incident-row")).toHaveCount(1);
    expect(await scan()).toEqual([]);
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("check-tier")).toHaveCount(4);
    expect(await scan()).toEqual([]);
  });
}

test.describe("evidence pack", () => {
  test("public visitors see only a note; a key already set on /ops reveals the download", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    await useBoards(context, request, baseURL!, { verdicts: [], verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id, source: "live", final: true } } });
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("evidence-pack-public")).toBeVisible();
    await expect(page.getByTestId("evidence-pack-download")).toHaveCount(0);
    await expect(page.getByTestId("evidence-pack-key")).toHaveCount(0);
    await expect(page.getByTestId("key-input")).toHaveCount(0);
    await page.evaluate(() => window.sessionStorage.setItem("fl_operator_key", "operator-test-key")); // what /ops does
    await page.reload();
    const button = page.getByTestId("evidence-pack-download");
    await expect(button).toContainText("Download evidence pack | تنزيل ملف الأدلة");
    const [download] = await Promise.all([page.waitForEvent("download"), button.click()]);
    expect(download.suggestedFilename()).toBe(`evidence-${id}.zip`);
  });
});
