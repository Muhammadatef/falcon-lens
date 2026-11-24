import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseHuntAdmin, parseHuntItem, parsePublicHunt, toPublicHunt, unconfirmedCount } from "../../lib/hunt";
import { MESSAGES } from "../../lib/i18n";

const ROOT = join(__dirname, "..", "..");

const item = (patch: Record<string, unknown> = {}) => ({
  candidate_id: "hc_01JC8Z9Q3M5N7P2R4T6V8W0XYA",
  domain_defanged: "falcon-demo-bank-secure[.]test",
  brand_id: "falcon_demo_bank",
  brand_name: { ar: "بنك الصقر التجريبي", en: "Falcon Demo Bank" },
  discovery: "ct",
  permutation_kind: null,
  reasons: ["brand_token_in_cert", "cert_fresh"],
  first_seen: "2026-11-24T20:00:00Z",
  verdict: "dangerous",
  incident_id: null,
  found_before_report: true,
  time_to_detection_s: 120,
  time_to_detection_basis: "cert_not_before",
  source: "fixture",
  ...patch,
});

describe("hunt public projection", () => {
  it("keeps a confirmed, defanged row and drops extra fields", () => {
    const out = toPublicHunt({ items: [{ ...item(), prescore: 90, domain: "falcon-demo-bank-secure.test" }], counts: { confirmed: 1, new: 4, cleared: 2 } }, { hunt: { enabled: true, paused: false, sources: [{ id: "maps", kind: "maps", status: "ready_needs_key", terms_url: null }] } });
    expect(out.items).toHaveLength(1);
    const raw = JSON.stringify(out);
    expect(raw).not.toContain("prescore");
    expect(raw).not.toContain("falcon-demo-bank-secure.test");
    expect(out.sources).toEqual([{ id: "maps", kind: "maps", status: "ready_needs_key" }]);
    expect(unconfirmedCount(out.counts)).toBe(6);
  });

  it.each([
    ["live name", { domain_defanged: "falcon-demo-bank-secure.test" }],
    ["markup in domain", { domain_defanged: "<img src=x onerror=alert(1)>[.]test" }],
    ["markup in reasons", { reasons: ["<script>alert(1)</script>"] }],
    ["unconfirmed verdict", { verdict: "no_warning_signs" }],
    ["unknown source", { source: "synthetic" }],
    ["bad id", { candidate_id: "hc_x" }],
  ])("rejects %s", (_name, patch) => {
    expect(parseHuntItem(item(patch))).toBeNull();
  });

  it("time to detection needs its basis", () => {
    expect(parseHuntItem(item({ time_to_detection_basis: null }))?.ttdSeconds).toBeNull();
  });

  it("browser parse rejects non-objects and unknown statuses in counts", () => {
    expect(parsePublicHunt(null)).toBeNull();
    expect(parsePublicHunt({ items: [], counts: { bogus: 3, confirmed: -1 } })?.counts).toEqual({});
  });

  it("operator view parses and clamps prescore", () => {
    const a = parseHuntAdmin({
      enabled: true, paused: true, interval_min: 15, prescore_min: 60, quota: { per_hour: 20, per_day: 200 },
      last_cycle_at: "2026-11-24T20:10:00Z", last_cycle_outcome: "ok", sources: [], counts: { new: 1 },
      items: [{ candidate_id: "hc_01JC8Z9Q3M5N7P2R4T6V8W0XYB", domain_defanged: "falcon-demo-bank-pay[.]test", brand_id: "falcon_demo_bank", status: "new", prescore: 140, verdict: null, first_seen: "2026-11-24T20:00:00Z", provenance: { source: "fixture" } }],
    });
    expect(a?.items[0]?.prescore).toBe(100);
    expect(a?.paused).toBe(true);
  });
});

describe("hunt wording", () => {
  it("never says safe and has every key in both languages", () => {
    for (const lang of ["ar", "en"] as const) {
      const hunt = Object.entries(MESSAGES[lang]).filter(([k]) => k.startsWith("hunt."));
      expect(hunt.length).toBeGreaterThan(40);
      for (const [, v] of hunt) expect(v).not.toMatch(/\bsafe\b|آمن/i);
    }
    expect(MESSAGES.ar["hunt.status.ready_needs_key"]).toBe("جاهز، يحتاج مفتاح API");
    expect(MESSAGES.ar["hunt.before"]).toBe("رُصد قبل أي بلاغ");
    expect(MESSAGES.ar["hunt.confirmed"]).toBe("أكّده بصير");
  });

  it("feed component has no link, no 'safe' and no literal figures", () => {
    const src = readFileSync(join(ROOT, "components", "HuntFeed.tsx"), "utf8");
    expect(src).not.toMatch(/\bsafe\b|آمن/i);
    expect(src).not.toMatch(/<a[\s>]|href=/);
    const jsx = src.split("\n").filter((l) => /^\s*[<{].*>/.test(l));
    for (const line of jsx) expect(line).not.toMatch(/>\s*\d+\s*</);
  });
});
