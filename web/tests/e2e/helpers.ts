import { randomBytes } from "node:crypto";
import { test as base, expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";
import type { Verdict } from "../../lib/contracts";
import type { StreamStep } from "../../lib/demo";

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const ulidLike = (prefix: string) => prefix + Array.from(randomBytes(26), (b) => CROCKFORD[b % 32]).join("");
/** Base URL of the second mock stack whose /v1/meta reports every capability flag true (see playwright.config.ts). */
export const ALL_ON_URL = `http://127.0.0.1:${process.env.ON_MOCK_PORT ?? 43112}`;
export const newVerdictId = () => ulidLike("vd_");
export const newIncidentId = () => ulidLike("inc_");
export const token = () => `t${randomBytes(6).toString("hex")}`;

export interface Scenario {
  match: string;
  verdictId?: string;
  status?: number;
  retryAfter?: number;
  steps?: StreamStep[];
  drop?: boolean;
  /** Answer the POST with 200 + the final Verdict (cache hit), as the real API does. */
  cached?: boolean;
  streamStatus?: number;
  statusVerdict?: Verdict | null;
}

export async function registerScenario(request: APIRequestContext, scenario: Scenario) {
  const response = await request.post("/__mock/scenario", { data: scenario });
  expect(response.ok()).toBe(true);
}

export async function scenarioLog(request: APIRequestContext, match: string): Promise<{ requests: { kind: string; contentType: string; forwardedFor: string | null }[]; streamOpens: number; statusCalls: number }> {
  return (await request.get(`/__mock/scenario?match=${encodeURIComponent(match)}`)).json();
}

export interface Boards {
  campaigns?: unknown[] | null;
  incidents?: unknown[] | null;
  campaignEvents?: unknown[];
  incidentEvents?: unknown[];
  requireKey?: string;
}

/** Registers board data for this browser context (selected by a cookie the mock reads). */
export async function useBoards(context: BrowserContext, request: APIRequestContext, baseURL: string, boards: Boards): Promise<string> {
  const key = token();
  expect((await request.post("/__mock/boards", { data: { key, ...boards } })).ok()).toBe(true);
  await context.addCookies([{ name: "mock_boards", value: key, url: baseURL }]);
  return key;
}

export async function setPrefs(context: BrowserContext, baseURL: string, prefs: { lang?: "ar" | "en"; theme?: "dark" | "light" }) {
  const cookies = [];
  if (prefs.lang) cookies.push({ name: "fl_lang", value: prefs.lang, url: baseURL });
  if (prefs.theme) cookies.push({ name: "fl_theme", value: prefs.theme, url: baseURL });
  await context.addCookies(cookies);
}

export async function submitText(page: Page, text: string) {
  await page.getByTestId("check-input").fill(text);
  await page.getByTestId("check-submit").click();
}

interface Guard {
  csp: string[];
  errors: string[];
  dialogs: string[];
}

/**
 * Every test runs with a guard: any CSP violation, uncaught page error or dialog
 * (alert/confirm/prompt, the classic XSS proof) fails the test.
 */
export const test = base.extend<{ guard: Guard }>({
  guard: [
    async ({ page }, use) => {
      const guard: Guard = { csp: [], errors: [], dialogs: [] };
      await page.addInitScript(() => {
        const w = window as unknown as { __csp: string[] };
        w.__csp = [];
        document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI} ${e.sourceFile ?? ""}:${e.lineNumber}`));
      });
      page.on("console", (message) => {
        const text = message.text();
        if (/content security policy|refused to (load|execute|apply|connect|frame)/i.test(text)) guard.csp.push(text);
      });
      page.on("pageerror", (error) => guard.errors.push(String(error)));
      page.on("dialog", (dialog) => {
        guard.dialogs.push(dialog.message());
        void dialog.dismiss();
      });
      await use(guard);
      const inPage = await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []).catch(() => [] as string[]);
      expect([...guard.csp, ...inPage], "CSP violations").toEqual([]);
      expect(guard.errors, "uncaught page errors").toEqual([]);
      expect(guard.dialogs, "dialogs opened").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
