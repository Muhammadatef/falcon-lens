import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { SCRIPT, SCRIPT_KEYS, arbiterClips, checkingClips, finalClips, foundClips, investigatorStartClips, sentinelClips, sentinelFindingClips, summaryClips, todoClips } from "../../lib/voice-script";

const en = JSON.parse(readFileSync(new URL("../../public/voice/en/manifest.json", import.meta.url), "utf8")) as { id: string; text: string; voice: string }[];

describe("every spoken line is a pre-generated clip", () => {
  it("the committed English manifest has every script id, with the script text, in one voice", () => {
    const byId = new Map(en.map((e) => [e.id, e]));
    for (const key of SCRIPT_KEYS) {
      const e = byId.get(`en.${key}`);
      expect(e, `en.${key} missing from the manifest`).toBeDefined();
      expect(e!.text).toBe(SCRIPT.en[key]);
    }
    expect(new Set(en.map((e) => e.voice))).toEqual(new Set(["am_fenrir"]));
  });

  it("every composer only emits keys that exist in the script (both languages)", () => {
    const keys: string[] = [];
    for (let n = 1; n <= 10; n++) keys.push(...foundClips(n), ...investigatorStartClips(n), ...sentinelClips(n));
    for (let n = 1; n <= 10; n++) for (let i = 1; i <= n; i++) keys.push(...checkingClips(i, n));
    for (const v of ["dangerous", "suspicious", "no_warning_signs", null] as const) for (const s of [0, 7, 55, 100]) keys.push(...arbiterClips(v, s));
    for (let total = 0; total <= 10; total++) {
      for (let d = 0; d <= total; d++) {
        const c = { total, dangerous: d, suspicious: total - d, clear: 0, failed: 0 };
        keys.push(...summaryClips(c), ...todoClips(c));
        for (const s of ["found", "watching", "unavailable", "none"] as const) keys.push(...finalClips(c, s));
      }
    }
    for (const linked of [0, 1, 2, 3, 10]) for (const b of [true, false]) keys.push(...sentinelFindingClips({ linked, linkStep: b, summary: b, drafted: b, awaiting: b }));
    for (const k of keys) {
      expect(SCRIPT.ar_ae[k], `ar_ae.${k}`).toBeTruthy();
      expect(SCRIPT.en[k], `en.${k}`).toBeTruthy();
    }
  });
});
