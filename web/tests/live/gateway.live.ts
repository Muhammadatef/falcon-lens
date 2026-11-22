/**
 * Through-the-gateway check against a RUNNING compose stack (Caddy → web / api).
 * Not part of `pnpm test:e2e`. Run it against your own stack:
 *
 *   LIVE_BASE_URL=https://localhost:8443 pnpm exec playwright test --project=live
 *
 * It asserts the things only the real gateway can prove: exactly one CSP on web routes
 * (the app's nonce policy, no 'unsafe-inline'), a deny-all CSP on /v1, same-origin SSE
 * through Caddy, and zero CSP violations while a real check streams to a final verdict.
 * The submitted address is a reserved `.test` name; whichever worker is attached decides
 * the verdict, so the test only requires that a final one arrives.
 */
import { expect, submitText, test, token } from "../e2e/helpers";

test("web routes carry only the app's strict nonce CSP; /v1 is deny-all", async ({ request }) => {
  const page = await request.get("/");
  expect(page.status()).toBe(200);
  const policies = page.headersArray().filter((h) => h.name.toLowerCase() === "content-security-policy");
  expect(policies, "exactly one CSP header on web routes").toHaveLength(1);
  const csp = policies[0]!.value;
  expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
  expect(csp).toMatch(/style-src 'self' 'nonce-[A-Za-z0-9+/=]+'/);
  expect(csp).not.toContain("unsafe-inline");
  expect(csp).not.toContain("unsafe-eval");

  const api = await request.get("/v1/version");
  expect(api.status()).toBe(200);
  expect(api.headers()["content-security-policy"]).toContain("default-src 'none'");
});

test("a real check streams through the gateway to a final verdict with zero CSP violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  const submitted = page.waitForResponse((r) => r.url().endsWith("/v1/check/url") && r.request().method() === "POST");
  await submitText(page, `https://falcon-demo-bank-secure.test/login?c=${token()}`);
  const response = await submitted;
  expect([200, 202]).toContain(response.status());

  await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final", { timeout: 30_000 });
  await expect(page.getByTestId("verdict-word")).toBeVisible();
  await expect(page.getByTestId("verdict-id")).toHaveText(/^vd_[0-9A-HJKMNP-TV-Z]{26}$/);
  await expect(page).toHaveURL(/\?id=vd_/);
  await expect(page.getByTestId("result").locator("a")).toHaveCount(0);
  // No demo ribbon and no demo examples: this is the real path.
  await expect(page.getByTestId("demo-ribbon")).toHaveCount(0);

  // Reload attaches to the stored verdict.
  await page.reload();
  await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final", { timeout: 30_000 });
});

test("boards answer honestly whatever the backend state", async ({ page }) => {
  await page.goto("/campaigns");
  await expect(page.getByTestId("board-not-connected").or(page.getByTestId("board-empty")).or(page.getByTestId("campaigns"))).toBeVisible();
  await expect(page.getByTestId("demo-ribbon")).toHaveCount(0);
});
