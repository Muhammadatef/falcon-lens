import { describe, expect, it } from "vitest";
import { binaryLabel, couldNotCheck, csvCell, parseBatchInput, resultFromVerdict, toCsv } from "@/lib/batch";

describe("batch input", () => {
  it("reads one URL per line, skipping blanks, comments and duplicates", () => {
    expect(parseBatchInput("# c\n\nhttp://a.test/\n http://b.test/ \nhttp://a.test/\n")).toEqual(["http://a.test/", "http://b.test/"]);
  });
  it("reads a CSV with a url column, quoted cells included", () => {
    expect(parseBatchInput('id,URL,label\n1,"http://a.test/?x=1,2",fraud\n2,http://b.test/,legit\n')).toEqual(["http://a.test/?x=1,2", "http://b.test/"]);
  });
});

describe("binary mapping", () => {
  it("strict treats suspicious and could_not_check as fraud, lenient does not", () => {
    expect(binaryLabel("dangerous", "strict")).toBe("fraud");
    expect(binaryLabel("suspicious", "strict")).toBe("fraud");
    expect(binaryLabel("could_not_check", "strict")).toBe("fraud");
    expect(binaryLabel("suspicious", "lenient")).toBe("legit");
    expect(binaryLabel("could_not_check", "lenient")).toBe("legit");
    expect(binaryLabel("no_warning_signs", "strict")).toBe("legit");
  });
});

describe("csv output", () => {
  it("neutralises spreadsheet formulas and quotes commas", () => {
    expect(csvCell("=HYPERLINK(1)")).toBe("'=HYPERLINK(1)");
    expect(csvCell("a,b")).toBe('"a,b"');
  });
  it("maps a verdict to a row with top reason codes", () => {
    const r = resultFromVerdict(
      { verdict: "suspicious", verdict_id: "vd_1", risk_score: 61, degraded: true, degraded_reasons: ["t2_timeout"], tier_reached: "T1", latency_ms: 9, evidence: [{ id: "ev_a", signal: "url.homograph", weight: 9, polarity: "risk" }, { id: "ev_b", signal: "rep.feed", hard_rule: "H2", weight: 30, polarity: "risk" }], reasons: [{ evidence_ids: ["ev_a"] }] },
      1,
    );
    expect(r.top_reasons).toEqual(["url.homograph", "H2"]);
    const csv = toCsv([{ url: "http://a.test/", result: r }, { url: "http://b.test/", result: couldNotCheck("submit HTTP 422") }], "strict");
    const lines = csv.trim().split("\r\n");
    expect(lines[0]).toBe("url,verdict,risk_score,binary_label,degraded,degraded_reasons,tier_reached,top_reasons,latency_ms,verdict_id,error");
    expect(lines[1]).toBe("http://a.test/,suspicious,61,fraud,true,t2_timeout,T1,url.homograph;H2,9,vd_1,");
    expect(lines[2]).toContain("could_not_check,,fraud");
    expect(toCsv([{ url: "http://a.test/", result: r }], "lenient")).toContain("suspicious,61,legit");
  });
  it("rejects an unknown verdict as could_not_check", () => {
    expect(resultFromVerdict({ verdict: "safe" }, 3).verdict).toBe("could_not_check");
  });
});
