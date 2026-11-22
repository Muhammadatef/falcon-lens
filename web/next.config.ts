import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  turbopack: { root: dirname(fileURLToPath(import.meta.url)) },
  outputFileTracingRoot: dirname(fileURLToPath(import.meta.url)),
  async headers() {
    return [
      // The service worker must never be served stale, and may control the whole origin.
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache, no-store, must-revalidate" }, { key: "Service-Worker-Allowed", value: "/" }] },
      { source: "/fonts/:path*", headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }] },
    ];
  },
};

export default config;
