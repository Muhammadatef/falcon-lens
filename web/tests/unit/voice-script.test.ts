import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  ARBITER_VERDICTS,
  CLIPS,
  SCRIPT,
  SCRIPT_KEYS,
  isFaqKey,
  arbiterClips,
  checkingClips,
  finalClips,
  foundClips,
  investigatorStartClips,
  investigatorStepClips,
  render,
  resultClips,
  scoreClips,
  sentinelClips,
  type InvestigatorStep,
} from "@/lib/voice-script";

const keys = new Set(SCRIPT_KEYS);
const known = (ids: readonly string[]) => ids.forEach((k) => expect(keys.has(k), k).toBe(true));
const wordCount = (s: string) => s.split(/\s+/).filter(Boolean).length;

describe("voice script", () => {
  it("clip ids are unique and both languages have identical key sets", () => {
    expect(new Set(CLIPS.map((c) => c.id)).size).toBe(CLIPS.length);
    expect(Object.keys(SCRIPT.ar_ae).sort()).toEqual(Object.keys(SCRIPT.en).sort());
    expect(CLIPS.length).toBe(SCRIPT_KEYS.length * 2);
    expect(CLIPS.some((c) => c.id === "ar_ae.found.3") && CLIPS.some((c) => c.id === "en.investigator.arbiter_result.dangerous")).toBe(true);
  });

  it("never says safe, never uses digits or placeholders, never asks for personal details or gives phone numbers", () => {
    for (const c of CLIPS) {
      expect(c.text.length, c.id).toBeGreaterThan(2);
      expect(c.text.toLowerCase(), c.id).not.toMatch(/\bsafe(ly|r|st)?\b|آمن/);
      expect(c.text, c.id).not.toMatch(/[0-9٠-٩{}]|undefined/);
      expect(c.text.toLowerCase(), c.id).not.toMatch(/password|iban|emirates id|رقم الهوية|كلمة السر/);
    }
  });

  it("every Arabic line is a short sentence (12 words at most) and not formal-only for key lines", () => {
    for (const c of CLIPS.filter((x) => x.lang === "ar_ae")) expect(wordCount(c.text), c.id).toBeLessThanOrEqual(isFaqKey(c.key) ? 22 : 12);
    expect(SCRIPT.ar_ae["wake.ack"]).toBe("هلا، سامعك.");
    expect(SCRIPT.ar_ae["found.1"]).toContain("مسج وحدة");
    expect(SCRIPT.ar_ae["found.2"]).toContain("مسجين");
    expect(SCRIPT.ar_ae["found.3"]).toContain("ثلاث مسجات");
  });

  it("found / checking / score / arbiter / step clips exist for every case", () => {
    for (let n = 1; n <= 10; n++) {
      known(foundClips(n));
      known(investigatorStartClips(n));
      for (let i = 1; i <= n; i++) known(checkingClips(i, n));
    }
    for (let s = 0; s <= 100; s++) known(scoreClips(s));
    for (const v of ARBITER_VERDICTS) known(v === "could_not_check" ? arbiterClips(null) : arbiterClips(v, 55));
    for (const v of ["dangerous", "suspicious", "no_warning_signs"] as const) known(resultClips(v, 7));
    for (const s of ["lists", "address", "page", "ai_second_look_local", "ai_second_look_cloud", "rules_only"] as InvestigatorStep[]) known(investigatorStepClips(s));
    for (let n = 0; n <= 10; n++) known(sentinelClips(n));
    expect(render("en", scoreClips(41))).toBe("The score is forty-one out of one hundred.");
    expect(render("ar_ae", scoreClips(41))).toBe("الدرجة واحد وأربعين من مية.");
  });

  it("every final utterance for every verdict mix, N = 1..10, is composable from known clips", () => {
    let mixes = 0;
    for (let total = 1; total <= 10; total++) {
      for (let dangerous = 0; dangerous <= total; dangerous++) {
        for (let suspicious = 0; dangerous + suspicious <= total; suspicious++) {
          for (let failed = 0; dangerous + suspicious + failed <= total; failed++) {
            const clear = total - dangerous - suspicious - failed;
            for (const sentinel of ["found", "watching"] as const) {
              const ids = finalClips({ total, dangerous, suspicious, clear, failed }, sentinel);
              known(ids);
              expect(ids.at(-1)).toBe(sentinel === "found" ? "final.both_agents" : "final.sentinel_watching");
              for (const lang of ["ar_ae", "en"] as const) {
                const text = render(lang, ids);
                expect(text.toLowerCase()).not.toMatch(/\bsafe\b|آمن/);
                expect(text).not.toMatch(/[0-9٠-٩{}]/);
              }
              if (dangerous === 0 && suspicious === 0) expect(ids).not.toContain("todo.report");
              expect(ids.some((k) => k.startsWith("sentinel.linked") || k === "sentinel.handover")).toBe(false); // those are said live, only when true
              mixes += 1;
            }
          }
        }
      }
    }
    expect(mixes).toBeGreaterThan(1000);
  });

  it("the generated yaml matches the script (run node scripts/gen-voice-script.mjs if this fails)", () => {
    const read = (f: string) => readFileSync(new URL(`../../../packages/falcon_core/src/falcon_core/i18n/${f}`, import.meta.url), "utf8");
    const core = read("voice_script.yaml");
    const faq = read("voice_faq.yaml");
    const list = (yaml: string) => [...yaml.matchAll(/^ {2}- \{id: ("[^"]+"), lang: \w+, text: (".*")\}$/gm)].map((m) => ({ id: JSON.parse(m[1]!) as string, text: JSON.parse(m[2]!) as string }));
    const isFaq = (c: { key: string }) => isFaqKey(c.key);
    expect(core).toContain(`clip_count: ${CLIPS.filter((c) => !isFaq(c)).length}`);
    expect(faq).toContain(`clip_count: ${CLIPS.filter(isFaq).length}`);
    expect(list(core)).toEqual(CLIPS.filter((c) => !isFaq(c)).map((c) => ({ id: c.id, text: c.text })));
    expect(list(faq)).toEqual(CLIPS.filter(isFaq).map((c) => ({ id: c.id, text: c.text })));
  });

  it("the review doc lists every Emirati line with an empty reviewer column", () => {
    const doc = readFileSync(new URL("../../../docs/VOICE_SCRIPT_REVIEW.md", import.meta.url), "utf8");
    for (const key of SCRIPT_KEYS) expect(doc, key).toContain(`| ${SCRIPT.ar_ae[key]} | ${SCRIPT.en[key]} |  |`);
  });
});
