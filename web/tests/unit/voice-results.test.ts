import { describe, expect, it } from "vitest";
import { SCRIPT, SFX_KEYS, clipId, isSfx, messageResultKeys, render } from "@/lib/voice-script";

describe("spoken per-message result", () => {
  it("is earcon, ordinal and verdict line for every message and every verdict, in both languages", () => {
    for (let n = 1; n <= 10; n++) {
      for (const v of ["dangerous", "suspicious", "no_warning_signs", null] as const) {
        const keys = messageResultKeys(n, v);
        expect(keys.filter((k) => !isSfx(k))).toEqual([`msg.ord.${n}`, `msg.verdict.${v ?? "could_not_check"}`]);
        expect(keys.length).toBe(v === null ? 2 : 3);
        for (const lang of ["ar_ae", "en"] as const) {
          const text = render(lang, keys);
          expect(text).not.toMatch(/\bsafe\b|آمن|[0-9٠-٩]/i);
        }
      }
    }
  });
  it("the earcon matches the verdict and is dropped from the caption text", () => {
    expect(messageResultKeys(1, "dangerous")[0]).toBe("sfx.dangerous");
    expect(messageResultKeys(2, "suspicious")[0]).toBe("sfx.suspicious");
    expect(messageResultKeys(3, "no_warning_signs")[0]).toBe("sfx.clear");
    expect(render("en", messageResultKeys(1, "dangerous"))).toBe("Message one: dangerous. Don't tap the link or share any details.");
    expect(render("ar_ae", messageResultKeys(1, "dangerous"))).toBe("المسج الأول: خطِر. لا تضغط الرابط ولا تعطي أي بيانات.");
    expect(render("ar_ae", messageResultKeys(3, "no_warning_signs"))).toBe("المسج الثالث: ما لقينا علامات تحذير، بس خلّك منتبه.");
  });
  it("earcon ids are language-neutral", () => {
    expect([...SFX_KEYS].every((k) => clipId("ar_ae", k) === k && clipId("en", k) === k)).toBe(true);
    expect(SCRIPT.en["sfx.clear"]).toBeUndefined();
  });
});
