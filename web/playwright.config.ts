import { defineConfig, devices } from "@playwright/test";

/**
 * E2E runs the production build (strict CSP, no dev relaxations) behind a mock gateway
 * that serves /v1 with real SSE. Build first: `pnpm build && pnpm test:e2e`.
 * Odd ports so parallel stacks on the same host do not collide.
 */
const MOCK_PORT = Number(process.env.MOCK_PORT ?? 43110);
const APP_PORT = Number(process.env.APP_PORT ?? 43111);
/** Second stack whose /v1/meta reports every capability flag true (tests/e2e/helpers.ts: ALL_ON_URL). */
const ON_MOCK_PORT = Number(process.env.ON_MOCK_PORT ?? 43112);
const ON_APP_PORT = Number(process.env.ON_APP_PORT ?? 43113);
const ALL_CAPS = JSON.stringify(Object.fromEntries(["message_check", "email_check", "image_check", "injection_defence", "investigator", "t1_measured_model", "sentinel_agent", "rest_api", "mcp", "stix"].map((id) => [id, true])));
/** Set to a running stack's gateway (e.g. https://localhost:8443) to run tests/live through Caddy. */
const LIVE = process.env.LIVE_BASE_URL;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${MOCK_PORT}`,
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "phone-390", testMatch: /e2e\/.*\.spec\.ts/, use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } } },
    { name: "desktop-1440", testMatch: /e2e\/.*\.spec\.ts/, use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    // Screenshot capture, on demand only: SHOTS=1 pnpm exec playwright test --project=shots
    ...(process.env.SHOTS ? [{ name: "shots", testMatch: /shots\/.*\.shots\.ts/, timeout: 120_000, use: { ...devices["Desktop Chrome"] } }] : []),
    // Through the real gateway, on demand only: LIVE_BASE_URL=https://localhost:8443 pnpm exec playwright test --project=live
    ...(LIVE ? [{ name: "live", testMatch: /live\/.*\.live\.ts/, timeout: 90_000, use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, baseURL: LIVE, ignoreHTTPSErrors: true } }] : []),
  ],
  webServer: LIVE ? undefined : [
    {
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${APP_PORT}/api/health`,
      env: { PORT: String(APP_PORT), HOSTNAME: "127.0.0.1", NODE_ENV: "production", FL_API_INTERNAL_URL: `http://127.0.0.1:${MOCK_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "node tests/mock/gateway.mjs",
      url: `http://127.0.0.1:${MOCK_PORT}/api/health`,
      env: { MOCK_PORT: String(MOCK_PORT), APP_PORT: String(APP_PORT) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${ON_APP_PORT}/api/health`,
      env: { PORT: String(ON_APP_PORT), HOSTNAME: "127.0.0.1", NODE_ENV: "production", FL_API_INTERNAL_URL: `http://127.0.0.1:${ON_MOCK_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "node tests/mock/gateway.mjs",
      url: `http://127.0.0.1:${ON_MOCK_PORT}/api/health`,
      env: { MOCK_PORT: String(ON_MOCK_PORT), APP_PORT: String(ON_APP_PORT), MOCK_CAPS: ALL_CAPS },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
