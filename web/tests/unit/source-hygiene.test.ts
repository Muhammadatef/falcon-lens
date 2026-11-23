import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("../..", import.meta.url));
const SKIP = new Set(["node_modules", ".next", "tests", "design", "test-results", "playwright-report", "eslint.config.mjs"]);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    if (SKIP.has(name)) return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(tsx?|mjs|js|css|html)$/.test(name) ? [path] : [];
  });
}

const files = sources(root);
// Built from parts so this file does not match itself if the skip list ever changes.
const FORBIDDEN: [string, RegExp][] = [
  ["dangerouslySet" + "InnerHTML", new RegExp("dangerouslySet" + "InnerHTML")],
  ["innerHTML / outerHTML assignment", /\.(inner|outer)HTML\s*=/],
  ["insertAdjacentHTML", /insertAdjacentHTML/],
  ["document.write", /document\.write\(/],
  ["eval / new Function", /\beval\(|new Function\(/],
  ["third-party runtime origin", /https?:\/\/(fonts\.googleapis|fonts\.gstatic|cdn\.|unpkg|cdnjs)/],
];

describe("source hygiene (app code, not tests)", () => {
  it("finds the app sources", () => {
    expect(files.length).toBeGreaterThan(20);
    expect(files.some((f) => f.endsWith("components/Result.tsx"))).toBe(true);
  });

  for (const [label, pattern] of FORBIDDEN) {
    it(`never uses ${label}`, () => {
      const hits = files.filter((file) => pattern.test(readFileSync(file, "utf8"))).map((f) => f.slice(root.length));
      expect(hits).toEqual([]);
    });
  }

  it("never builds an href or src from verdict data (links are internal constants only)", () => {
    for (const file of files.filter((f) => f.endsWith(".tsx"))) {
      const text = readFileSync(file, "utf8");
      // Internal constants only: nav entries, the /docs/<slug> list, and the figure paths in lib/docs-content.ts.
      const ALLOWED = ["l.href", "`/docs/${slug", "`/docs/${s", "REPO_BLOB + src", "page.figure.src", "f.src"];
      for (const m of text.matchAll(/\b(href|src)=\{([^}]+)\}/g)) expect(ALLOWED, `${file}: ${m[0]}`).toContain(m[2]);
    }
  });
});
