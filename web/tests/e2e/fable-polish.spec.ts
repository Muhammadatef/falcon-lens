import AxeBuilder from "@axe-core/playwright";
import { DEMO_INCIDENT } from "../../lib/demo";
import { DEMO_TRACE } from "../../lib/demo-trace";
import { expect, newIncidentId, setPrefs, test, useBoards } from "./helpers";

/** Design audit of 24 Nov (reviews/AUDIT-DESIGN-20261124-1900.md): one test per fixed finding. */
test.describe("design polish (audit 24 Nov)", () => {
  for (const lang of ["ar", "en"] as const) {
    test(`/voice: the three how-to steps are numbered (${lang})`, async ({ page, context, baseURL }) => {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/voice");
      const list = page.locator(".voice-how ol");
      await expect(list.locator("li")).toHaveCount(3);
      expect(await list.evaluate((el) => getComputedStyle(el).listStyleType)).toBe("decimal");
      // The marker needs room inside the list box, or it is clipped at the page edge.
      expect(await list.evaluate((el) => parseFloat(getComputedStyle(el).paddingInlineStart))).toBeGreaterThanOrEqual(24);
    });

    test(`trace pages carry a title in the page language (${lang})`, async ({ page, context, request, baseURL }) => {
      await setPrefs(context, baseURL!, { lang });
      const id = newIncidentId();
      await useBoards(context, request, baseURL!, { incidents: [{ ...DEMO_INCIDENT, incident_id: id, source: "live" }], traces: { [id]: [{ incident_id: id, thread_id: id, runs: DEMO_TRACE.runs }] } });
      await page.goto(`/incidents/${id}`);
      await expect(page).toHaveTitle(lang === "ar" ? /^مسار عمل «درع»، الحارس · عدسة الصقر \| Falcon Lens$/ : /· Falcon Lens \| عدسة الصقر$/);
      await page.goto("/checks/vd_01KB0DEM0DATA0000000000001?demo=1");
      await expect(page).toHaveTitle(lang === "ar" ? "مسار الفحص · عدسة الصقر | Falcon Lens" : "Check trace · Falcon Lens | عدسة الصقر");
    });
  }

  test("incident trace in English on a phone: a long model-status pill wraps, the page never scrolls sideways", async ({ page, context, request, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.setViewportSize({ width: 390, height: 844 });
    const id = newIncidentId();
    const run = JSON.parse(JSON.stringify(DEMO_TRACE.runs[0]));
    // The live case: the model answered, the output was repaired once, then the template was used.
    for (const step of run.steps) if (step.llm) Object.assign(step.llm, { route: "cloud", repaired: true, fallback_template: true, tokens_in: 3756, tokens_out: 1305 });
    await useBoards(context, request, baseURL!, { incidents: [{ ...DEMO_INCIDENT, incident_id: id, source: "live" }], traces: { [id]: [{ incident_id: id, thread_id: id, runs: [run] }] } });
    await page.goto(`/incidents/${id}`);
    await expect(page.getByTestId("trace-step")).toHaveCount(6);
    await expect(page.locator(".trace-llm .pill--wait").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("/results and /docs/integration: no heading-order or duplicate-landmark finding", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "ar" });
    for (const path of ["/results", "/docs/integration"]) {
      await page.goto(path);
      const res = await new AxeBuilder({ page }).withRules(["heading-order", "landmark-unique", "scrollable-region-focusable"]).analyze();
      expect(res.violations.map((v) => `${path} ${v.id} ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
    }
  });

  test("reduced motion: no animation keeps running on the public pages", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "ar" });
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const path of ["/", "/voice", "/agents", "/docs", "/docs/agents", "/campaigns?demo=1", "/history?demo=1", "/results", "/incidents/inc_01KB0DEM0DATA0000000000002?demo=1"]) {
      await page.goto(path);
      await page.waitForTimeout(600);
      const running = await page.evaluate(() =>
        document.getAnimations().filter((a) => a.playState === "running" && (a.effect?.getTiming().iterations === Infinity || Number(a.effect?.getTiming().duration) > 1000)).map((a) => {
          const el = (a.effect as KeyframeEffect | null)?.target;
          return `${(a as CSSAnimation).animationName ?? "transition"} on ${el?.tagName}.${String(el?.className).slice(0, 40)}`;
        }),
      );
      expect(running, path).toEqual([]);
    }
  });

  for (const lang of ["ar", "en"] as const) {
    test(`three-layer architecture on /agents, /docs and /docs/agents: stacked, foldable, no axe finding (${lang})`, async ({ page, context, baseURL }) => {
      await setPrefs(context, baseURL!, { lang });
      for (const path of ["/agents", "/docs", "/docs/agents"]) {
        await page.goto(path);
        const layers = page.getByTestId("arch-layers");
        await expect(layers).toBeVisible();
        // Voice on top, the two agents in the middle, the platform at the bottom.
        const order = await layers.locator("details.al-layer").evaluateAll((els) => els.map((e) => [e.getAttribute("data-layer"), Math.round(e.getBoundingClientRect().top)] as const));
        expect(order.map((o) => o[0])).toEqual(["voice", "agents", "platform"]);
        expect(order[0]![1]).toBeLessThan(order[1]![1]);
        expect(order[1]![1]).toBeLessThan(order[2]![1]);
        await expect(layers.getByTestId("al-link")).toHaveCount(2);
        await expect(layers.getByTestId("al-group-baseer")).toContainText(lang === "ar" ? "«بصير»، المحقّق" : "Baseer, the Investigator");
        await expect(layers.getByTestId("al-group-dir")).toContainText(lang === "ar" ? "«درع»، الحارس" : "Dir', the Sentinel");
        expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), path).toBeLessThanOrEqual(0);
        const res = await new AxeBuilder({ page }).include('[data-testid="arch-layers"]').analyze();
        expect(res.violations.map((v) => `${path} ${v.id} ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
      }
      // A layer folds and opens with the keyboard (native details).
      const voice = page.getByTestId("al-layer-voice");
      await voice.locator("summary").focus();
      await page.keyboard.press("Enter");
      await expect(voice).not.toHaveAttribute("open", "");
      await expect(voice.getByTestId("al-step").first()).toBeHidden();
      await page.keyboard.press("Enter");
      await expect(voice.getByTestId("al-step")).toHaveCount(9);
    });

    test(`no rendered page shows an internal decision-record id or a raw repository path (${lang})`, async ({ page, context, baseURL }) => {
      await setPrefs(context, baseURL!, { lang });
      const paths = ["/", "/voice", "/agents", "/campaigns?demo=1", "/history?demo=1", "/results", "/authorities", "/privacy", "/ops", "/docs", "/docs/architecture", "/docs/agents", "/docs/cascade", "/docs/arbiter", "/docs/security", "/docs/evals", "/docs/integration", "/docs/privacy", "/checks/vd_01KB0DEM0DATA0000000000001?demo=1", "/incidents/inc_01KB0DEM0DATA0000000000002?demo=1"];
      for (const path of paths) {
        await page.goto(path);
        const text = await page.locator("body").innerText();
        expect(text.match(/ADR-\d{3}/g) ?? [], path).toEqual([]);
        expect(text.match(/(?:docs\/[A-Z_]+\.md|services\/[\w/.-]+\.py|packages\/falcon_core[\w/.-]*|contracts\/[\w.-]+\.(?:json|yaml))/g) ?? [], path).toEqual([]);
      }
    });
  }

  test("the interactive diagram panel links to the code on GitHub instead of listing file paths", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/docs/agents");
    await page.getByTestId("arch-layers").waitFor();
    await expect(page.locator(".agent-arch .chip.mono", { hasText: /ADR/ })).toHaveCount(0);
    await expect(page.locator("main")).toContainText("Alternatives we rejected");
  });
});
