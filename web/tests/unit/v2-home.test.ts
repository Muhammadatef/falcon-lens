import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { summarise } from "@/components/SentinelTicker";
import { CAP_IDS, mergeCapabilities } from "@/lib/capabilities";
import { parseCampaign } from "@/lib/contracts";
import fpBundled from "@/lib/fp-regress.generated.json";
import { formatRate, parseLiveFp } from "@/lib/fp-regress";
import { MESSAGES } from "@/lib/i18n";
import { formatCi, formatMetric, headline, parseResults } from "@/lib/results";

const repo = fileURLToPath(new URL("../../..", import.meta.url));

describe("capability flags (W2-01)", () => {
  it("covers the agents and the integration surfaces", () => {
    for (const id of ["sentinel_agent", "rest_api", "mcp", "stix", "investigator"] as const) expect(CAP_IDS).toContain(id);
  });
  it("missing, false, true and runtime-overrides-bundle", () => {
    expect(mergeCapabilities({}, null).sentinel_agent).toBe(false); // missing: in progress
    expect(mergeCapabilities({ mcp: false }, {}).mcp).toBe(false);
    expect(mergeCapabilities({ stix: true }, {}).stix).toBe(true);
    expect(mergeCapabilities({ rest_api: true }, { rest_api: false }).rest_api).toBe(false); // runtime wins
    expect(mergeCapabilities({ sentinel_agent: false }, { sentinel_agent: true }).sentinel_agent).toBe(true);
  });
});

const artifact = (metrics: Record<string, unknown>) => ({ available: true, artifact: "x.json", data: { created_at: "t", dataset_hash: "h", scope: "s", metrics } });

describe("headline() (W2-08): nothing renders unless the artifact holds all four fields", () => {
  const full = { "test.n": 77, "test.recall": 0.8125, "test.recall_ci95": [0.7, 0.9], "test.fpr": 0.0625, "test.fpr_ci95": [0.01, 0.12], "test.official_false_dangerous": 3 };
  it("is null when unavailable or a field is missing", () => {
    expect(headline(parseResults({ available: false }))).toBeNull();
    expect(headline(null)).toBeNull();
    const noOfficial: Record<string, unknown> = { ...full };
    delete noOfficial["test.official_false_dangerous"];
    expect(headline(parseResults(artifact(noOfficial)))).toBeNull();
    const noFpr: Record<string, unknown> = { ...full };
    delete noFpr["test.fpr"];
    expect(headline(parseResults(artifact(noFpr)))).toBeNull();
  });
  it("returns the artifact's own values for a second, different fixture (nothing is typed)", () => {
    const h = headline(parseResults(artifact(full)))!;
    expect(formatMetric("recall", h.recall.value, "en")).toBe("81.3%");
    expect(formatMetric("fpr", h.fpr.value, "ar")).toBe("6.3%");
    expect(formatCi(h.recall, "en")).toBe("70.0% – 90.0%");
    expect(h.official).toBe(3);
    expect(h.n).toBe(77);
  });
});

describe("live false-alarm artifact (ruling 3)", () => {
  const fixture = {
    available: true,
    artifact: "z.json",
    data: {
      created_at: "2026-01-02T03:04:05Z",
      counts: { dangerous: 1, no_warning_signs: 5, suspicious: 4 },
      false_positive_rate: { value: 0.5, ci95: [0.25, 0.75] },
      by_serves_web: { serves_web_page: { n: 8, false_positive_rate: { value: 0.125, ci95: [0.05, 0.4] } } },
    },
  };
  it("reads web-serving and all rows with range and n; n of the all row is the sum of counts", () => {
    const f = parseLiveFp(fixture)!;
    expect(f.web).toEqual({ n: 8, rate: 0.125, lo: 0.05, hi: 0.4 });
    expect(f.all).toEqual({ n: 10, rate: 0.5, lo: 0.25, hi: 0.75 });
    expect(formatRate(f.web.rate, "en")).toBe("12.5%");
  });
  it("is null when a field is missing", () => {
    expect(parseLiveFp({ available: false })).toBeNull();
    expect(parseLiveFp({ ...fixture, data: { ...fixture.data, by_serves_web: {} } })).toBeNull();
  });
  it("the bundled copy is the newest published fp_regress artifact (by created_at) when the monorepo is present", () => {
    const dir = join(repo, "evals", "results", "published", "fp_regress");
    if (!existsSync(dir)) return;
    const files = readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => ({ f, d: JSON.parse(readFileSync(join(dir, f), "utf8")) as { created_at: string; by_serves_web?: unknown; false_positive_rate?: unknown } }))
      .filter(({ d }) => d.by_serves_web && d.false_positive_rate)
      .sort((a, b) => a.d.created_at.localeCompare(b.d.created_at));
    expect((fpBundled as { artifact: string }).artifact).toBe(files.at(-1)!.f);
  });
});

describe("sentinel ticker counts come from the response (W2-04)", () => {
  const raw = (id: string, count: number, last: string, source: string) => ({ campaign_id: id, title: { en: id }, count, last_seen: last, source });
  const parse = (rows: unknown[]) => rows.map(parseCampaign).filter((c) => c !== null);
  it("sums and picks the latest", () => {
    const s = summarise(parse([raw("a", 3, "2026-11-20T10:00:00Z", "live"), raw("b", 4, "2026-11-22T10:00:00Z", "live")]));
    expect(s).toMatchObject({ campaigns: 2, checks: 7, live: true });
    expect(s.latest?.id).toBe("b");
  });
  it("flags non-live sources and handles empty", () => {
    expect(summarise(parse([raw("a", 1, "2026-11-20T10:00:00Z", "synthetic")])).live).toBe(false);
    expect(summarise([])).toMatchObject({ campaigns: 0, checks: 0, latest: null });
  });
});

describe("copy rules (W2 acceptance)", () => {
  const source = readFileSync(join(repo, "web", "lib", "i18n.ts"), "utf8");
  it("types no digit-percent literal (only the 95% interval label is allowed)", () => {
    const hits = [...source.matchAll(/\d+(?:\.\d+)?\s?%/g)].map((m) => m[0]).filter((x) => x.replace(/\s/g, "") !== "95%");
    expect(hits).toEqual([]);
  });
  it("Arabic and English have the same keys and no empty string", () => {
    expect(Object.keys(MESSAGES.ar).sort()).toEqual(Object.keys(MESSAGES.en).sort());
    for (const lang of ["ar", "en"] as const) for (const [k, v] of Object.entries(MESSAGES[lang])) expect(v, `${lang}:${k}`).not.toBe("");
  });
  it("never says safe / آمن", () => {
    for (const v of Object.values(MESSAGES.ar)) expect(v).not.toMatch(/(^|[\s«"(])آمن(ة|ا|ون)?([\s».,:؛،)]|$)/);
    for (const v of Object.values(MESSAGES.en)) expect(v.toLowerCase()).not.toMatch(/\bsafe(ly|r|st|ty)?\b/);
  });
  it("the nav labels in the v2 order exist in both languages", () => {
    for (const k of ["nav.check", "nav.agents", "nav.results", "nav.authorities", "nav.docs", "nav.privacy", "nav.live", "nav.campaigns", "nav.ops"] as const) {
      expect(MESSAGES.ar[k]).toBeTruthy();
      expect(MESSAGES.en[k]).toBeTruthy();
    }
    expect(MESSAGES.en["cap.progress"]).toBe("In progress");
  });
});
