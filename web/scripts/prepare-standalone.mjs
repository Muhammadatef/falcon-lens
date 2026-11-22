#!/usr/bin/env node
// `output: "standalone"` leaves static assets outside .next/standalone. Copy them in so
// `pnpm start` (and the Playwright web server) serve the same thing the Docker image does.
import { cpSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const standalone = join(root, ".next", "standalone");
if (!existsSync(standalone)) {
  console.error("prepare-standalone: .next/standalone not found (did `next build` run?)");
  process.exit(1);
}
cpSync(join(root, ".next", "static"), join(standalone, ".next", "static"), { recursive: true });
cpSync(join(root, "public"), join(standalone, "public"), { recursive: true });
console.log("prepare-standalone: static and public copied");
