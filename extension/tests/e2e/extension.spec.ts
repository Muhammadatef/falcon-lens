/**
 * Loads the unpacked e2e build (dist-e2e) in Chromium with a persistent context and drives it
 * against the mock API and the local fixture site. Nothing leaves 127.0.0.1.
 * FL_SHOTS=1 also writes the README screenshots to docs/screenshots/.
 */
import { test as base, chromium, expect, type BrowserContext, type Page } from "@playwright/test";
import type { Server } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { API_PORT, SITE_PORT, XSS_REASON, startApi, startSite, type ApiCall } from "./servers";

const here = dirname(fileURLToPath(import.meta.url));
const EXT = join(here, "..", "..", "dist-e2e");
const SHOTS = join(here, "..", "..", "docs", "screenshots");
const site = (host: string, path = "/"): string => `http://${host}:${SITE_PORT}${path}`;

const LOOKALIKE = site("falcon-demo-bank.secure-verify.test", "/login");
const DOWNGRADE = site("falcon-demo-bank.partner-portal.test", "/");
const UNREACHABLE = site("falcon-demo-bank.unreachable-host.test", "/");
const PENDING = site("falcon-demo-bank.pending-check.test", "/");
const PLAIN = site("heron-sample-shop.test", "/news");
const OFFICIAL = site("online.falcon-demo-bank.test", "/");

interface Fixtures {
  context: BrowserContext;
  extensionId: string;
  calls: ApiCall[];
  hits: string[];
}

