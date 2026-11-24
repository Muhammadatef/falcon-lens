import { describe, expect, it } from "vitest";
import { DEMO_DANGEROUS, DEMO_NWS } from "@/lib/demo";
import { VOICE_MESSAGES } from "@/lib/i18n-voice";
import { permissionsPolicy } from "../../proxy";
import { sentences } from "@/lib/speech";
import { buildSpeech, buildSummary, countOutcomes, parseVoiceReply, sharedBrandCampaign, speechLang, splitMessages, topAction, type Outcome } from "@/lib/voice";

const d = (id: string, brand = "falcon_demo_bank"): Outcome => ({ id, verdict: { ...DEMO_DANGEROUS, impersonated_brand: DEMO_DANGEROUS.impersonated_brand ? { ...DEMO_DANGEROUS.impersonated_brand, brand_id: brand } : null } });
const s = (id: string): Outcome => ({ id, verdict: { ...DEMO_DANGEROUS, verdict: "suspicious", impersonated_brand: null } });
const c = (id: string): Outcome => ({ id, verdict: DEMO_NWS });
const f = (): Outcome => ({ id: null, verdict: null });

const texts = (raw: string) => splitMessages(raw).items.map((i) => i.text);

describe("clipboard splitter (realistic multi-message clipboards)", () => {
  it("1. Arabic messages separated by blank lines", () => {
    const raw = "عزيزي العميل، تم إيقاف حسابك. حدّث بياناتك الآن عبر https://falcon-demo-bank-secure.test/login\n\nشحنتك متوقفة في الجمارك، ادفع رسوم 12 درهم هنا: http://parcel-fee.example/pay\n\nمرحباً، موعدك غداً الساعة العاشرة صباحاً.";
    const items = splitMessages(raw).items;
    expect(items).toHaveLength(3);
    expect(items[0]!.text).toContain("falcon-demo-bank-secure.test");
    expect(items[2]!.text).toBe("مرحباً، موعدك غداً الساعة العاشرة صباحاً.");
  });
  it("2. English messages separated by blank lines (with extra blank lines and spaces)", () => {
    const raw = "Your package is on hold. Pay the fee: http://parcel-fee.example/pay\n\n\n   \nURGENT: your account will be closed today, verify at https://acct-verify.example/\n\nHi, dinner at 8?";
    expect(texts(raw)).toHaveLength(3);
  });
  it("3. numbered list, English", () => {
    const raw = "1. Your bank card is blocked, call us or visit http://card-unblock.example\n2. You won a prize! Claim at www.prize-claim.example\n3) Meeting moved to Tuesday";
    const t = texts(raw);
    expect(t).toHaveLength(3);
    expect(t[0]!.startsWith("Your bank card")).toBe(true);
    expect(t[2]).toBe("Meeting moved to Tuesday");
  });
  it("4. Arabic-Indic numbering", () => {
    const raw = "١- تم تعليق بطاقتك، اضغط هنا http://card-hold.example\n٢- لديك طرد جديد: https://track-parcel.example/x\n٣- كل عام وأنتم بخير";
    expect(texts(raw)).toHaveLength(3);
  });
  it("5. bulleted lines", () => {
    const raw = "• Click to claim your refund http://refund-now.example\n• Your OTP is 4821, do not share it\n- Delivery tomorrow";
    expect(texts(raw)).toHaveLength(3);
  });
  it("6. no blank lines: each URL-bearing line closes one message (text before a link belongs to it)", () => {
    const raw = "Your parcel is held\nhttp://parcel-held.example/a\nAccount suspended, act now\nhttps://acct-suspend.example/b\nhttp://third-link.example/c";
    const items = splitMessages(raw).items;
    expect(items).toHaveLength(3);
    expect(items[0]!.text).toContain("Your parcel is held");
    expect(items[2]!.kind).toBe("url");
  });
  it("7. one message with a link on a line of its own stays one message", () => {
    expect(texts("Dear customer, your account needs review.\nhttps://account-review.example/login")).toHaveLength(1);
  });
  it("8. one message with two links on one line stays one message", () => {
    expect(texts("Pay at http://a-pay.example or http://b-pay.example today")).toHaveLength(1);
  });
  it("9. a lone link becomes a link check, refanged for submission", () => {
    const items = splitMessages("hxxps://falcon-demo-bank-secure[.]test/login").items;
    expect(items).toEqual([{ kind: "url", text: "https://falcon-demo-bank-secure.test/login" }]);
  });
  it("10. more than ten messages are capped at ten and flagged", () => {
    const raw = Array.from({ length: 14 }, (_, i) => `Message number ${i + 1}: click http://scam-${i}.example/x`).join("\n\n");
    const r = splitMessages(raw);
    expect(r.items).toHaveLength(10);
    expect(r.truncated).toBe(true);
  });
  it("11. duplicates are checked once; CRLF clipboards work", () => {
    const raw = "Win a prize http://prize.example\r\n\r\nWin a prize http://prize.example\r\n\r\nSecond one http://second.example";
    expect(texts(raw)).toHaveLength(2);
  });
  it("12. empty, whitespace and control characters give nothing", () => {
    expect(splitMessages("").items).toEqual([]);
    expect(splitMessages("  \n\n \t ").items).toEqual([]);
    expect(splitMessages("\u0000\u0001").items).toEqual([]);
  });
  it("13. a numbered list inside blank-line blocks still splits per marker", () => {
    const raw = "From my phone:\n\n1. First scam http://one.example\n2. Second scam http://two.example";
    expect(texts(raw)).toHaveLength(3);
  });
  it("14. defanged links in text are kept as text", () => {
    const items = splitMessages("Verify now hxxp://bank-verify[.]example/login\n\nSecond hxxp://other[.]example").items;
    expect(items).toHaveLength(2);
    expect(items[0]!.kind).toBe("message");
  });
  it("15. oversized items are clipped under the API message limit", () => {
    const [item] = splitMessages("ا".repeat(9000)).items;
    expect(new TextEncoder().encode(item!.text).length).toBeLessThan(8 * 1024);
  });
});

