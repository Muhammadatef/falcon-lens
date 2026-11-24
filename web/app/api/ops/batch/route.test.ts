import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

let n = 0;
const req = (body: unknown, key: string | null = "ops-key-not-a-secret") =>
  new Request("http://web.test/api/ops/batch", {
    method: "POST",
    headers: { "content-type": "application/json", "x-falcon-client-ip": `198.51.100.${++n}`, ...(key ? { "x-ops-key": key } : {}) },
    body: JSON.stringify(body),
  });
const verdict = (extra: object = {}) => ({ verdict_id: "vd_1", verdict: "dangerous", risk_score: 92, final: true, degraded: false, tier_reached: "T1", latency_ms: 40, evidence: [], reasons: [], ...extra });
const upstream = (...replies: Response[]) => {
  const f = vi.fn(async () => replies.shift() ?? new Response("{}", { status: 500 }));
  vi.stubGlobal("fetch", f);
  return f;
};
const json = (status: number, body: unknown, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

beforeEach(() => {
  vi.stubEnv("FL_OPS_BATCH_KEY", "ops-key-not-a-secret");
  vi.stubEnv("FL_WEB_READ_KEY", "server-key-not-a-secret");
  vi.stubEnv("FL_API_INTERNAL_URL", "http://api.test:8000");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("POST /api/ops/batch", () => {
  it("rejects a missing key without calling the API, and holds no server key", async () => {
    const f = upstream();
    expect((await POST(req({ url: "http://a.test/" }, null))).status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });
  it("passes the API's 403 (key lacks check scope) back so the page can say so", async () => {
    upstream(json(403, {}));
    expect((await POST(req({ url: "http://a.test/" }))).status).toBe(403);
  });
  it("forwards the typed key, never a server key, and returns a final verdict", async () => {
    const f = upstream(json(200, verdict()));
    const res = await POST(req({ url: "http://a.test/" }));
    expect(await res.json()).toMatchObject({ verdict: "dangerous", risk_score: 92, verdict_id: "vd_1", error: "" });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test:8000/v1/check/url?wait=8");
    const h = init.headers as Headers;
    expect(h.get("x-api-key")).toBe("ops-key-not-a-secret");
    expect(JSON.stringify(Object.fromEntries(h))).not.toContain("server-key");
  });
  it("polls until final", async () => {
    upstream(json(202, { verdict_id: "vd_2" }), json(200, verdict({ verdict_id: "vd_2", final: false })), json(200, verdict({ verdict_id: "vd_2", verdict: "suspicious" })));
    const body = await (await POST(req({ url: "http://a.test/" }))).json();
    expect(body.verdict).toBe("suspicious");
  }, 10_000);
  it("passes an upstream 429 back with Retry-After", async () => {
    upstream(json(429, {}, { "retry-after": "7" }));
    const res = await POST(req({ url: "http://a.test/" }));
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("7");
  });
  it("turns an upstream rejection into could_not_check", async () => {
    upstream(json(422, {}));
    expect(await (await POST(req({ url: "http://a.test/" }))).json()).toMatchObject({ verdict: "could_not_check", error: "submit HTTP 422" });
  });
  it("limits one visitor per minute", async () => {
    upstream();
    const ip = "203.0.113.9";
    const mk = () => new Request("http://web.test/api/ops/batch", { method: "POST", headers: { "x-falcon-client-ip": ip, "x-ops-key": "x" }, body: "{}" });
    let last = 0;
    for (let i = 0; i < 241; i++) last = (await POST(mk())).status;
    expect(last).toBe(429);
  });
});
