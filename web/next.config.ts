import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  turbopack: { root: dirname(fileURLToPath(import.meta.url)) },
  outputFileTracingRoot: dirname(fileURLToPath(import.meta.url)),
  async redirects() {
    // Permanent (308). /architecture/agents lands on /docs/agents (built by the docs card, W2-07).
    return [
      { source: "/how-it-works", destination: "/agents", permanent: true },
      { source: "/architecture/agents", destination: "/docs/agents", permanent: true },
    ];
  },
  async rewrites() {
    // Private (uncommitted) voice clips win over the committed public/voice files; the route falls back to them.
    return { beforeFiles: [{ source: "/voice/:lang/:file", destination: "/api/voice-clips/:lang/:file" }], afterFiles: [], fallback: [] };
  },
  async headers() {
    return [
      // The service worker must never be served stale, and may control the whole origin.
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache, no-store, must-revalidate" }, { key: "Service-Worker-Allowed", value: "/" }] },
      { source: "/fonts/:path*", headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }] },
    ];
  },
};

export default config;
