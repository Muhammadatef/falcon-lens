import { describe, expect, it } from "vitest";
import { ARCH } from "@/lib/arch-content";
import { DOCS, DOC_SLUGS, isDocSlug, type DocPage } from "@/lib/docs-content";
import { DOC_MESSAGES } from "@/lib/i18n-docs";
import { fmtThreshold, parseProvenance, parseThresholds } from "@/lib/docs-data";

/** Every string a page holds, flattened. */
function strings(page: DocPage): string[] {
  const out = [page.lead, ...(page.callout ? [page.callout] : [])];
  for (const s of page.sections) {
    out.push(s.title, ...(s.body ?? []), ...(s.list ?? []));
    for (const c of s.cards ?? []) out.push(c.title, c.body);
    if (s.table) out.push(...s.table.cols, ...s.table.rows.flat());
  }
  return out;
}

/** Identifiers and protocol versions that legitimately hold digits. Everything else must be written in words. */
const ALLOWED_DIGIT_TOKENS = /\bT[0-3]\b|\bH[1-6]\b|\bADR-\d{3}\b|\bSHA-256\b|\bHMAC-SHA256\b|\bSTIX 2\.1\b|\bv1\b|الإصدار 1|\bRFC 9457\b|\b(?:401|429)\b|\bF1\b|\bV3\b|\bargon2id\b|\bFL_[A-Z_]+\b/g;

describe("docs content", () => {
  const langs = ["ar", "en"] as const;
  const pages = DOC_SLUGS.filter((s) => s !== "agents");

  it("has the eight slugs and rejects others", () => {
    expect(DOC_SLUGS).toHaveLength(8);
    expect(isDocSlug("cascade")).toBe(true);
    expect(isDocSlug("nope")).toBe(false);
    expect(isDocSlug("../etc")).toBe(false);
  });

  it("types a section for every page in both languages with the same section ids", () => {
    for (const slug of pages) {
      const ids = (l: "ar" | "en") => DOCS[l][slug as Exclude<typeof slug, "agents">].sections.map((s) => s.id);
      expect(ids("ar"), slug).toEqual(ids("en"));
      expect(ids("en").length, slug).toBeGreaterThan(2);
    }
  });

  it("types no numeric literal other than protocol versions and identifiers", () => {
    for (const lang of langs) {
      for (const slug of pages) {
        for (const text of strings(DOCS[lang][slug as Exclude<typeof slug, "agents">])) {
          const left = text.replace(ALLOWED_DIGIT_TOKENS, "").replace(/[A-Za-z0-9_.-]*\/[A-Za-z0-9_./{},* -]*/g, "");
          expect(left, `${lang}/${slug}: ${text.slice(0, 80)}`).not.toMatch(/\d/);
        }
      }
    }
  });

  it("never says safe / آمن and never claims a connection", () => {
    for (const lang of langs) {
      for (const slug of pages) {
        const all = strings(DOCS[lang][slug as Exclude<typeof slug, "agents">]).join("\n");
        expect(all.toLowerCase(), `${lang}/${slug}`).not.toMatch(/\bsafe(ly|r|st)?\b/);
        expect(all, `${lang}/${slug}`).not.toContain("آمن");
        expect(all, `${lang}/${slug}`).not.toMatch(/endorsed by|مؤيَّد من|integrated with abu dhabi/i);
      }
    }
  });

  it("the agent-pattern copy (moved from /architecture/agents) never says safe either", () => {
    for (const lang of langs) {
      const all = JSON.stringify(ARCH[lang]);
      expect(all.toLowerCase(), lang).not.toMatch(/\bsafe(ly|r|st)?\b/);
      expect(all, lang).not.toContain("آمن");
    }
  });

  it("integration says ready to connect, not connected, in both languages", () => {
    expect(DOCS.en.integration.callout).toContain("Ready to connect. Not connected.");
    expect(DOCS.ar.integration.callout).toContain("جاهز للربط، وغير مربوط");
    expect(DOCS.en.integration.lead).toContain("Ready to connect, not connected");
    expect(DOCS.ar.integration.lead).toContain("جاهز للربط، وغير مربوط");
  });

  it("the cascade page restates the four tiers and only T3 carries a capability badge", () => {
    for (const lang of langs) {
      const tiers = DOCS[lang].cascade.sections.find((s) => s.id === "tiers")!.cards!;
      expect(tiers.map((c) => c.tag)).toEqual(["T0", "T1", "T2", "T3"]);
      expect(tiers.map((c) => c.cap ?? null)).toEqual([null, null, null, "investigator"]);
    }
  });

  it("every string key exists in both languages for the v2 strings, with no safe / percent literal", () => {
    expect(Object.keys(DOC_MESSAGES.ar).sort()).toEqual(Object.keys(DOC_MESSAGES.en).sort());
    for (const lang of langs) {
      for (const [key, value] of Object.entries(DOC_MESSAGES[lang])) {
        expect(value, `${lang} ${key}`).not.toMatch(/\bsafe(ly|r|st)?\b|آمن|\d\s*%/i);
        expect(value.trim(), `${lang} ${key}`).not.toBe("");
      }
    }
  });
});

describe("docs data comes only from the artifact", () => {
  const fixture = (thresholds: unknown) => ({ available: true, artifact: "20990101T000000Z.json", data: { created_at: "2099-01-01T00:00:00Z", dataset_hash: "abc", git_sha: "def", scope: "a scope", thresholds } });

  it("returns null when unavailable or when a required field is missing", () => {
    expect(parseThresholds({ available: false })).toBeNull();
    expect(parseThresholds(null)).toBeNull();
    expect(parseThresholds(fixture({ tau_low: 0.1 }))).toBeNull();
    expect(parseProvenance({ available: false })).toBeNull();
  });

  it("echoes a second, different fixture (nothing is typed)", () => {
    const t = parseThresholds(fixture({ tau_low: 0.1234, tau_high: 0.9, eps_low: 0.01, eps_high: 0.5, fit_source: "elsewhere" }))!;
    expect(t).toEqual({ tauLow: 0.1234, tauHigh: 0.9, epsLow: 0.01, epsHigh: 0.5, fitSource: "elsewhere" });
    expect(fmtThreshold(t.tauLow)).toBe("0.1234");
    expect(parseProvenance(fixture({}))).toMatchObject({ artifact: "20990101T000000Z.json", gitSha: "def", scope: "a scope" });
  });
});
