import { describe, expect, it } from "vitest";
import { DEMO_DANGEROUS } from "@/lib/demo";
import type { Evidence, Verdict } from "@/lib/contracts";
import { CLIPS, findingKeysFor, sentinelFindingGroups, tierFindingGroups } from "@/lib/voice-script";
import { campaignBrand, spoken, stepGroups, tierFoundText } from "@/lib/voice-speech";
import { tierRows } from "@/lib/voice-progress";

const ev = (signal: string, tier: Evidence["tier"], weight: number, observed: unknown = true, extra: Partial<Evidence> = {}): Evidence => ({
  id: `ev_${signal.replace(/[^a-z]/g, "").slice(0, 12).padEnd(8, "x")}`,
  signal,
  family: signal.split(".")[0]!,
  observed,
  weight,
  polarity: weight > 0 ? "risk" : "neutral",
  source: "computed",
  tier,
  ...extra,
});
const known = new Set(CLIPS.map((c) => c.key));
const withEv = (evidence: Evidence[], extra: Partial<Verdict> = {}): Verdict => ({ ...DEMO_DANGEROUS, tier_reached: "T2", model_route: "none", evidence, ...extra });

describe("per-check findings come from the real evidence", () => {
  it("speaks the strongest two findings per tier, in weight order", () => {
    const g = tierFindingGroups([ev("url.combosquat", "T1", 2), ev("domain.age_days", "T1", 2.5, { age_days: 3 }), ev("url.shortener", "T1", 0.4)], "T1");
    expect(g).toEqual([["find.age.lead", "num.3", "find.age.days"], ["find.combosquat"]]);
  });
  it("numbers use the exact num clips; 0..2 days have their own wording; over 100 days is not spoken", () => {
    const k = (n: number) => findingKeysFor(ev("domain.age_days", "T1", 2, { age_days: n, registered_at: "x", registrar: null, domain: "a.test" }));
    expect(k(42)).toEqual(["find.age.lead", "num.42", "find.age.days"]);
    expect(k(0)).toEqual(["find.age.0"]);
    expect(k(2)).toEqual(["find.age.2"]);
    expect(k(400)).toBeNull();
    expect(findingKeysFor(ev("domain.cert_age_days", "T1", 1, { cert_age_days: 9, first_seen: "x", certs_seen: 1 }))).toEqual(["find.cert.lead", "num.9", "find.cert.days"]);
  });
  it("an unknown code, a trust item, a zero weight and an errored signal are never spoken", () => {
    expect(findingKeysFor(ev("evil.<script>alert(1)</script>", "T1", 5))).toBeNull();
    expect(findingKeysFor(ev("url.combosquat", "T1", -3, true, { polarity: "trust" }))).toBeNull();
    expect(findingKeysFor(ev("rep.openphish", "T0", 0, false))).toBeNull();
    expect(findingKeysFor(ev("url.combosquat", "T1", 2, true, { error: "timeout" }))).toBeNull();
    expect(tierFindingGroups([ev("totally.unknown", "T1", 9)], "T1")).toEqual([["find.none"]]);
  });
  it("a tier with nothing speakable says so, except the AI tier", () => {
    expect(tierFindingGroups([], "T0")).toEqual([["find.none"]]);
    expect(tierFindingGroups([ev("llm.model_name", "T3", 1, "x")], "T3")).toEqual([]);
  });
  it("brand names come from the small clip set, else a generic body", () => {
    expect(findingKeysFor(ev("brand.claimed_not_owned", "T2", 3, { brand_id: "falcon_demo_bank" }))).toEqual(["find.brand.a", "brand.falcon_demo_bank", "find.brand.b"]);
    expect(findingKeysFor(ev("brand.claimed_not_owned", "T2", 3, { brand_id: "<img onerror=x>" }))).toEqual(["find.brand.generic"]);
    expect(findingKeysFor(ev("brand.claimed_not_owned", "T2", 3, { brand_id: "some_unlisted_brand" }))).toEqual(["find.brand.generic"]);
  });
  it("a credential form says what it really asked for, by field kind", () => {
    const k = (kinds: string[]) => findingKeysFor(ev("page.cred_form", "T2", 1.5, { present: true, field_kinds: kinds, forms: 1 }));
    expect(k(["otp", "password"])).toEqual(["find.cred.password_otp"]);
    expect(k(["card", "cvv", "password"])).toEqual(["find.cred.card"]);
    expect(k(["emirates_id"])).toEqual(["find.cred.eid"]);
    expect(k(["pin"])).toEqual(["find.cred.pin"]);
    expect(k(["otp"])).toEqual(["find.cred.otp"]);
    expect(k(["<img>"])).toEqual(["find.cred.generic"]);
    expect(findingKeysFor(ev("page.cred_form", "T2", 1.5, true))).toEqual(["find.cred.generic"]);
  });
  it("incomplete page renders are spoken even with no weight", () => {
    expect(findingKeysFor(ev("sandbox.not_rendered", "T2", 0))).toEqual(["find.incomplete"]);
  });
  it("every spoken key exists as a clip in both languages", () => {
    const codes = ["rep.openphish", "url.combosquat", "url.homograph", "page.cred_form", "page.cross_origin_post", "message.rule.otp_request", "email.auth_fail", "image.qr_decoded", "sandbox.not_rendered"];
    for (const c of codes) for (const k of findingKeysFor(ev(c, "T1", 1)) ?? []) expect(known.has(k), k).toBe(true);
    for (const k of sentinelFindingGroups({ linked: 3, linkStep: true, summary: true, drafted: true, awaiting: true, brand: "falcon_demo_bank" }).flat()) expect(known.has(k), k).toBe(true);
  });
  it("two different checks give different step texts and the panel rows equal the spoken lines", () => {
    const bank = withEv([ev("url.combosquat", "T1", 2), ev("domain.age_days", "T1", 2.5, { age_days: 2 }), ev("page.cred_form", "T2", 1.5, { present: true, field_kinds: ["password", "otp"], forms: 1 })]);
    const sms = withEv([ev("message.rule.delivery_fee", "T1", 1.2), ev("message.rule.urgency", "T1", 0.8)], { tier_reached: "T1" });
    const a = stepGroups("lookalike", bank).map((g) => spoken("ar", g));
    const b = stepGroups("wording", sms).map((g) => spoken("ar", g));
    expect(a.join("|")).not.toBe(b.join("|"));
    expect(a.join(" ")).toContain("النطاق مسجّل قبل يومين");
    expect(b.join(" ")).toContain("رسوم توصيل");
    const row = tierRows(bank, "url", "ar", true).find((r) => r.tier === "T1");
    expect(row?.found).toBe(tierFoundText("ar", "lookalike", bank));
    expect(row?.found).toBe(a.slice(1).join(" "));
  });
  it("the campaign brand is named only when known and clipped", () => {
    const base = { linked: 3, linkStep: true, summary: false, drafted: false, awaiting: false };
    expect(sentinelFindingGroups({ ...base, brand: "falcon_demo_bank" })).toEqual([["sentinel.linked.3"], ["sentinel.campaign", "brand.falcon_demo_bank"]]);
    expect(sentinelFindingGroups({ ...base, brand: "unknown_brand" })).toEqual([["sentinel.linked.3"]]);
    expect(sentinelFindingGroups({ ...base, brand: null })).toEqual([["sentinel.linked.3"]]);
    const o = (id: string) => ({ verdict: { ...DEMO_DANGEROUS, verdict: "dangerous" as const, impersonated_brand: { brand_id: id, name_ar: "x", name_en: "x" } } }) as never;
    expect(campaignBrand([o("falcon_demo_bank"), o("falcon_demo_bank"), o("salik")])).toBe("falcon_demo_bank");
  });
});
