import { defineConfig } from "vitest/config";

export default defineConfig({
  // Build-time constants (scripts/build.mjs injects the real values).
  define: { __FL_API_BASE__: JSON.stringify("https://localhost:8443"), __FL_WEB_BASE__: JSON.stringify("https://localhost:8443") },
  test: { include: ["tests/*.test.ts"] }, // tests/e2e belongs to Playwright
});
