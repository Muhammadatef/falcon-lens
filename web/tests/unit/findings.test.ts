import { describe, expect, it } from "vitest";
import type { Evidence } from "@/lib/contracts";
import { FINDING_LINES, findingLine, safeHost, tierFindingLines } from "@/lib/findings";
import { SPOKEN_CODES } from "@/lib/voice-script";

const ev = (signal: string, tier: Evidence["tier"], weight: number, observed: unknown = true, extra: Partial<Evidence> = {}): Evidence => ({
  id: `ev_${signal.replace(/[^a-z]/g, "").slice(0, 12).padEnd(8, "x")}`,
  signal,
  family: signal.split(".")[0]!,
  observed,
  weight,
  polarity: weight > 0 ? "risk" : "neutral",
  source: "computed",
  tier,
  ...extra,
});

describe("written findings mirror the spoken ones", () => {
  it("every code that is spoken also has a written line", () => {
    for (const code of SPOKEN_CODES) expect(FINDING_LINES[code], code).toBeDefined();
  });
});

describe("four input types give four different step lists from their own evidence", () => {
  const link = [ev("url.combosquat", "T1", 2, { brand_id: "falcon_demo_bank" }), ev("domain.age_days", "T1", 2.5, 2), ev("domain.cert_age_days", "T1", 1, 1), ev("page.cross_origin_post", "T2", 3, "hxxps://collector[.]invalid/hook"), ev("brand.claimed_not_owned", "T2", 3, { brand_id: "falcon_demo_bank" })];
  const sms = [ev("message.rule.delivery_fee", "T1", 1.4), ev("message.rule.urgency", "T1", 0.9), ev("message.contains_url", "T1", 0, { count: 1, urls: ["hxxp://parcel-fee[.]test/pay"] }), ev("message.contains_phone", "T1", 0, { numbers: 1 })];
  const mail = [ev("email.auth_fail", "T1", 2, { failures: ["spf", "dmarc", "<b>x</b>"] }), ev("email.display_name_impersonation", "T1", 2, { brands: ["falcon_demo_bank"], sender_domain: "mail[.]test" }), ev("email.reply_to_mismatch", "T1", 1, { from_domain: "a[.]test", reply_to_domain: "other[.]test" }), ev("email.attachment", "T1", 0.5, {})];
  const qr = [ev("image.qr_decoded", "T0", 0, { qr_count: 1, urls: ["hxxps://poster-pay[.]test/x?y=1"] }), ev("url.free_host_or_tunnel", "T1", 1.2), ev("url.shortener", "T1", 0.4)];

  it("each list matches its own evidence, with values", () => {
    expect(tierFindingLines(link, "T1", "en", "falcon_demo_bank")).toEqual([
      "The domain was registered 2 days ago",
      "The address adds a word to the name of Falcon Demo Bank",
      "The site certificate was issued 1 day ago",
    ]);
    expect(tierFindingLines(link, "T2", "ar")).toEqual([expect.stringContaining("خادم آخر"), "تدّعي أنها بنك الصقر التجريبي والنطاق ليس من نطاقاتها الرسمية"]);
    expect(tierFindingLines(sms, "T1", "en")).toEqual(["The message asks for a delivery fee", "The message rushes you", expect.stringContaining("parcel-fee[.]test")]);
    expect(tierFindingLines(mail, "T1", "en")).toEqual([expect.stringContaining("SPF / DMARC"), expect.stringContaining("Falcon Demo Bank"), expect.stringContaining("other[.]test")]);
    expect(tierFindingLines(qr, "T0", "en")).toEqual([expect.stringContaining("poster-pay[.]test")]);
  });

  it("the four lists differ and none leaks markup", () => {
    const all = [link, sms, mail, qr].map((x) => (["T0", "T1", "T2"] as const).flatMap((t) => tierFindingLines(x, t, "ar")).join("|"));
    expect(new Set(all).size).toBe(4);
    for (const s of all) expect(s).not.toMatch(/<|>|javascript:/i);
  });

  it("unknown codes, trust items and errored signals print nothing; a host is reduced to host characters", () => {
    expect(findingLine(ev("evil.code<script>", "T1", 9), "en")).toBeNull();
    expect(findingLine(ev("url.combosquat", "T1", -2, true, { polarity: "trust" }), "en")).toBeNull();
    expect(findingLine(ev("url.combosquat", "T1", 2, true, { error: "timeout" }), "en")).toBeNull();
    expect(safeHost("hxxps://a[.]test/<img onerror=x>")).toBe("a[.]test");
    expect(safeHost("javascript:alert(1)")).not.toContain("(");
  });
});
