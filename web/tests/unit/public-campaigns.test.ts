import { describe, expect, it } from "vitest";
import { GET as list } from "../../app/api/public/campaigns/route";
import { GET as stream } from "../../app/api/public/campaigns/stream/route";
import { WindowLimiter, filterFrame, toPublicCampaign, toPublicList, visitorKey } from "../../lib/public-campaigns";

const ID = "cmp_01KB0DEM0DATA00000000000AB";
const raw = {
  campaign_id: ID, brand_id: "brd_1", brand_name: "Falcon Demo Bank", title_ar: "حملة", title_en: "Campaign", severity: "high", count: 3,
  first_seen: "2026-11-22T08:00:00Z", last_seen: "2026-11-22T10:00:00Z", series: [0, 1, 2], advice_ar: "نصيحة", advice_en: "Advice", source: "synthetic",
  status: "awaiting_approval", domains: ["http://fake-falcon.example/login", "evil.example"],
  actions: [{ id: "act_1", draft: "SECRET-DRAFT" }], approver: "SECRET-APPROVER", notes: "SECRET-NOTE", raw_url: "http://evil.example/x", linked_verdicts: ["vd_1"], operator: { x: 1 },
};

describe("toPublicCampaign", () => {
  it("drops operator-only fields and keeps only the allow-list", () => {
    const out = toPublicCampaign(raw)!;
    expect(Object.keys(out).sort()).toEqual(["advice", "brand_name", "campaign_id", "count", "domains", "first_seen", "last_seen", "series", "severity", "source", "status", "title"]);
    const text = JSON.stringify(out);
    for (const s of ["SECRET", "actions", "approver", "notes", "raw_url", "linked_verdicts"]) expect(text).not.toContain(s);
    expect(out.title).toEqual({ ar: "حملة", en: "Campaign" });
  });
  it("defangs domain indicators and caps them", () => {
    const out = toPublicCampaign({ ...raw, domains: Array.from({ length: 20 }, () => "http://a.example/p") })!;
    expect(out.domains).toHaveLength(8);
    expect(out.domains[0]).toBe("hxxp://a[.]example/p");
  });
  it("rejects unusable input and bad ids", () => {
    expect(toPublicCampaign(null)).toBeNull();
    expect(toPublicCampaign({ campaign_id: "<img onerror=1>" })).toBeNull();
    expect(toPublicList({ items: [raw, 1, {}] })).toHaveLength(1);
  });
  it("filterFrame passes campaign events filtered and drops others", () => {
    const out = filterFrame(`id: 5\nevent: campaign\ndata: ${JSON.stringify(raw)}`)!;
    expect(out).toContain("event: campaign");
    expect(out).not.toContain("SECRET");
    expect(filterFrame(`event: incident\ndata: ${JSON.stringify(raw)}`)).toBeNull();
    expect(filterFrame("event: campaign\ndata: {not json")).toBeNull();
  });
});

describe("limiter and visitor key", () => {
  it("limits per key and resets", () => {
    const l = new WindowLimiter(2, 1000);
    expect([l.take("a", 0), l.take("a", 1), l.take("b", 2)]).toEqual([0, 0, 0]);
    expect(l.take("a", 3)).toBeGreaterThan(0);
    expect(l.take("a", 2000)).toBe(0);
  });
  it("uses only a valid X-Falcon-Client-IP", () => {
    expect(visitorKey(new Request("http://x", { headers: { "x-falcon-client-ip": "203.0.113.9" } }))).toBe("203.0.113.9");
    expect(visitorKey(new Request("http://x", { headers: { "x-falcon-client-ip": "<script>" } }))).toBe("unknown");
  });
});

async function withFetch(impl: typeof fetch, fn: () => Promise<void>) {
  const original = globalThis.fetch;
  globalThis.fetch = impl;
  try {
    await fn();
  } finally {
    globalThis.fetch = original;
  }
}
const req = (ip: string) => new Request("http://x/api/public/campaigns", { headers: { "x-falcon-client-ip": ip } });

describe("GET /api/public/campaigns (mocked API)", () => {
  it("200: filtered items, key sent upstream only", async () => {
    process.env.FL_WEB_READ_KEY = "k-secret";
    let sent: Headers | undefined;
    await withFetch((async (_u: unknown, init?: RequestInit) => { sent = new Headers(init?.headers); return Response.json({ items: [raw] }); }) as typeof fetch, async () => {
      const res = await list(req("198.51.100.1"));
      expect(res.status).toBe(200);
      const text = await res.text();
      expect(text).toContain(ID);
      expect(text).not.toContain("SECRET");
      expect(text).not.toContain("k-secret");
      expect(sent?.get("x-api-key")).toBe("k-secret");
      expect(sent?.get("x-falcon-client-ip")).toBe("198.51.100.1");
    });
  });
  it("401 upstream: not_connected, no leak", async () => {
    process.env.FL_WEB_READ_KEY = "k-secret";
    await withFetch((async () => new Response("{}", { status: 401 })) as typeof fetch, async () => {
      const res = await list(req("198.51.100.2"));
      expect(res.status).toBe(502);
      expect(await res.json()).toEqual({ error: "not_connected" });
    });
  });
  it("no key configured: 503 without calling the API", async () => {
    delete process.env.FL_WEB_READ_KEY;
    await withFetch((async () => { throw new Error("must not call"); }) as typeof fetch, async () => {
      expect((await list(req("198.51.100.3"))).status).toBe(503);
    });
  });
  it("429 after the per-visitor budget", async () => {
    process.env.FL_WEB_READ_KEY = "k";
    await withFetch((async () => Response.json({ items: [] })) as typeof fetch, async () => {
      let last = 200;
      for (let i = 0; i < 31; i++) last = (await list(req("198.51.100.4"))).status;
      expect(last).toBe(429);
    });
  });
});

describe("GET /api/public/campaigns/stream (mocked API)", () => {
  const enc = new TextEncoder();
  it("passes campaign events through filtered and drops other events", async () => {
    process.env.FL_WEB_READ_KEY = "k-secret";
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode(`: hi\n\nevent: campaign\ndata: ${JSON.stringify({ campaign_id: ID, severity: "high", count: 2, approver: "SECRET-APPROVER" })}\n\n`));
        c.enqueue(enc.encode(`event: incident\ndata: {"campaign_id":"${ID}"}\n\n`));
        c.close();
      },
    });
    await withFetch((async () => new Response(body, { headers: { "content-type": "text/event-stream" } })) as typeof fetch, async () => {
      const res = await stream(req("198.51.100.9"));
      expect(res.headers.get("content-type")).toContain("text/event-stream");
      const text = await res.text();
      expect(text).toContain("event: campaign");
      expect(text).toContain(ID);
      expect(text).not.toContain("SECRET");
      expect(text).not.toContain("event: incident");
    });
  });
  it("401 upstream: not_connected", async () => {
    process.env.FL_WEB_READ_KEY = "k-secret";
    await withFetch((async () => new Response("{}", { status: 401 })) as typeof fetch, async () => {
      expect((await stream(req("198.51.100.10"))).status).toBe(502);
    });
  });
});
