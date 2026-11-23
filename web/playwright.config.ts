import { execFileSync } from "node:child_process";
import { defineConfig, devices } from "@playwright/test";

/**
 * E2E runs the production build (strict CSP, no dev relaxations) behind a mock gateway
 * that serves /v1 with real SSE. Build first: `pnpm build && pnpm test:e2e`.
 */
/**
 * Free ports are reserved once per run in the main process and passed to workers via env
 * (workers re-evaluate this file), so concurrent runs on one host cannot collide.
 * MOCK_PORT / APP_PORT still override.
 */
function freePorts(n: number): number[] {
  const code = `const s=[];let d=0;const out=[];for(let i=0;i<${n};i++){const x=require("net").createServer();x.listen(0,"127.0.0.1",()=>{out.push(x.address().port);s.push(x);if(++d===${n}){console.log(out.join(","));s.forEach(y=>y.close())}})}`;
  return execFileSync(process.execPath, ["-e", code], { encoding: "utf8" }).trim().split(",").map(Number);
}
if (!process.env.MOCK_PORT || !process.env.APP_PORT) {
  const [m, a] = freePorts(2);
  process.env.MOCK_PORT ??= String(m);
  process.env.APP_PORT ??= String(a);
}
const MOCK_PORT = Number(process.env.MOCK_PORT);
const APP_PORT = Number(process.env.APP_PORT);
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
  ],
});
