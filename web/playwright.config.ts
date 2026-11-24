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
if (!process.env.MOCK_PORT || !process.env.APP_PORT || !process.env.APP_PORT_CAPS_FALSE || !process.env.APP_PORT_CAPS_TRUE) {
  const [m, a, cf, ct] = freePorts(4);
  process.env.MOCK_PORT ??= String(m);
  process.env.APP_PORT ??= String(a);
  process.env.APP_PORT_CAPS_FALSE ??= String(cf);
  process.env.APP_PORT_CAPS_TRUE ??= String(ct);
}
const MOCK_PORT = Number(process.env.MOCK_PORT);
const APP_PORT = Number(process.env.APP_PORT);
const CAPS_FALSE_PORT = Number(process.env.APP_PORT_CAPS_FALSE);
const CAPS_TRUE_PORT = Number(process.env.APP_PORT_CAPS_TRUE);
/** Set to a running stack's gateway (e.g. https://localhost:8443) to run tests/live through Caddy. */
const LIVE = process.env.LIVE_BASE_URL;
/** The spoken demo line (wav) the fake microphone plays; set by `make voice-e2e`. */
const VOICE_WAV = process.env.VOICE_E2E_WAV;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  // Local runs cap workers (browser memory); GitHub CI keeps Playwright's default.
  ...(process.env.CI ? {} : { workers: Number(process.env.FL_PW_WORKERS ?? 2) }),
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
    // The @voice-live suite needs a spoken wav and macOS `say`: run it with `make voice-e2e` (see tests/live/voice.live.ts).
    ...(VOICE_WAV ? [{
      name: "voice-live",
      testMatch: /live\/voice\.live\.ts/,
      timeout: 240_000,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 900 },
        baseURL: process.env.BASE_URL ?? process.env.LIVE_BASE_URL ?? "https://localhost:8443",
        ignoreHTTPSErrors: true,
        launchOptions: {
          args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${VOICE_WAV}%noloop`, "--autoplay-policy=no-user-gesture-required"],
        },
      },
    }] : []),
    ...(LIVE ? [{ name: "live", testMatch: /live\/.*\.live\.ts/, testIgnore: /live\/voice\.live\.ts/, timeout: 90_000, use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, baseURL: LIVE, ignoreHTTPSErrors: true } }] : []),
  ],
  webServer: LIVE || VOICE_WAV ? undefined : [
    {
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${APP_PORT}/api/health`,
      env: { PORT: String(APP_PORT), HOSTNAME: "127.0.0.1", NODE_ENV: "production", FL_API_INTERNAL_URL: `http://127.0.0.1:${MOCK_PORT}`, FL_WEB_READ_KEY: "test-read-key", FL_WEB_TEST_FORWARD_COOKIE: "mock_boards" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    // Same build, but /v1/meta reports every capability false / true (cookie `mock_caps`, routed by the mock gateway).
    ...([["false", CAPS_FALSE_PORT], ["true", CAPS_TRUE_PORT]] as const).map(([mode, port]) => ({
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${port}/api/health`,
      env: { PORT: String(port), HOSTNAME: "127.0.0.1", NODE_ENV: "production", FL_API_INTERNAL_URL: `http://127.0.0.1:${MOCK_PORT}/__caps/${mode}` },
      reuseExistingServer: false,
      timeout: 60_000,
    })),
    {
      command: "node tests/mock/gateway.mjs",
      url: `http://127.0.0.1:${MOCK_PORT}/api/health`,
      env: { MOCK_PORT: String(MOCK_PORT), APP_PORT: String(APP_PORT), APP_PORT_CAPS_FALSE: String(CAPS_FALSE_PORT), APP_PORT_CAPS_TRUE: String(CAPS_TRUE_PORT) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
