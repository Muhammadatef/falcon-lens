import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import bundled from "@/lib/eval-areas.generated.json";
import { AREA_ORDER, areaNote, areaScope, areaTitle, loadAreas, parseAreas, pendingKeys, pendingLabel, rowLabel, rowText, type Area } from "@/lib/results-areas";

const published = join(fileURLToPath(new URL("../../..", import.meta.url)), "evals", "results", "published");
const LANGS = ["ar", "en"] as const;

/** Every numeric token of a string, thousands separators dropped. */
const tokens = (s: string) => (s.replace(/,/g, "").match(/\d+(?:\.\d+)?/g) ?? []).map(Number);

function allowed(area: Area, key: string): Set<number> {
  const r = area.rows[key]!;
  const out = new Set<number>();
  for (const v of [r.value, r.lo, r.hi]) {
    if (v === null) continue;
    out.add(Number((v * 100).toFixed(1)));
    out.add(Number((v * 100 + 1e-9).toFixed(1)));
    out.add(Number(v.toPrecision(6)));
    out.add(Number(v.toFixed(6)));
  }
  for (const v of [r.k, r.n]) if (v !== null) out.add(v);
  return out;
}

describe("results areas (every displayed number exists in the bundled JSON)", () => {
  const areas = loadAreas();

  it("bundles every expected area with at least one row", () => {
    expect(areas.map((a) => a.id)).toEqual([...AREA_ORDER]);
    for (const a of areas) expect(Object.keys(a.rows).length).toBeGreaterThan(0);
  });

  it("each rendered figure is built only from its row's own value, k, n and range", () => {
    for (const lang of LANGS) {
      for (const a of areas) {
        for (const key of Object.keys(a.rows)) {
          const x = rowText(a.rows[key]!, lang);
          const ok = allowed(a, key);
          for (const t of tokens(`${x.main} ${x.detail} ${x.ci}`)) expect(ok.has(t), `${a.id}.${key} ${lang}: ${t}`).toBe(true);
        }
      }
    }
  });

  it("labels, scope and notes carry no digits and never say safe", () => {
    for (const lang of LANGS) {
      for (const a of areas) {
        const text = [areaTitle(a.id, lang), areaScope(a.id, lang), areaNote(a.id, lang), ...Object.keys(a.rows).map((k) => rowLabel(a.id, k, lang)), ...a.notEvaluated.map((k) => pendingLabel(k, lang))].join(" ");
        expect(text, `${a.id} ${lang}`).not.toMatch(/\d/);
        expect(text).not.toMatch(/\bsafe\b|آمن/i);
      }
    }
  });

  it("red-team always carries the harmful count together with the answered count", () => {
    const rt = areas.find((a) => a.id === "redteam")!;
    expect(rt.rows.extended_harmful).toBeDefined();
    expect(rt.rows.extended_answered).toBeDefined();
    expect(rt.rows.production_answered).toBeDefined();
    for (const lang of LANGS) expect(rowText(rt.rows.extended_harmful!, lang).detail).toContain(String(rt.rows.extended_harmful!.n));
  });

  it("keeps 'not evaluated' only where the artifact says so", () => {
    expect(areas.find((a) => a.id === "sandbox_t2")!.notEvaluated).toEqual(["phishing_side_t2_recall"]);
    expect(areas.find((a) => a.id === "arabic_clarity")!.notEvaluated).toEqual(["human_rating"]);
    const main = ["arabic_clarity", "cost_per_check_llm", "faithfulness", "flip_rate_3_runs", "injection_attack_success_rate", "llm_tier_T3", "sandbox_tier_T2", "zero_day", "synthetic", "cloud_route", "sovereign_route"];
    const p = pendingKeys(main, areas);
    expect(p.main).toEqual([]);
    expect([...p.extra].sort()).toEqual(["energy", "human_rating", "phishing_side_t2_recall"]);
  });

  it("returns nothing when the bundle is unavailable", () => {
    expect(parseAreas({ available: false })).toEqual([]);
    expect(parseAreas(null)).toEqual([]);
  });

  it("row values equal numbers present in the source artifact when the monorepo is present", () => {
    if (!existsSync(published)) return;
    const nums = (v: unknown, acc: Set<number>): Set<number> => {
      if (typeof v === "number") acc.add(v);
      else if (Array.isArray(v)) v.forEach((x) => nums(x, acc));
      else if (v && typeof v === "object") Object.values(v).forEach((x) => nums(x, acc));
      return acc;
    };
    const file = bundled as unknown as { areas: Record<string, { artifact: string; rows: Record<string, { value: number; k: number | null; n: number | null; lo: number | null; hi: number | null; artifact?: string }> }> };
    for (const [id, a] of Object.entries(file.areas)) {
      const dir = join(published, id.startsWith("fit_") ? "fits" : id);
      const load = (name: string) => {
        const path = join(dir, name);
        expect(existsSync(path), path).toBe(true);
        return nums(JSON.parse(readFileSync(path, "utf8")), new Set());
      };
      load(a.artifact);
      for (const [key, r] of Object.entries(a.rows)) {
        // A row cites its own artifact when it differs from the area's (red team: extended and production are separate files).
        const source = load(r.artifact ?? a.artifact);
        for (const v of [r.value, r.k, r.lo, r.hi]) if (v !== null) expect(source.has(v), `${id}.${key}=${v} in ${r.artifact ?? a.artifact}`).toBe(true);
      }
    }
    expect(readdirSync(published).length).toBeGreaterThan(0);
  });
});
