/**
 * Picks two free loopback ports and builds the e2e extension against them into a private temp
 * dir, so parallel runs (other worktrees, CI shards) never collide on a fixed port or a shared
 * dist-e2e. Workers inherit the values through process.env.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const freePort = (): Promise<number> =>
  new Promise((resolve, reject) => {
    const s = createServer();
    s.once("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address() as { port: number };
      s.close(() => resolve(port));
    });
  });

export default async function globalSetup(): Promise<() => void> {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const out = mkdtempSync(join(tmpdir(), "fl-ext-e2e-"));
  const api = await freePort();
  let site = await freePort();
  while (site === api) site = await freePort();
  process.env.FL_E2E_API_PORT = String(api);
  process.env.FL_E2E_SITE_PORT = String(site);
  process.env.FL_E2E_OUT = out;
  execFileSync("node", [join(root, "scripts", "build.mjs"), "--e2e"], { cwd: root, stdio: "inherit", env: process.env });
  return () => rmSync(out, { recursive: true, force: true });
}
