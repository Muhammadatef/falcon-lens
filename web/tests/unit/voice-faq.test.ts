import { describe, expect, it } from "vitest";
import { parseVoiceReply } from "@/lib/voice";
import { ACK_KEY, FAQ, FAQ_KEYS, OFF_TOPIC, SCRIPT, offTopicKey, render } from "@/lib/voice-script";

const base = { transcript: "x", lang: "ar", wake: true, command: "x", duration_ms: 10, model: "m" };

describe("voice FAQ script", () => {
  it("has at least twenty scam-safety answers, with Arabic (Emirati) and English for every one", () => {
    expect(FAQ.length).toBeGreaterThanOrEqual(20);
    expect(new Set(FAQ.map(([n]) => n)).size).toBe(FAQ.length);
    for (const [name, ar, en] of FAQ) {
      expect(ar.length, name).toBeGreaterThan(10);
      expect(en.length, name).toBeGreaterThan(10);
      expect(SCRIPT.ar_ae[`faq.${name}`]).toBe(ar);
      expect(SCRIPT.en[`faq.${name}`]).toBe(en);
    }
    expect(Object.keys(SCRIPT.ar_ae).sort()).toEqual(Object.keys(SCRIPT.en).sort());
  });

  it("three rotating off-topic redirects per language, and the instant acknowledgement", () => {
    expect(OFF_TOPIC.length).toBe(3);
    expect([0, 1, 2, 3, 4, 5].map(offTopicKey)).toEqual(["offtopic.1", "offtopic.2", "offtopic.3", "offtopic.1", "offtopic.2", "offtopic.3"]);
    expect(offTopicKey(-1)).toBe("offtopic.3");
    expect(SCRIPT.ar_ae["offtopic.1"]).toContain("خارج شغلي");
    expect(SCRIPT.ar_ae[ACK_KEY]).toBe("لحظة…");
    expect(SCRIPT.en[ACK_KEY]).toBe("One moment…");
  });

  it("never says safe, never gives a phone number or a link, never asks for personal details", () => {
    const keys = [...FAQ_KEYS, "offtopic.1", "offtopic.2", "offtopic.3", ACK_KEY];
    for (const lang of ["ar_ae", "en"] as const) {
      for (const k of keys) {
        const t = render(lang, [k]);
        expect(t.toLowerCase(), k).not.toMatch(/\bsafe(ly|r|st)?\b|آمن|امان/);
        expect(t, k).not.toMatch(/[0-9٠-٩]|https?:|www\.|\.com|\.ae/i);
        expect(t.toLowerCase(), k).not.toMatch(/password|iban|emirates id|رقم الهوية|كلمة السر|\bplease (send|give|share)\b/);
      }
    }
  });

  it("the report answer is generic: official channels, no number or address", () => {
    expect(SCRIPT.en["faq.report"]).toContain("official channels");
    expect(SCRIPT.ar_ae["faq.report"]).toContain("القنوات الرسمية");
  });

  it("the data answer matches docs/PRIVACY.md: processed locally and deleted, only a fingerprint and the result are kept", () => {
    expect(SCRIPT.en["faq.data_stored"]).toMatch(/voice is processed on our own server and isn't kept/);
    expect(SCRIPT.en["faq.data_stored"]).toMatch(/defanged copy of the link, the evidence and the result/);
    expect(SCRIPT.en["faq.agents"]).not.toMatch(/nothing is sent/i);
    for (const l of ["ar_ae", "en"] as const) expect(SCRIPT[l]["offtopic.1"]).not.toMatch(/protect|أحميك/i);
  });
});

describe("voice reply parsing for the FAQ", () => {
  it("accepts a known answer id", () => {
    const r = parseVoiceReply({ ...base, intent: "faq", answer_id: "faq.otp" });
    expect(r?.intent).toBe("faq");
    expect(r?.answerId).toBe("faq.otp");
  });
  it("an unknown or missing answer id degrades to the redirect, never to invented speech", () => {
    expect(parseVoiceReply({ ...base, intent: "faq", answer_id: "faq.invented" })?.intent).toBe("off_topic");
    expect(parseVoiceReply({ ...base, intent: "faq", answer_id: null })?.intent).toBe("off_topic");
  });
  it("answer ids are ignored for every other intent", () => {
    expect(parseVoiceReply({ ...base, intent: "off_topic", answer_id: "faq.otp" })?.answerId).toBeNull();
    expect(parseVoiceReply({ ...base, intent: "none", answer_id: null })?.intent).toBe("none");
  });
});

describe("end-of-speech silence", () => {
  it("defaults to 800 ms; 650 is available through the setting; junk and out-of-range values fall back", async () => {
    const { vadSilenceMs, VOICE_LIMITS } = await import("@/lib/voice");
    expect(VOICE_LIMITS.silenceMs).toBe(800);
    expect(vadSilenceMs(undefined)).toBe(800);
    expect(vadSilenceMs("650")).toBe(650);
    for (const bad of ["", "abc", "100", "5000", "-1"]) expect(vadSilenceMs(bad)).toBe(800);
  });
});