const test = base.extend<Fixtures>({
  calls: async ({}, use) => {
    const calls: ApiCall[] = [];
    const api: Server = await startApi(calls);
    await use(calls);
    api.closeAllConnections();
    await new Promise((r) => api.close(r));
  },
  hits: async ({}, use) => {
    const hits: string[] = [];
    const srv: Server = await startSite(hits);
    await use(hits);
    srv.closeAllConnections();
    await new Promise((r) => srv.close(r));
  },
  context: async ({ calls, hits }, use) => {
    const context = await chromium.launchPersistentContext("", {
      channel: "chromium",
      viewport: { width: 390, height: 844 },
      args: [
        `--disable-extensions-except=${EXT}`,
        `--load-extension=${EXT}`,
        "--host-resolver-rules=MAP *.test 127.0.0.1",
      ],
    });
    // A freshly installed extension needs a moment before Chromium delivers webNavigation events
    // to its service worker. Probe until the guard answers, then start each test from a clean slate.
    let [sw] = context.serviceWorkers();
    sw ??= await context.waitForEvent("serviceworker");
    const probe = await context.newPage();
    await expect(async () => {
      await probe.goto(site("falcon-demo-bank.startup-probe.test")).catch(() => undefined);
      await expect(probe).toHaveURL(/^chrome-extension:\/\//, { timeout: 500 });
    }).toPass({ timeout: 15_000 });
    await expect(probe.locator("#status")).not.toHaveAttribute("data-state", "pending");
    await probe.close();
    await sw.evaluate(() => chrome.storage.session.clear());
    calls.length = 0;
    hits.length = 0;
    await use(context);
    await context.close();
  },
  extensionId: async ({ context }, use) => {
    let [sw] = context.serviceWorkers();
    sw ??= await context.waitForEvent("serviceworker");
    await use(sw.url().split("/")[2]!);
  },
});

const shot = async (page: Page, name: string): Promise<void> => {
  if (!process.env.FL_SHOTS) return;
  await page.waitForTimeout(900); // let the plate wash and row stagger finish
  await page.screenshot({ path: join(SHOTS, name) });
};

const checkCalls = (calls: ApiCall[]): ApiCall[] => calls.filter((c) => c.path.startsWith("/v1/check/url"));

test("lookalike navigation shows the warning before any input, then upgrades to dangerous", async ({ context, extensionId, calls }) => {
  const page = await context.newPage();
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  await page.goto(PLAIN);
  await expect(page.locator("#demo-input")).toBeVisible();

  const committed: string[] = [];
  page.on("framenavigated", (f) => f === page.mainFrame() && committed.push(f.url()));
  await page.goto(LOOKALIKE).catch(() => undefined); // the navigation is replaced by the warning page
  await expect(page).toHaveURL(new RegExp(`^chrome-extension://${extensionId}/warning\\.html`));
  expect(committed).not.toContain(LOOKALIKE); // the lookalike document never rendered in the tab

  // Before any input: the tab shows the extension page, and there is nothing to type into.
  await expect(page.locator("#go-back")).toBeVisible();
  await expect(page.locator("#go-back")).toBeFocused();
  expect(await page.locator("input, textarea, [contenteditable]").count()).toBe(0);
  expect(await page.locator("#demo-input").count()).toBe(0);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "ar");
  await expect(page.locator(".url")).toHaveText(`hxxp://falcon-demo-bank[.]secure-verify[.]test:${SITE_PORT}/login`);

  // Server confirmation upgrades the plate in place.
  await expect(page.locator("#plate")).toHaveAttribute("data-verdict", "dangerous");
  await expect(page.locator("#verdict-chip")).toHaveText("خطِر");
  await expect(page.locator("#status")).toHaveAttribute("data-state", "done");
  await expect(page.locator("#demo-badge")).toBeVisible(); // source=fixture is labelled, never shown as live
  await expect(page.locator("#local-reasons")).toContainText("بنك الصقر التجريبي");
  await expect(page.locator("#official")).toContainText("falcon-demo-bank.test");

  // XSS: the hostile reason is shown as text, creates no element and runs nothing.
  await expect(page.locator("#reasons")).toContainText(XSS_REASON);
  expect(await page.locator("#reasons img, #reasons script").count()).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  expect(dialogs).toEqual([]);
  await shot(page, "warning-dangerous-ar-390.png");

  // Privacy: one request, and its body is exactly the URL being checked.
  const sent = checkCalls(calls);
  expect(sent).toHaveLength(1);
  expect(sent[0]!.path).toBe("/v1/check/url?wait=6");
  expect(JSON.parse(sent[0]!.body)).toEqual({ url: LOOKALIKE });
  expect(sent[0]!.headers.cookie).toBeUndefined();
  expect(sent[0]!.headers.referer).toBeUndefined();
  expect(sent[0]!.headers["x-api-key"]).toBeUndefined();

  // English mirror.
  await page.locator("#lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.locator("#verdict-chip")).toHaveText("Dangerous");
  await expect(page.locator("#go-back")).toHaveText("Go back");
  expect(checkCalls(calls)).toHaveLength(1); // re-render does not re-send
  await shot(page, "warning-dangerous-en-390.png");

  // Go back returns to the page the person came from.
  await page.locator("#go-back").click();
  await expect(page).toHaveURL(PLAIN);
  await expect(page.locator("#demo-input")).toBeVisible();
});

test("continue anyway records the choice for the host and is not asked again", async ({ context, extensionId, calls }) => {
  const page = await context.newPage();
  await page.goto(LOOKALIKE).catch(() => undefined);
  await expect(page).toHaveURL(new RegExp(`^chrome-extension://${extensionId}/warning\\.html`));
  await expect(page.locator("#status")).toHaveAttribute("data-state", "done");
  await page.locator("#continue").click();
  await expect(page).toHaveURL(LOOKALIKE);
  await expect(page.locator("#fixture-label")).toContainText("TEST FIXTURE, not a real site");

  // Same host again: no second interruption. Verdict comes from the 10-minute cache.
  await page.goto(site("falcon-demo-bank.secure-verify.test", "/other"));
  await expect(page.locator("#fixture-label")).toBeVisible();
  expect(checkCalls(calls)).toHaveLength(1);

  // A different lookalike host still warns.
  await page.goto(DOWNGRADE).catch(() => undefined);
  await expect(page).toHaveURL(new RegExp(`^chrome-extension://${extensionId}/warning\\.html`));
});

test("a final 'no warning signs' downgrades the page and never says safe", async ({ context, extensionId }) => {
  const page = await context.newPage();
  await page.goto(DOWNGRADE).catch(() => undefined);
  await expect(page).toHaveURL(new RegExp(`^chrome-extension://${extensionId}/warning\\.html`));
  await expect(page.locator("#plate")).toHaveAttribute("data-verdict", "no_warning_signs");
  await expect(page.locator("#verdict-word")).toHaveText("لم نجد علامات تحذير");
  await expect(page.locator("#caution")).toBeVisible();
  await expect(page.locator("#go-back")).toBeVisible();
  await expect(page.locator("#reasons")).toContainText("بنك الصقر التجريبي"); // why we stopped is still explained
  for (const lang of ["ar", "en"]) {
    const text = await page.locator("body").innerText();
    expect(text, lang).not.toMatch(/\bsafe\b/i);
    expect(text, lang).not.toMatch(/آمن/);
    if (lang === "ar") {
      await shot(page, "warning-downgraded-ar-390.png");
      await page.locator("#lang-toggle").click();
      await expect(page.locator("#verdict-word")).toHaveText("No warning signs found");
    }
  }
});

test("without a server verdict the on-device warning stays", async ({ context, extensionId }) => {
  const page = await context.newPage();
  await page.goto(UNREACHABLE).catch(() => undefined);
  await expect(page).toHaveURL(new RegExp(`^chrome-extension://${extensionId}/warning\\.html`));
  await expect(page.locator("#status")).toHaveAttribute("data-state", "error");
  await expect(page.locator("#plate")).toHaveAttribute("data-verdict", "suspicious");
  await expect(page.locator("#verdict-chip")).toHaveText("مريب");
  await shot(page, "warning-local-only-ar-390.png");

  // A provisional "no warning signs" (job still running) must not downgrade anything.
  await page.goto(PENDING).catch(() => undefined);
  await expect(page.locator(".url")).toContainText("pending-check");
  await expect(page.locator("#status")).toHaveAttribute("data-state", "done");
  await expect(page.locator("#plate")).toHaveAttribute("data-verdict", "suspicious");
  await expect(page.locator("#status")).toContainText("أولية");
});

test("the warning does not depend on the risky host answering", async ({ context, extensionId, hits }) => {
  // .invalid never resolves: the check runs on the address, before any response.
  const page = await context.newPage();
  await page.goto("http://falcon-demo-bank.secure-verify.invalid/").catch(() => undefined);
  await expect(page).toHaveURL(new RegExp(`^chrome-extension://${extensionId}/warning\\.html`));
  await expect(page.locator("#go-back")).toBeVisible();
  expect(hits).toHaveLength(0);
});

test("ordinary and official addresses are not interrupted and nothing is sent", async ({ context, calls }) => {
  const page = await context.newPage();
  for (const url of [PLAIN, OFFICIAL]) {
    await page.goto(url);
    await expect(page.locator("#demo-input")).toBeVisible();
    expect(page.url()).toBe(url);
  }
  expect(calls).toHaveLength(0);
});

test("hover badge appears in a mock webmail page with a strict CSP", async ({ context, calls }) => {
  const page = await context.newPage();
  await page.setViewportSize({ width: 900, height: 600 });
  await page.goto(site("webmail.test", "/"));
  const badge = page.locator("falcon-lens-badge");

  await page.locator("#plain-link").hover();
  await page.waitForTimeout(150);
  expect(await badge.count()).toBe(0); // nothing before the 400 ms rest
  expect(calls).toHaveLength(0);

  await page.locator("#bad-link").hover();
  await expect(badge).toHaveAttribute("data-state", "done");
  await expect(badge).toHaveAttribute("data-verdict", "dangerous");
  const sent = checkCalls(calls);
  expect(sent).toHaveLength(1);
  expect(JSON.parse(sent[0]!.body)).toEqual({ url: LOOKALIKE });
  // The page cannot reach into the badge, and the badge cannot be clicked.
  expect(await page.evaluate(() => document.querySelector("falcon-lens-badge")!.shadowRoot)).toBeNull();
  await shot(page, "hover-badge-webmail-ar.png");

  await page.mouse.move(5, 5);
  await expect(badge).toHaveAttribute("data-state", "hidden");

  // Second rest on the same link: answered from the cache.
  await page.locator("#bad-link").hover();
  await expect(badge).toHaveAttribute("data-state", "done");
  expect(checkCalls(calls)).toHaveLength(1);

  // Server unreachable: the badge falls back to the on-device result and never claims a verdict.
  await page.locator("#offline-link").hover();
  await expect(badge).toHaveAttribute("data-verdict", "none");
  await expect(badge).toHaveAttribute("data-state", "done");

  // Keyboard focus works like hover.
  await page.locator("#plain-link").focus();
  await expect(badge).toHaveAttribute("data-verdict", "no_warning_signs");
});

test("the hover script is not injected outside the listed hosts", async ({ context }) => {
  const page = await context.newPage();
  await page.goto(PLAIN);
  await page.locator("#demo-input").hover();
  await page.waitForTimeout(700);
  expect(await page.locator("falcon-lens-badge").count()).toBe(0);
});

test("popup shows the verdict with reasons, Arabic first with an English switch", async ({ context, extensionId }) => {
  const page = await context.newPage();
  await page.setViewportSize({ width: 380, height: 600 });
  await page.goto(`chrome-extension://${extensionId}/popup.html?u=${encodeURIComponent(LOOKALIKE)}`);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("#plate")).toHaveAttribute("data-verdict", "dangerous");
  await expect(page.locator("#verdict-word")).toHaveText("خطِر");
  await expect(page.locator("#reasons .row")).toHaveCount(2);
  await expect(page.locator("#reasons")).toContainText(XSS_REASON);
  expect(await page.locator("#reasons img, #reasons script").count()).toBe(0);
  await expect(page.locator("#open-app")).toHaveAttribute("href", `http://127.0.0.1:${API_PORT}`);
  await expect(page.locator("#open-app")).toHaveAttribute("rel", /noopener/);
  await shot(page, "popup-dangerous-ar.png");

  await page.locator("#lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.locator("#verdict-word")).toHaveText("Dangerous");
  await shot(page, "popup-dangerous-en.png");

  // Official domain: stated as a fact about the list, with a caution, and the server's word.
  await page.goto(`chrome-extension://${extensionId}/popup.html?u=${encodeURIComponent(OFFICIAL)}`);
  await expect(page.locator("#official")).toContainText("Falcon Demo Bank");
  await expect(page.locator("#verdict-word")).toHaveText("No warning signs found");
  await expect(page.locator("#caution")).toBeVisible();
  expect(await page.locator("body").innerText()).not.toMatch(/\bsafe\b/i);
  await shot(page, "popup-no-warning-signs-en.png");

  // Pages that are not web pages cannot be checked.
  await page.goto(`chrome-extension://${extensionId}/popup.html?u=${encodeURIComponent("chrome://settings")}`);
  await expect(page.locator("#unsupported")).toBeVisible();
});

test("options: validates, saves, tests the connection and sends the API key only to the API", async ({ context, extensionId, calls }) => {
  const page = await context.newPage();
  await page.setViewportSize({ width: 720, height: 900 });
  await page.goto(`chrome-extension://${extensionId}/options.html`);
  await expect(page.locator("#opt-api")).toHaveValue(`http://127.0.0.1:${API_PORT}`);
  await shot(page, "options-ar.png");

  await page.locator("#opt-api").fill("http://plain-http-not-allowed.test");
  await page.locator("#save").click();
  await expect(page.locator("#notice")).toHaveAttribute("data-kind", "error");

  await page.locator("#opt-api").fill(`http://127.0.0.1:${API_PORT}/`);
  await page.locator("#opt-key").fill("fl_test_fixture_key");
  await page.locator("#save").click();
  await expect(page.locator("#notice")).toHaveAttribute("data-kind", "ok");

  await page.locator("#test").click();
  await expect(page.locator("#notice")).toHaveText("الخادم يستجيب.");
  expect(calls.at(-1)!.path).toBe("/v1/version");
  expect(calls.at(-1)!.headers["x-api-key"]).toBe("fl_test_fixture_key");

  // Turning server checks off keeps everything on the device.
  await page.locator("#opt-server").uncheck();
  await page.locator("#save").click();
  await expect(page.locator("#notice")).toHaveAttribute("data-kind", "ok");
  const before = calls.length;
  const tab = await context.newPage();
  await tab.goto(LOOKALIKE).catch(() => undefined);
  await expect(tab).toHaveURL(new RegExp(`^chrome-extension://${extensionId}/warning\\.html`));
  await expect(tab.locator("#status")).toHaveAttribute("data-state", "error");
  await expect(tab.locator("#plate")).toHaveAttribute("data-verdict", "suspicious");
  expect(calls.length).toBe(before);
});

test("extension pages carry a strict CSP and request minimal permissions", async ({ context, extensionId }) => {
  const page = await context.newPage();
  await page.goto(`chrome-extension://${extensionId}/options.html`);
  const manifest = await page.evaluate(() => chrome.runtime.getManifest());
  expect(manifest.permissions).toEqual(["webNavigation", "storage", "activeTab"]);
  expect(manifest.host_permissions).toEqual(["http://127.0.0.1/*"]);
  expect(manifest.web_accessible_resources).toBeUndefined();
  const csp = (manifest.content_security_policy as { extension_pages: string }).extension_pages;
  expect(csp).toContain("default-src 'none'");
  expect(csp).toContain("script-src 'self'");
  expect(csp).not.toMatch(/unsafe-inline|unsafe-eval|wasm-unsafe-eval/);
  // Inline script and remote script are both refused by the page's CSP.
  const ran = await page.evaluate(async () => {
    const s = document.createElement("script");
    s.textContent = "window.__inline = 1";
    document.head.append(s);
    await new Promise((r) => setTimeout(r, 50));
    return (window as unknown as { __inline?: number }).__inline;
  });
  expect(ran).toBeUndefined();
});
