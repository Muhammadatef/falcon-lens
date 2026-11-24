import AxeBuilder from "@axe-core/playwright";
import { DEMO_DANGEROUS, DEMO_INCIDENT } from "../../lib/demo";
import { DEMO_TRACE } from "../../lib/demo-trace";
import { expect, newIncidentId, newVerdictId, setPrefs, test, useBoards } from "./helpers";

const PHONE = "+971 50 123 4567";
const EMAIL = "victim.name@example-mail.com";
const URL_PII = "https://login.evil-example.com/verify/path?email=victim.name@example-mail.com&phone=0501234567&token=SECRET123";
const MESSAGE = `Call ${PHONE}, write ${EMAIL} or open ${URL_PII}`;
const LEAKS = [PHONE, "123 4567", "0501234567", EMAIL, "victim.name", "example-mail", "SECRET123", "/verify/path", "token=", "abuse@registrar-example.com", "DRAFT-BODY", "operator-ali", "SECRET-HEADER"];

const expectNoLeak = (text: string) => {
  for (const leak of LEAKS) expect(text, `leaked: ${leak}`).not.toContain(leak);
};

test.describe("public history is read only and leaks nothing", () => {
  test("check pages and lists carry no raw input, phone, email or URL query", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    const doc = {
      ...DEMO_DANGEROUS,
      verdict_id: id,
      input_type: "message",
      source: "live",
      input_text: MESSAGE,
      canonical_url: URL_PII,
      email_headers: { from: EMAIL, "x-secret": "SECRET-HEADER" },
      reasons: [{ ar: `اتصل ${PHONE}`, en: `Call ${PHONE} or visit ${URL_PII}`, evidence_ids: ["ev_brand0own1"] }],
      evidence: DEMO_DANGEROUS.evidence.map((e, i) => (i === 1 ? { ...e, observed: MESSAGE, display: { ar: `الرسالة ${EMAIL}`, en: `Mentions ${URL_PII}` } } : e)),
      trace: [{ step: 1, kind: "tool", name: "whois_lookup", summary: MESSAGE, ms: 40 }],
    };
    const row = { verdict_id: id, created_at: "2026-11-24T10:00:00Z", input_type: "message", display: URL_PII, input_text: MESSAGE, verdict: "dangerous", risk_score: 90, degraded: false, degraded_reasons: [], tier_reached: "T2", model_route: "none", source: "live", agent: { tiers_run: ["T0", "T1", "T2"], extractor_ran: false, investigator_ran: false, tool_calls: 1, llm_calls: 0 } };
    await useBoards(context, request, baseURL!, { verdicts: [row], verdictDocs: { [id]: doc }, verdictEvents: [{ ...row, verdict_id: newVerdictId() }] });

    const list = await page.request.get("/api/public/checks");
    expect(list.status()).toBe(200);
    expect(list.headers()["cache-control"]).toContain("no-store");
    expectNoLeak(await list.text());
    const one = await page.request.get(`/api/public/checks/${id}`);
    expect(one.status()).toBe(200);
    const body = await one.text();
    expectNoLeak(body);
    expect(body).not.toContain("input_text");

    await page.goto("/history");
    await expect(page.getByTestId("check-row")).toHaveCount(2);
    expectNoLeak(await page.content());
    await page.goto(`/checks/${id}`);
    await expect(page.getByTestId("check-tier")).toHaveCount(4);
    expectNoLeak(await page.content());
    const text = await page.locator("body").innerText();
    expect(text).not.toMatch(/آمن/);
    expect(text).not.toMatch(/\bsafe\b/i);
  });

  test("incident pages carry no draft bodies, recipients or approvers, and offer no decision", async ({ page, context, request, baseURL }) => {
    const id = newIncidentId();
    const inc = {
      ...DEMO_INCIDENT,
      incident_id: id,
      source: "live",
      actions: [
        { action_id: "act_takedown_001", tool: "draft_takedown", mode: "external_draft", status: "awaiting_approval", draft: { recipient_kind: "registrar", subject: "Takedown", body_en: "DRAFT-BODY abuse@registrar-example.com", body_ar: "DRAFT-BODY" }, evidence_ids: [], approved_by: "operator-ali" },
      ],
      timeline: [{ at: "2026-11-24T10:00:00Z", what: `note ${EMAIL} ${PHONE}` }],
      correlation_keys: { phone: PHONE },
    };
    const trace = JSON.parse(JSON.stringify({ incident_id: id, thread_id: id, runs: [DEMO_TRACE.runs[0]] }));
    trace.runs[0].interrupt = { ...trace.runs[0].interrupt, decision: "approved", decided_by: "operator-ali" };
    await useBoards(context, request, baseURL!, { incidents: [inc], traces: { [id]: [trace] } });

    const list = await page.request.get("/api/public/incidents");
    expect(list.status()).toBe(200);
    expectNoLeak(await list.text());
    const one = await page.request.get(`/api/public/incidents/${id}`);
    expect(one.status()).toBe(200);
    const raw = await one.text();
    expectNoLeak(raw);
    expect(raw).toContain("draft_takedown"); // the action TYPE is public
    // No write verb exists on the public surface.
    for (const method of ["post", "put", "delete"] as const) {
      const res = await page.request[method](`/api/public/incidents/${id}`);
      expect([404, 405]).toContain(res.status());
    }
    expect((await page.request.post(`/api/public/incidents/${id}/actions/act_takedown_001/approve`)).status()).toBe(404);

    await page.goto(`/incidents/${id}`);
    await expect(page.getByTestId("trace-step")).toHaveCount(6);
    await expect(page.getByTestId("approve")).toHaveCount(0);
    await expect(page.getByTestId("key-input")).toHaveCount(0);
    expectNoLeak(await page.content());
  });

  test("History is in the header nav, /ops stays key protected and is labelled Operator actions", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { incidents: [], requireKey: "op-test-key", verdicts: [] });
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/history");
    await expect(page.locator('header nav a[href="/history"]').first()).toContainText("History");
    await expect(page.getByTestId("key-input")).toHaveCount(0);
    await page.goto("/ops");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Operator actions");
    await expect(page.getByTestId("key-input")).toBeVisible();
    await expect(page.getByTestId("ops-unauthorized")).toBeVisible();
    await setPrefs(context, baseURL!, { lang: "ar" });
    await page.goto("/history");
    await expect(page.locator('header nav a[href="/history"]').first()).toContainText("السجل");
  });

  test("CSP is intact and axe finds nothing serious on the public pages (ar, phone width)", async ({ page, context, request, baseURL }) => {
    const id = newVerdictId();
    const inc = newIncidentId();
    await useBoards(context, request, baseURL!, {
      verdicts: [],
      verdictDocs: { [id]: { ...DEMO_DANGEROUS, verdict_id: id, source: "live" } },
      incidents: [{ ...DEMO_INCIDENT, incident_id: inc, source: "live" }],
      traces: { [inc]: [{ incident_id: inc, thread_id: inc, runs: [DEMO_TRACE.runs[0]] }] },
    });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const violations: string[] = [];
    page.on("console", (m) => {
      if (/content security policy/i.test(m.text())) violations.push(m.text());
    });
    page.on("pageerror", (e) => violations.push(e.message));
    for (const path of ["/history", `/checks/${id}`, `/incidents/${inc}`]) {
      const response = await page.goto(path);
      const csp = response?.headers()["content-security-policy"] ?? "";
      expect(csp).toContain("default-src 'self'");
      expect(csp).not.toContain("unsafe-eval");
      await expect(page.locator("main")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      const found = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      expect(found.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
    }
    expect(violations).toEqual([]);
  });
  for (const lang of ["ar", "en"] as const) {
    test(`incident titles are structured, ids sit behind technical detail, queued state is honest (${lang})`, async ({ page, context, request, baseURL }) => {
      const id = newIncidentId();
      const queued = newIncidentId();
      const hostile = { ar: "اتصل 0501234567 evil.test/x?t=1", en: "Call 0501234567 https://evil.test/x?t=1" };
      await useBoards(context, request, baseURL!, {
        incidents: [
          { ...DEMO_INCIDENT, incident_id: id, source: "live", summary: hostile, severity_reason: hostile },
          { ...DEMO_INCIDENT, incident_id: queued, source: "live", status: "open", summary: hostile, severity_reason: hostile, updated_at: "2026-11-24T09:00:00Z" },
        ],
        traces: { [id]: [{ incident_id: id, thread_id: id, runs: [DEMO_TRACE.runs[0]] }], [queued]: [{ incident_id: queued, thread_id: queued, runs: [] }] },
      });
      await setPrefs(context, baseURL!, { lang });
      const title = lang === "ar" ? "حملة احتيال تنتحل بنك الصقر التجريبي" : "Suspected scam campaign impersonating Falcon Demo Bank";
      await page.goto("/history?tab=incidents");
      const rows = page.getByTestId("incident-row");
      await expect(rows).toHaveCount(2);
      for (const row of await rows.all()) await expect(row).toContainText(title);
      let body = await page.locator("main").innerText();
      expect(body).not.toMatch(/text removed|أُزيل النص|0501234567|x\?t=1/);
      expect(body).not.toContain(id);

      await page.goto(`/incidents/${id}`);
      await expect(page.getByTestId("trace-incident-title")).toHaveText(title);
      body = await page.locator("main").innerText();
      expect(body).not.toMatch(/text removed|أُزيل النص|0501234567|x\?t=1/);
      expect(body).not.toContain(id);
      expect(body).not.toContain("vd_");
      const details = page.getByTestId("trace-technical");
      await expect(details).not.toHaveAttribute("open", "");
      await details.locator("summary").click();
      await expect(page.getByTestId("trace-verdicts")).toBeVisible();

      await page.goto(`/incidents/${queued}`);
      await expect(page.getByTestId("trace-empty")).toHaveAttribute("data-state", "tr.queued");
      expect(await page.locator("main").innerText()).not.toMatch(/has not started|لم يبدأ/);
    });
  }

});
