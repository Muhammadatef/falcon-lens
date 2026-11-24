import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AR_NOTES } from "../../lib/artifact-notes-ar";
import { artifactNote } from "../../lib/results-kpi";

const LIB = join(__dirname, "../../lib");
const KEYS = new Set(["caveat", "provenance", "separationrule", "syntheticurlscaveat"]);

function notes(o: unknown, out: Set<string>) {
  if (Array.isArray(o)) o.forEach((x) => notes(x, out));
  else if (o && typeof o === "object") {
    for (const [k, v] of Object.entries(o)) {
      if (typeof v === "string" && KEYS.has(k.toLowerCase()) && v.trim()) out.add(v);
      else notes(v, out);
    }
  }
}

describe("artifact notes in Arabic", () => {
  const found = new Set<string>();
  for (const f of readdirSync(LIB).filter((n) => n.endsWith(".generated.json"))) notes(JSON.parse(readFileSync(join(LIB, f), "utf8")), found);

  it("finds the notes in the bundle", () => expect(found.size).toBeGreaterThan(10));
  it("every caveat and provenance note in the bundle has a formal Arabic translation", () => {
    expect([...found].filter((t) => !AR_NOTES[t])).toEqual([]);
  });
  it("keeps every digit group of the English note in the Arabic one", () => {
    for (const t of found) {
      const digits = (s: string) => (s.match(/\d+(?:\.\d+)?/g) ?? []).sort().join(",");
      expect(digits(AR_NOTES[t]!), t).toBe(digits(t));
    }
  });
  it("no translation says safe", () => expect(Object.values(AR_NOTES).join(" ")).not.toMatch(/آمن/));
  it("English is returned untouched, an unknown Arabic note yields null so the UI shows the labelled English", () => {
    expect(artifactNote("x note", "en")).toBe("x note");
    expect(artifactNote("a future note", "ar")).toBeNull();
  });
});
