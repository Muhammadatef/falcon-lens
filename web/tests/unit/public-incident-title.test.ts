import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BRAND_NAMES } from "@/lib/brand-names";
import { publicIncidentTitle, toPublicIncident } from "@/lib/public-history";

const IID = "inc_01HZX3K9Q2M4N5P6R7S8T9V0WX";
const base = { incident_id: IID, type: "campaign", severity: "high", status: "open", created_at: "2026-11-24T10:00:00Z", updated_at: "2026-11-24T10:00:00Z", source: "live" };

describe("public incident title is built from structured fields only", () => {
  it("known brand, Arabic and English", () => {
    expect(publicIncidentTitle("campaign", "falcon_demo_bank")).toEqual({ ar: "حملة احتيال تنتحل بنك الصقر التجريبي", en: "Suspected scam campaign impersonating Falcon Demo Bank" });
  });
  it("unknown, missing or hostile brand falls back to the generic title", () => {
    for (const b of ["nope", null, undefined, "__proto__", "constructor", "<script>", 7]) {
      expect(publicIncidentTitle("campaign", b)).toEqual({ ar: "حملة احتيال مشتبه بها", en: "Suspected scam campaign" });
    }
  });
  it("unknown type uses the campaign title; other types have their own", () => {
    expect(publicIncidentTitle("evil", null).en).toBe("Suspected scam campaign");
    expect(publicIncidentTitle("report_burst", "falcon_demo_bank").en).toContain("Falcon Demo Bank");
    expect(publicIncidentTitle("quality", "falcon_demo_bank").en).toBe("Check quality note");
  });
  it("projection ignores the free-text summary and never emits the removed-text marker", () => {
    const evil = { ar: "اتصل 0501234567 evil.test/x?t=1", en: "Call 0501234567 https://evil.test/x?t=1 <b>" };
    const out = toPublicIncident({ ...base, brand_id: "falcon_demo_bank", summary: evil })!;
    const s = JSON.stringify(out.summary);
    expect(s).toContain("Falcon Demo Bank");
    expect(s).not.toMatch(/evil|0501234567|text removed|أُزيل/);
  });
  it("brand table matches data/brands.yaml", () => {
    const yaml = readFileSync(resolve(__dirname, "../../../data/brands.yaml"), "utf8");
    const found = [...yaml.matchAll(/- brand_id: (\S+)\n\s+name_en: (.+)\n\s+name_ar: (.+)\n/g)];
    expect(found.length).toBeGreaterThan(20);
    for (const [, id, en, ar] of found) expect(BRAND_NAMES[id!]).toEqual({ ar: ar!.trim(), en: en!.trim() });
    expect(Object.keys(BRAND_NAMES)).toHaveLength(found.length);
  });
});
