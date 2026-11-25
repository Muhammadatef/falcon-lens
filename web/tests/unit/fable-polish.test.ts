import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { NODE_TEXT } from "@/lib/i18n-arch";
import { DOCS, DOC_SLUGS } from "@/lib/docs-content";
import { publicSeverityLine } from "@/lib/public-history";
import { VOICE_DOC } from "@/lib/voice-doc";

/** Design audit of 24 Nov: copy that must stay true to the shipped code. */
describe("design polish: truthful copy", () => {
  const langs = ["ar", "en"] as const;

  it("voice docs describe the FAQ fallback: rules first, a local embedding model, no generative answer", () => {
    for (const lang of langs) {
      const intent = VOICE_DOC[lang].steps.find((s) => s.tag === "INTENT")!;
      const text = [intent.title, intent.body, ...VOICE_DOC[lang].limits].join(" ");
      expect(text).not.toMatch(/not a model|لا نموذج،/);
      expect(text).toMatch(lang === "ar" ? /نموذج تضمين محلي/ : /local embedding model/);
      expect(text).toMatch(lang === "ar" ? /نموذج توليدي/ : /No generative model/);
    }
    // Same number of steps and limits in both languages.
    expect(VOICE_DOC.ar.steps.map((s) => s.tag)).toEqual(VOICE_DOC.en.steps.map((s) => s.tag));
    expect(VOICE_DOC.ar.limits).toHaveLength(VOICE_DOC.en.limits.length);
  });

  it("the interactive architecture no longer says the voice intent involves no model", () => {
    for (const lang of langs) {
      const all = JSON.stringify(NODE_TEXT[lang].voice_intent);
      expect(all).not.toMatch(/No model is involved|دون أي نموذج\. ثم يمرّ/);
    }
  });

  it("sovereign mode is described as no content to a cloud model, never as nothing leaving the machine", () => {
    const sources = ["lib/docs-content.ts", "lib/page-content.ts"].map((f) => readFileSync(join(__dirname, "../..", f), "utf8")).join("\n");
    expect(sources).not.toMatch(/so no content leaves the machine|فلا يغادر أي محتوى الجهاز/);
    for (const lang of langs) {
      const text = DOC_SLUGS.filter((s): s is Exclude<typeof s, "agents" | "building-agents"> => s !== "agents" && s !== "building-agents").map((s) => JSON.stringify(DOCS[lang][s])).join(" ");
      expect(text).toMatch(lang === "ar" ? /إلى نموذج سحابي/ : /sent to a cloud model/);
    }
  });

  it("the dangerous verdict is always written «خطِر», never «خطير»", () => {
    expect(publicSeverityLine(["R4"], 0, 0).ar).toContain("«خطِر»");
    expect(publicSeverityLine(["R4"], 0, 0).ar).not.toContain("خطير");
  });

  it("the architecture diagram is identical in docs/ and in the web app", () => {
    const repo = join(__dirname, "../../..");
    const docs = readFileSync(join(repo, "docs/assets/architecture.svg"), "utf8");
    expect(readFileSync(join(repo, "web/public/images/architecture.svg"), "utf8")).toBe(docs);
    expect(docs).not.toContain("fixed rules, no model");
  });
});
