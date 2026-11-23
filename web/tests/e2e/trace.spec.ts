import { DEMO_INCIDENT } from "../../lib/demo";
import { DEMO_TRACE } from "../../lib/demo-trace";
import { XSS } from "../fixtures";
import { expect, newIncidentId, setPrefs, test, useBoards } from "./helpers";

type Steps = Record<string, any>[]; // eslint-disable-line @typescript-eslint/no-explicit-any

const incident = (id: string, patch: Record<string, unknown> = {}) => ({ ...DEMO_INCIDENT, incident_id: id, source: "live", ...patch });
const traceOf = (id: string, mutate?: (steps: Steps) => void, runPatch: Record<string, unknown> = {}) => {
  const run = JSON.parse(JSON.stringify(DEMO_TRACE.runs[0]));
  mutate?.(run.steps);
  return { incident_id: id, thread_id: id, runs: [{ ...run, ...runPatch }] };
};

test.describe("incident agent trace page", () => {
  test("renders the six nodes, tool modes, model route, and the human-approval interrupt", async ({ page, context, request, baseURL }) => {
    const id = newIncidentId();
    const key = await useBoards(context, request, baseURL!, { incidents: [incident(id)], traces: { [id]: [traceOf(id)] }, requireKey: "op-test-key" });
    await page.goto("/ops");
    await page.getByTestId("key-input").fill("op-test-key");
    await page.getByTestId("key-input").press("Enter");
    await page.getByTestId("trace-link").click();
    await expect(page).toHaveURL(new RegExp(`/incidents/${id}$`));
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

    await expect(page.getByTestId("trace-incident")).toContainText("falcon-demo-bank-secure[.]test");
    await expect(page.getByTestId("trace-incident")).toContainText("vd_01KB0DEM0DATA0000000000001");
    await expect(page.getByTestId("trace-step")).toHaveCount(6);
    const nodes = await page.getByTestId("trace-step").evaluateAll((els) => els.map((e) => e.getAttribute("data-node")));
    expect(nodes).toEqual(["enrich", "compare", "assess", "summarise", "propose", "act"]);
    await expect(page.getByTestId("trace-tool").first()).toHaveAttribute("data-mode", "read");
    await expect(page.locator('[data-testid="trace-tool"][data-mode="external_draft"]')).toContainText("يحتاج موافقة بشرية");
    const routes = await page.getByTestId("llm-route").evaluateAll((els) => els.map((e) => e.getAttribute("data-route")));
    expect(routes).toEqual(["local", "none", "local"]); // summarise fell back to the template
    await expect(page.getByTestId("step-duration").first()).toContainText("212 ms");

    await expect(page.getByTestId("trace-interrupt")).toContainText("بانتظار قرار بشري");
    await page.getByTestId("approve").click();
    await expect
      .poll(async () => (await (await request.get(`/__mock/boards?key=${key}`)).json()).decisions)
      .toEqual([{ incident: id, action: "act_takedown_001", decision: "approve" }]);
    expect(page.url()).not.toContain("op-test-key");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("English, and the page follows the run live until it settles", async ({ page, context, request, baseURL }) => {
    const id = newIncidentId();
    const partial = traceOf(id, (s) => void s.splice(2), { status: "running", finished_at: null, interrupt: null });
    partial.runs[0].steps[1]!.status = "running";
    await useBoards(context, request, baseURL!, { incidents: [incident(id, { status: "triaging", actions: [] })], traces: { [id]: [partial, traceOf(id)] } });
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto(`/incidents/${id}`);
    await expect(page.getByTestId("trace-step")).toHaveCount(2);
    await expect(page.getByTestId("trace-live")).toContainText("Live");
    await expect(page.getByTestId("trace-step")).toHaveCount(6, { timeout: 12_000 });
    await expect(page.getByTestId("trace-interrupt")).toContainText("Waiting for a human");
    await expect(page.locator('[data-testid="trace-tool"][data-mode="external_draft"]')).toContainText("needs human approval");
    await expect(page.locator('[data-testid="trace-tool"][data-mode="internal_auto"]').first()).toContainText("automatic");
    await expect(page.getByTestId("llm-route").nth(1)).toContainText("template, no model");
  });

  test("hostile strings stay inert text and raise no CSP violation", async ({ page, context, request, baseURL }) => {
    const id = newIncidentId();
    const trace = traceOf(id, (s) => {
      s[0]!.summary_ar = XSS.img;
      s[0]!.summary_en = XSS.script;
      s[0]!.tools[0].name = XSS.svg;
      s[2]!.error_code = XSS.attr;
      s[3]!.llm.model = XSS.img;
    });
    const inc = incident(id, { summary: { ar: XSS.img, en: XSS.img }, indicators: [{ kind: "url", value_defanged: XSS.jsUrl, first_seen: "2026-11-22T10:02:00Z" }], linked_verdicts: [XSS.script] });
    await useBoards(context, request, baseURL!, { incidents: [inc], traces: { [id]: [trace] } });
    await page.goto(`/incidents/${id}`);
    await expect(page.getByTestId("trace-step")).toHaveCount(6);
    await expect(page.getByTestId("trace-timeline")).toContainText(XSS.img);
    await expect(page.locator("main img, main script, main svg[onload], main a:not([data-testid='trace-back'])")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  });

  test("a rule-based fallback draft is shown as its own labelled chip, with generated_by on LLM nodes", async ({ page, context, request, baseURL }) => {
    const id = newIncidentId();
    const trace = traceOf(id, (s) => {
      s[2]!.generated_by = "llm";
      s[3]!.generated_by = "template";
      s[4]!.generated_by = "rule";
      s[4]!.tools = [{ name: "draft_takedown", mode: "external_draft", status: "ok", evidence_ids: [], duration_ms: 0, origin: "rule_fallback" }];
    });
    await useBoards(context, request, baseURL!, { incidents: [incident(id)], traces: { [id]: [trace] } });
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto(`/incidents/${id}`);
    await expect(page.locator('[data-testid="trace-tool"][data-origin="rule_fallback"]')).toContainText("rule-based draft, needs human approval");
    const by = await page.getByTestId("step-generated").evaluateAll((els) => els.map((e) => e.getAttribute("data-by")));
    expect(by).toEqual(["llm", "template", "rule"]);
  });

  test("reduced motion switches the entrance animation off", async ({ page, context, request, baseURL }) => {
    const id = newIncidentId();
    await useBoards(context, request, baseURL!, { incidents: [incident(id)], traces: { [id]: [traceOf(id)] } });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(`/incidents/${id}`);
    await expect(page.getByTestId("trace-step")).toHaveCount(6);
    expect(await page.getByTestId("trace-step").first().evaluate((e) => getComputedStyle(e).animationName)).toBe("none");
  });

  test("a missing key shows the key prompt, an unknown incident shows not-found, a bad id is a 404 page", async ({ page, context, request, baseURL }) => {
    await useBoards(context, request, baseURL!, { incidents: [], requireKey: "k" });
    await page.goto(`/incidents/${newIncidentId()}`);
    await expect(page.getByTestId("trace-unauthorized")).toBeVisible();
    await useBoards(context, request, baseURL!, { incidents: [] });
    await page.goto(`/incidents/${newIncidentId()}`);
    await expect(page.getByTestId("trace-not-found")).toBeVisible();
    const bad = await page.goto("/incidents/not-an-id");
    expect(bad?.status()).toBe(404);
  });

  test("?demo=1 shows the synthetic trace under the DEMO DATA ribbon", async ({ page }) => {
    await page.goto(`/incidents/${DEMO_INCIDENT.incident_id}?demo=1`);
    await expect(page.getByTestId("demo-ribbon")).toBeVisible();
    await expect(page.getByTestId("trace-step")).toHaveCount(6);
    await page.getByTestId("approve").click();
    await expect(page.getByTestId("trace-notice")).toContainText("لم يُرسَل أي شيء");
  });
});
