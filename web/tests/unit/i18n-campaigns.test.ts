import { describe, expect, it } from "vitest";
import { CX_MESSAGES } from "@/lib/i18n-campaigns";

describe("campaign explainer strings", () => {
  it("AR and EN have the same keys", () => {
    expect(Object.keys(CX_MESSAGES.ar).sort()).toEqual(Object.keys(CX_MESSAGES.en).sort());
  });
  it("no empty strings, no digits, never 'safe'", () => {
    for (const lang of ["ar", "en"] as const)
      for (const [k, v] of Object.entries(CX_MESSAGES[lang])) {
        expect(v.trim(), k).not.toBe("");
        expect(v, k).not.toMatch(/\d/);
        expect(v.toLowerCase(), k).not.toMatch(/\bsafe\b|آمن/);
      }
  });
  it("Arabic strings contain Arabic text", () => {
    for (const [k, v] of Object.entries(CX_MESSAGES.ar)) expect(v, k).toMatch(/[؀-ۿ]/);
  });
});
