import { describe, expect, it } from "vitest";
import { ARCH } from "@/lib/arch-content";
import { DOCS } from "@/lib/docs-content";
import { MESSAGES } from "@/lib/i18n";
import { DOC_MESSAGES } from "@/lib/i18n-docs";
import { AUTH, PRIVACY } from "@/lib/page-content";

/**
 * "In seconds" is a speed claim. The evaluation artifact holds no latency metric, so user-facing copy must not
 * state one (CLAUDE.md truthfulness: every figure comes from a generated artifact). The only places a time unit may
 * appear are code-level limits that are labelled as budgets, a Retry-After value the API sent, and the phrase
 * "second look" (the AI second look).
 */
const SPEED = /\bseconds\b|\b(?:one|every) second|per second\b|ثوانٍ|ثواني|ثوان\b|\d+\s*ثانية|ثانية واحدة/i;
const EXEMPT = /budget|ميزانية|الميزانية|\{n\}|second look|نظرة ثانية|\{latency_s\}/i;

function collect(): { where: string; text: string }[] {
  const out: { where: string; text: string }[] = [];
  const walk = (where: string, v: unknown) => {
    if (typeof v === "string") out.push({ where, text: v });
    else if (Array.isArray(v)) v.forEach((x, i) => walk(`${where}[${i}]`, x));
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(`${where}.${k}`, x);
  };
  for (const lang of ["ar", "en"] as const) {
    walk(`i18n.${lang}`, MESSAGES[lang]);
    walk(`i18n-docs.${lang}`, DOC_MESSAGES[lang]);
    walk(`arch.${lang}`, ARCH[lang]);
    walk(`docs.${lang}`, DOCS[lang]);
    walk(`auth.${lang}`, AUTH[lang]);
    walk(`privacy.${lang}`, PRIVACY[lang]);
  }
  return out;
}

describe("no unsourced speed claims in user-facing copy", () => {
  it("scans a meaningful amount of copy", () => {
    expect(collect().length).toBeGreaterThan(500);
  });

  it("never says 'in seconds' / «في ثوانٍ» (or any time unit) outside labelled budgets and API-sourced values", () => {
    const hits = collect().filter(({ text }) => SPEED.test(text) && !EXEMPT.test(text)).map(({ where, text }) => `${where}: ${text.slice(0, 100)}`);
    expect(hits).toEqual([]);
  });

  it("the specific claims removed in review stay removed", () => {
    for (const lang of ["ar", "en"] as const) {
      const all = JSON.stringify(MESSAGES[lang]) + JSON.stringify(ARCH[lang]);
      expect(all, lang).not.toMatch(/in seconds|seconds-long|في ثوانٍ|خلال ثوانٍ|بالثواني/);
    }
  });
});
