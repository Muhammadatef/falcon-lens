import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { arLinkedChecks } from "@/lib/ar-count";
import { BRAND_NAMES } from "@/lib/brand-names";
import { publicIncidentTitle, publicSeverityLine, toPublicIncident } from "@/lib/public-history";

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
  it("R1: lookalike domains for one brand, counts domains, omits 0", () => {
    expect(publicSeverityLine(["R1"], 9, 3)).toEqual({ ar: "رُصد 3 نطاقات جديدًا تشبه علامة واحدة خلال ساعة.", en: "3 new lookalike domains for one brand within an hour." });
    expect(publicSeverityLine(["R1"], 9, 1).en).toBe("1 new lookalike domain for one brand within an hour.");
    expect(publicSeverityLine(["R1"], 9, 0)).toEqual({ ar: "رُصدت نطاقات جديدة تشبه علامة واحدة خلال ساعة.", en: "New lookalike domains for one brand within an hour." });
  });
  it("R2: same page fingerprint, counts domains, omits 0", () => {
    expect(publicSeverityLine(["R2"], 0, 4)).toEqual({ ar: "ظهر 4 نطاقات بالبصمة نفسها للصفحة خلال 7 أيام.", en: "4 domains with the same page fingerprint within 7 days." });
    expect(publicSeverityLine(["R2"], 0, 12).ar).toContain("12 نطاقًا");
    expect(publicSeverityLine(["R2"], 0, 0).en).toBe("Domains with the same page fingerprint within 7 days.");
  });
  it("R3: report burst, no invented count", () => {
    expect(publicSeverityLine(["R3"], 7, 2)).toEqual({ ar: "وردت عدة بلاغات متشابهة خلال 30 دقيقة.", en: "Several similar scam reports arrived within 30 minutes." });
  });
  it("R4: neutral wording, no safe/سليم/آمن", () => {
    const l = publicSeverityLine(["R4"], 1, 1);
    expect(l.en).toBe("A domain that earlier showed no warning signs now has a dangerous verdict.");
    expect(l.ar).toContain("لم تظهر عليه علامات تحذير سابقًا");
    expect(JSON.stringify(l)).not.toMatch(/سليم|آمن|safe/i);
  });
  it("R5: false-alarm feedback, no invented count", () => {
    expect(publicSeverityLine(["R5"], 7, 2).en).toBe("Several feedback reports say the same signal raised a false alarm within an hour.");
    expect(publicSeverityLine(["R5"], 7, 2).ar).toContain("إنذارًا خاطئًا");
  });
  it("unknown rule: generic line with Arabic number agreement; no count when 0", () => {
    expect(publicSeverityLine(["R99", "<x>"], 1, 0)).toEqual({ ar: "ربط الحارس فحص واحد بهذه الحادثة.", en: "Sentinel linked 1 check to this incident." });
    expect(publicSeverityLine([], 2, 0).ar).toBe("ربط الحارس فحصان بهذه الحادثة.");
    expect(publicSeverityLine([], 5, 0).ar).toBe("ربط الحارس 5 فحوص بهذه الحادثة.");
    expect(publicSeverityLine([], 11, 0).ar).toBe("ربط الحارس 11 فحصًا بهذه الحادثة.");
    expect(publicSeverityLine([], 0, 0).en).toBe("Sentinel recorded this incident.");
  });
  it("Arabic count helper", () => {
    expect([1, 2, 3, 10, 11].map((n) => arLinkedChecks(n))).toEqual(["فحص واحد مرتبط", "فحصان مرتبطان", "3 فحوص مرتبطة", "10 فحوص مرتبطة", "11 فحصًا مرتبطًا"]);
  });
  it("projection never carries free-text severity reason", () => {
    const out = toPublicIncident({ ...base, rule_ids: ["R1"], severity_reason: { ar: "اتصل 0501234567", en: "Call evil.test/x" } })!;
    expect(JSON.stringify(out.severity_reason)).not.toMatch(/evil|0501234567|removed/);
  });
});