describe("spoken summary", () => {
  it("matches the owner's example in Arabic and English (3 messages: 2 dangerous, 1 no warning signs)", () => {
    const counts = countOutcomes([d("a"), d("b"), c("c")]);
    expect(counts).toEqual({ total: 3, dangerous: 2, suspicious: 0, clear: 1, failed: 0 });
    expect(buildSummary("ar", counts)).toBe("فحصت ثلاث رسائل. اثنتان منها خطِرة: لا تضغط على الروابط ولا ترسل أي رمز. واحدة منها لم نجد فيها علامات تحذير، ومع ذلك كن حذراً.");
    expect(buildSummary("en", counts)).toBe("I checked three messages. Two are dangerous: don't tap the links and never share a code. One showed no warning signs, but stay careful.");
  });
  it("handles one message, none, and failed checks", () => {
    expect(buildSummary("en", countOutcomes([d("a")]))).toBe("I checked one message. It is dangerous. Don't tap the link and never share a code.");
    expect(buildSummary("ar", countOutcomes([c("a")]))).toContain("رسالة واحدة");
    expect(buildSummary("en", countOutcomes([]))).toBe("I found no messages to check.");
    expect(buildSummary("en", countOutcomes([d("a"), f()]))).toContain("One could not be checked");
    expect(buildSummary("ar", countOutcomes([f()]))).toContain("تعذّر فحصها");
  });
  it("never says safe, never uses digits, never asks for personal details, for every mix up to ten", () => {
    for (let total = 0; total <= 10; total++) {
      for (let dang = 0; dang <= total; dang++) {
        for (let sus = 0; dang + sus <= total; sus++) {
          for (let fail = 0; dang + sus + fail <= total; fail++) {
            const outcomes = [...Array.from({ length: dang }, () => d("x")), ...Array.from({ length: sus }, () => s("y")), ...Array.from({ length: fail }, f), ...Array.from({ length: total - dang - sus - fail }, () => c("z"))];
            for (const lang of ["ar", "en"] as const) {
              const text = buildSpeech(lang, outcomes);
              expect(text.toLowerCase(), `${lang} ${total}/${dang}/${sus}/${fail}`).not.toMatch(/\bsafe(ly|r|st)?\b|آمن/);
              expect(text, `${lang} ${total}/${dang}/${sus}/${fail}`).not.toMatch(/[0-9٠-٩]/);
              expect(text).not.toMatch(/\{|\}|undefined/);
            }
          }
        }
      }
    }
  });
  it("reads the most severe verdict's first 'do now' line after the summary, in the spoken language", () => {
    const out = [c("a"), d("b")];
    expect(topAction("en", out)).toBe(DEMO_DANGEROUS.actions.now.en[0]);
    expect(topAction("ar", out)).toBe(DEMO_DANGEROUS.actions.now.ar[0]);
    expect(buildSpeech("ar", out).endsWith(DEMO_DANGEROUS.actions.now.ar[0]!)).toBe(true);
    expect(topAction("en", [f()])).toBe("");
  });
  it("every voice string exists in both languages, is non-empty and never says safe", () => {
    expect(Object.keys(VOICE_MESSAGES.ar).sort()).toEqual(Object.keys(VOICE_MESSAGES.en).sort());
    for (const lang of ["ar", "en"] as const) {
      for (const [key, value] of Object.entries(VOICE_MESSAGES[lang])) {
        expect(value.length, key).toBeGreaterThan(2);
        expect(value.toLowerCase(), key).not.toMatch(/\bsafe(ly|r|st)?\b|آمن/);
      }
    }
  });
  it("sentences() splits for the speech engine without losing text", () => {
    const t = buildSpeech("ar", [d("a"), d("b"), c("c")]);
    expect(sentences(t).join(" ")).toBe(t);
    expect(sentences(t).length).toBeGreaterThan(2);
  });
});

describe("campaign line only when the data says so", () => {
  it("needs two dangerous verdicts naming the same brand", () => {
    expect(sharedBrandCampaign([d("a"), d("b")])).toBe(true);
    expect(sharedBrandCampaign([d("a"), d("b", "other_brand")])).toBe(false);
    expect(sharedBrandCampaign([d("a"), s("b"), c("c")])).toBe(false);
    expect(sharedBrandCampaign([d("a"), f()])).toBe(false);
  });
});

describe("voice reply parsing and policy", () => {
  it("accepts the contract and collapses unknown values", () => {
    expect(parseVoiceReply({ transcript: "x", lang: "ar", wake: true, intent: "check_clipboard", command: "c", duration_ms: 10, model: "m" })).toMatchObject({ wake: true, intent: "check_clipboard", lang: "ar" });
    expect(parseVoiceReply({ wake: true, intent: "rm -rf", lang: "fr" })).toMatchObject({ intent: "none", lang: "other" });
    expect(parseVoiceReply({ intent: "help" })).toBeNull();
    expect(parseVoiceReply(null)).toBeNull();
    expect(speechLang("other", "ar")).toBe("ar");
    expect(speechLang("en", "ar")).toBe("en");
  });
  it("the microphone is allowed on /voice only", () => {
    expect(permissionsPolicy("/voice")).toContain("microphone=(self)");
    expect(permissionsPolicy("/")).toContain("microphone=()");
    expect(permissionsPolicy("/history")).toContain("microphone=()");
  });
});
