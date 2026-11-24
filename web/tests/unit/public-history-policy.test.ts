import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { REMOVED_TEXT, REMOVED_TEXT_AR, scrub, scrubAr, toPublicCheck } from "@/lib/public-history";

const I18N = resolve(__dirname, "../../../packages/falcon_core/src/falcon_core/i18n");
/** Every quoted template string in the file (reasons, hard rules, actions, caution, report). */
const templates = (lang: "ar" | "en"): string[] =>
  readFileSync(resolve(I18N, `${lang}.yaml`), "utf8")
    .split("\n")
    .map((l) => /^\s*(?:-|[\w.]+:)\s+"(.+)"\s*$/.exec(l)?.[1])
    .filter((x): x is string => Boolean(x));

describe("public text policy: allow-list, fail closed", () => {
  const BAD = [
    "https:\\\\evil.test\\reset\\TOKEN",
    "evil.test\\reset\\TOKEN",
    "evil。test/TOKEN",
    "evil[dot]test/TOKEN",
    "evil.test∕reset∕TOKEN",
    "data:text/html;base64,PHNjcmlwdD4=",
    "evil.test⁄reset",
    "a＼b",
    "100% sure",
    "zero​width",
    "key=value",
    "a_b",
    "<b>x</b>",
  ];
  for (const text of BAD) {
    it(`replaces the whole string: ${JSON.stringify(text)}`, () => {
      expect(scrub(`see ${text} now`)).toBe(REMOVED_TEXT);
      expect(scrubAr(`انظر ${text}`)).toBe(REMOVED_TEXT_AR);
    });
  }

  it("removes OTP, PIN and account numbers (ASCII and Arabic-Indic)", () => {
    expect(scrub("code 1234 now")).toBe("code [number removed] now");
    expect(scrubAr("الرمز ٤٥٦٧٨ الآن")).toBe("الرمز [number removed] الآن");
    expect(scrub("pin 12 34 56")).toBe("pin [number removed]");
    expect(scrub("card 1234-5678-9012")).toBe("card [number removed]");
  });

  it("removes long letter-digit tokens", () => {
    expect(scrub("token abcdef1234567890abcdef12 here")).toBe("token [number removed] here");
  });

  it("keeps short numbers and ordinary punctuation", () => {
    expect(scrub("Registered 3 days ago (v2). Really? Yes: «ok» - fine")).toBe("Registered 3 days ago (v2). Really? Yes: «ok» - fine");
  });

  it("is idempotent on its own output", () => {
    for (const t of ["see https://u:p@a.example.test:8443/x?y#z or 1234", "اضغط https://evil.example.test/x"]) {
      const once = scrub(t);
      expect(scrub(once)).toBe(once);
    }
  });

  for (const lang of ["ar", "en"] as const) {
    it(`every real ${lang} template string survives unchanged`, () => {
      const list = templates(lang).filter((x) => x !== lang);
      expect(list.length).toBeGreaterThanOrEqual(40);
      const changed = list.filter((t) => scrub(t, 1000) !== t);
      // Known, reported (not silently widened): en `email.auth_fail` writes "SPF/DKIM/DMARC" and "/" is not allowed.
      const known = lang === "en" ? ["The email failed sender checks (SPF/DKIM/DMARC)."] : [];
      expect(changed, `templates altered by the policy: ${JSON.stringify(changed)}`).toEqual(known);
      console.info(`${lang}: ${list.length - changed.length}/${list.length} real template strings survive unchanged`);
    });
  }

  it("the policy runs on every free-text field of a check projection", () => {
    const out = toPublicCheck({
      verdict_id: "vd_01HZX3K9Q2M4N5P6R7S8T9V0WX",
      input_type: "message",
      verdict: "dangerous",
      risk_score: 90,
      tier_reached: "T1",
      final: true,
      impersonated_brand: { brand_id: "b", name_ar: "بنك/", name_en: "Bank=" },
      evidence: [{ id: "ev_1", tier: "T0", signal: "a", display: { ar: "رمز 1234", en: "evil.test\\x" } }],
      reasons: [{ ar: "سبب%", en: "reason 99999", evidence_ids: ["ev_1"] }],
    })!;
    const text = JSON.stringify(out);
    expect(text).not.toMatch(/1234|99999|evil|%|=/);
    expect(text).toContain(REMOVED_TEXT);
    expect(text).toContain(REMOVED_TEXT_AR);
  });
});
