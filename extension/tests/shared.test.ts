// Pure-function tests. Hosts are reserved test names; nothing is fetched.
import { describe, expect, it } from "vitest";
import { unwrap } from "../src/content";
import { signalText, t, verdictWord } from "../src/i18n";
import { isWebUrl, normaliseBase, permissionPattern, slimVerdict } from "../src/shared";

const ID = "vd_01JD3Z8Q4T6V8X0Z2B4D6F8H0K";
const base = {
  verdict_id: ID,
  verdict: "dangerous",
  risk_score: 94,
  final: true,
  degraded: false,
  reasons: [{ ar: "سبب", en: "reason", evidence_ids: ["ev_fixture0001"] }],
  actions: { now: { ar: ["أغلق الصفحة"], en: ["Close the page"] }, if_already_acted: { ar: [], en: [] }, report: { ar: "", en: "" } },
};

describe("slimVerdict treats the server response as untrusted", () => {
  it("keeps the contract fields the UI shows", () => {
    const v = slimVerdict({ ...base, source: "fixture", impersonated_brand: { brand_id: "falcon_demo_bank", name_ar: "بنك الصقر التجريبي", name_en: "Falcon Demo Bank", official_domains: ["falcon-demo-bank.test"] } });
    expect(v).toMatchObject({ verdict: "dangerous", risk_score: 94, final: true, source: "fixture" });
    expect(v?.brand?.domains).toEqual(["falcon-demo-bank.test"]);
    expect(v?.now.en).toEqual(["Close the page"]);
    expect(v?.caution).toEqual({ ar: [], en: [] });
  });

  it("rejects anything outside the verdict enum, including 'safe'", () => {
    for (const verdict of ["safe", "ok", "", null, 1]) expect(slimVerdict({ ...base, verdict })).toBeNull();
    expect(slimVerdict({ ...base, verdict_id: "vd_short" })).toBeNull();
    expect(slimVerdict(null)).toBeNull();
    expect(slimVerdict("dangerous")).toBeNull();
    expect(slimVerdict({ verdict_id: ID, events_url: "/x", status_url: "/y" })).toBeNull(); // Accepted shape
  });

  it("caps lengths and counts, and defaults carefully", () => {
    const long = "x".repeat(5000);
    const v = slimVerdict({ ...base, final: "yes", source: "made-up", risk_score: 900, reasons: Array.from({ length: 9 }, () => ({ ar: long, en: long })) });
    expect(v?.final).toBe(false); // only a literal true counts as final
    expect(v?.source).toBe("live");
    expect(v?.risk_score).toBe(100);
    expect(v?.reasons).toHaveLength(3);
    expect(v?.reasons[0]?.en).toHaveLength(220);
  });
});

describe("settings validation", () => {
  it("accepts https anywhere and http only for this computer", () => {
    expect(normaliseBase("https://api.falcon-lens.example/v1/")).toBe("https://api.falcon-lens.example");
    expect(normaliseBase("http://localhost:8080")).toBe("http://localhost:8080");
    expect(normaliseBase("http://127.0.0.1:8765/")).toBe("http://127.0.0.1:8765");
    for (const bad of ["http://api.falcon-lens.example", "ftp://localhost", "javascript:alert(1)", "https://user:pw@api.falcon-lens.example", "nope", ""]) {
      expect(normaliseBase(bad), bad).toBeNull();
    }
  });

  it("permission patterns carry no port", () => {
    expect(permissionPattern("http://127.0.0.1:8765")).toBe("http://127.0.0.1/*");
    expect(permissionPattern("https://api.falcon-lens.example")).toBe("https://api.falcon-lens.example/*");
  });

  it("only web URLs can be continued to", () => {
    expect(isWebUrl("https://falcon-demo-bank.test/")).toBe(true);
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "chrome://settings", "x", ""]) expect(isWebUrl(bad), bad).toBe(false);
  });
});

describe("mail link wrappers", () => {
  const wrappers = [{ suffix: "wrapper.test", path: "/go", param: "url" }];
  it("checks the address the link really leads to", () => {
    const inner = "http://falcon-demo-bank.secure-verify.example/login";
    expect(unwrap(`https://eu.wrapper.test/go?url=${encodeURIComponent(inner)}&data=1`, wrappers)).toBe(inner);
  });
  it("leaves other links, other paths and non-web targets alone", () => {
    expect(unwrap("https://heron-sample-shop.example/a?url=x", wrappers)).toBe("https://heron-sample-shop.example/a?url=x");
    expect(unwrap("https://wrapper.test/other?url=https%3A%2F%2Fa.example%2F", wrappers)).toBe("https://wrapper.test/other?url=https%3A%2F%2Fa.example%2F");
    const js = `https://wrapper.test/go?url=${encodeURIComponent("javascript:alert(1)")}`;
    expect(unwrap(js, wrappers)).toBe(js);
    expect(unwrap("not a url", wrappers)).toBe("");
  });
});

describe("strings", () => {
  it("has the three verdict words in both languages", () => {
    expect(verdictWord("no_warning_signs", "ar")).toBe("لم نجد علامات تحذير");
    expect(verdictWord("no_warning_signs", "en")).toBe("No warning signs found");
    expect(verdictWord("dangerous", "ar")).toBe("خطِر");
    expect(t("go_back", "en")).toBe("Go back");
  });
  it("names the brand as text in a signal sentence", () => {
    const brand = { id: "falcon_demo_bank", name_ar: "بنك الصقر التجريبي", name_en: "Falcon Demo Bank", domains: ["falcon-demo-bank.test"] };
    expect(signalText({ id: "brand_in_host", block: true }, brand, "en")).toContain("Falcon Demo Bank");
    expect(signalText({ id: "homograph", block: true }, brand, "ar")).toContain("بنك الصقر التجريبي");
  });
});
