import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import { DEFAULT_CAUTION, parseCampaign, parseIncident, parseVerdict, unwrapList } from "@/lib/contracts";
import { DEMO_CAMPAIGNS, DEMO_DANGEROUS, DEMO_INCIDENT, DEMO_NWS, DEMO_STREAMS } from "@/lib/demo";
import { degradedVerdict, xssVerdict } from "../fixtures";

const schema = (name: string) => JSON.parse(readFileSync(fileURLToPath(new URL(`../../../contracts/${name}`, import.meta.url)), "utf8"));

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema(schema("evidence.schema.json"));
const validVerdict = ajv.compile(schema("verdict.schema.json"));
const validIncident = ajv.compile(schema("incident.schema.json"));

const strings = (node: unknown): string[] =>
  typeof node === "string" ? [node] : Array.isArray(node) ? node.flatMap(strings) : node && typeof node === "object" ? Object.values(node).flatMap(strings) : [];

const allVerdicts = [...DEMO_STREAMS.danger, ...DEMO_STREAMS.nws].map((s) => s.verdict).concat(degradedVerdict("vd_01KB0TEST000000000000000D1"), xssVerdict("vd_01KB0TEST000000000000000X1"));

describe("fixtures against the contracts (contracts are law)", () => {
  it("every demo and test verdict validates against verdict.schema.json", () => {
    for (const v of allVerdicts) {
      const ok = validVerdict(v);
      expect(validVerdict.errors ?? [], `${v.verdict_id} final=${v.final}`).toEqual([]);
      expect(ok).toBe(true);
    }
  });

  it("the demo incident validates against incident.schema.json", () => {
    validIncident(DEMO_INCIDENT);
    expect(validIncident.errors ?? []).toEqual([]);
  });

  it("holds the documented invariants", () => {
    for (const v of allVerdicts) {
      const ids = new Set(v.evidence.map((e) => e.id));
      for (const r of v.reasons) for (const id of r.evidence_ids) expect(ids.has(id)).toBe(true);
      if (v.verdict === "no_warning_signs") expect(v.actions.caution?.ar.length).toBeGreaterThan(0);
      if (v.degraded) expect(v.verdict).not.toBe("no_warning_signs");
    }
  });

  it("uses the registry spelling of the invented brand and only defanged, reserved-TLD URLs", () => {
    expect(DEMO_DANGEROUS.impersonated_brand?.name_ar).toBe("بنك الصقر التجريبي");
    const all = strings([DEMO_DANGEROUS, DEMO_NWS, DEMO_INCIDENT, DEMO_CAMPAIGNS]);
    expect(all.some((s) => s.includes("فالكون"))).toBe(false);
    for (const s of all) {
      if (s.includes("adpolice.gov.ae")) continue; // official reporting channels from config
      expect(s, s).not.toMatch(/https?:\/\//i);
      for (const host of s.match(/[a-z0-9-]+\[\.\][a-z]+/gi) ?? []) expect(host).toMatch(/\[\.\](test|invalid)$/);
    }
  });
});

describe("parseVerdict", () => {
  it("round-trips a contract-valid verdict", () => {
    const parsed = parseVerdict(JSON.parse(JSON.stringify(DEMO_DANGEROUS)));
    expect(parsed?.verdict).toBe("dangerous");
    expect(parsed?.evidence).toHaveLength(7);
    expect(parsed?.reasons).toHaveLength(3);
    expect(parsed?.trace).toHaveLength(4);
    expect(parsed?.actions.report.channels).toHaveLength(3);
  });

  it("rejects payloads that are not verdicts", () => {
    expect(parseVerdict(null)).toBeNull();
    expect(parseVerdict("vd_x")).toBeNull();
    expect(parseVerdict({ ...DEMO_NWS, verdict: "safe" })).toBeNull();
    expect(parseVerdict({ ...DEMO_NWS, verdict_id: "../../etc/passwd" })).toBeNull();
    expect(parseVerdict({ ...DEMO_NWS, final: "true" })).toBeNull();
    expect(parseVerdict({ ...DEMO_NWS, tier_reached: "T9" })).toBeNull();
  });

  it("invariant 4: a degraded no_warning_signs is never passed on as no_warning_signs", () => {
    for (const final of [true, false]) {
      const v = parseVerdict({ ...DEMO_NWS, degraded: true, degraded_reasons: ["rdap_unavailable"], final })!;
      expect(v.verdict).toBe("suspicious");
      expect(v.degraded).toBe(true);
    }
    // Not degraded: left as it is. Degraded but already cautious: left as it is.
    expect(parseVerdict(DEMO_NWS)!.verdict).toBe("no_warning_signs");
    expect(parseVerdict({ ...DEMO_DANGEROUS, degraded: true })!.verdict).toBe("dangerous");
    // Only a real boolean true counts; a truthy string does not flip a clean verdict.
    expect(parseVerdict({ ...DEMO_NWS, degraded: "false" })!.verdict).toBe("no_warning_signs");
  });

  it("invariant 3: no_warning_signs always carries a caution list", () => {
    const { caution: _caution, ...withoutCaution } = DEMO_NWS.actions;
    void _caution;
    expect(parseVerdict({ ...DEMO_NWS, actions: withoutCaution })!.actions.caution).toEqual(DEFAULT_CAUTION);
    expect(parseVerdict({ ...DEMO_NWS, actions: { ...DEMO_NWS.actions, caution: { ar: [], en: [] } } })!.actions.caution).toEqual(DEFAULT_CAUTION);
    expect(parseVerdict({ ...DEMO_NWS, actions: { ...DEMO_NWS.actions, caution: "be careful" } })!.actions.caution).toEqual(DEFAULT_CAUTION);
    expect(parseVerdict({ ...DEMO_NWS, actions: null })!.actions.caution).toEqual(DEFAULT_CAUTION);
    // One language present: it is kept, the other is filled.
    const half = parseVerdict({ ...DEMO_NWS, actions: { ...DEMO_NWS.actions, caution: { ar: ["تنبيه"], en: [] } } })!.actions.caution;
    expect(half).toEqual({ ar: ["تنبيه"], en: DEFAULT_CAUTION.en });
    // The API's own caution is used untouched, and other verdicts get none invented.
    expect(parseVerdict(DEMO_NWS)!.actions.caution).toEqual(DEMO_NWS.actions.caution);
    expect(parseVerdict(DEMO_DANGEROUS)!.actions.caution).toBeUndefined();
    for (const s of [...DEFAULT_CAUTION.ar, ...DEFAULT_CAUTION.en]) expect(s).not.toMatch(/\bsafe\b|آمن/i);
  });

  it("drops non-string and malformed members instead of rendering them", () => {
    const hostile = {
      ...DEMO_DANGEROUS,
      risk_score: 250,
      evidence: [...DEMO_DANGEROUS.evidence, { id: 7 }, { id: "ev_ok000001", tier: "T1", display: { ar: { __html: "<b>x</b>" }, en: 5 } }, "junk"],
      reasons: [{ ar: { toString: "x" }, en: "x", evidence_ids: ["ev_brand0own1"] }, { ar: "أ", en: "a", evidence_ids: ["ev_missing0001", "ev_brand0own1"] }, 4, ...DEMO_DANGEROUS.reasons],
      actions: { now: { ar: ["ok", 5, null], en: "nope" }, report: { ar: 1, en: "Report", channels: [{ value: 999 }, { value: "999", label_ar: {}, label_en: "Emergency" }] } },
      trace: [{ step: 2, kind: "tool", summary: "b" }, { step: 1, kind: "evil", summary: "a" }, { step: 0, kind: "tier", summary: 3 }],
      impersonated_brand: { name_ar: ["x"], name_en: "y" },
    };
    const v = parseVerdict(hostile)!;
    expect(v.risk_score).toBe(100);
    expect(v.evidence).toHaveLength(8);
    expect(v.evidence[7]?.display).toEqual({ ar: undefined, en: undefined });
    expect(v.reasons).toHaveLength(3);
    expect(v.reasons[0]).toEqual({ ar: "أ", en: "a", evidence_ids: ["ev_brand0own1"] });
    expect(v.actions.now).toEqual({ ar: ["ok"], en: [] });
    expect(v.actions.if_already_acted).toEqual({ ar: [], en: [] });
    expect(v.actions.report.ar).toBe("");
    expect(v.actions.report.channels).toEqual([{ label_ar: "", label_en: "Emergency", value: "999", source_url: "", retrieved_at: "" }]);
    expect(v.trace).toEqual([{ step: 2, kind: "tool", name: undefined, summary: "b", evidence_added: [], ms: undefined }]);
    expect(v.impersonated_brand).toBeNull();
  });
});

describe("boards", () => {
  it("parses incidents and rejects malformed ones", () => {
    expect(parseIncident(JSON.parse(JSON.stringify(DEMO_INCIDENT)))?.actions).toHaveLength(3);
    expect(parseIncident({ ...DEMO_INCIDENT, incident_id: "inc_bad" })).toBeNull();
    expect(parseIncident({ ...DEMO_INCIDENT, severity: "apocalyptic" })).toBeNull();
  });

  it("accepts a campaign object or a campaign-type incident", () => {
    expect(parseCampaign(DEMO_CAMPAIGNS[0])).toMatchObject({ severity: "high", count: 3 });
    const fromIncident = parseCampaign(DEMO_INCIDENT);
    expect(fromIncident).toMatchObject({ id: DEMO_INCIDENT.incident_id, count: 3, severity: "high" });
    expect(fromIncident?.title.ar).toContain("بنك الصقر التجريبي");
    expect(parseCampaign({ title: { ar: "x" } })).toBeNull();
  });

  it("unwraps list envelopes", () => {
    expect(unwrapList([1, 2])).toEqual([1, 2]);
    expect(unwrapList({ items: [1] })).toEqual([1]);
    expect(unwrapList({ campaigns: [2] })).toEqual([2]);
    expect(unwrapList({ nope: 1 })).toEqual([]);
    expect(unwrapList(null)).toEqual([]);
  });
});
