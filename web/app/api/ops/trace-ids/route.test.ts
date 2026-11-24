import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetOperatorCache } from "@/lib/ops-gate";
import { GET as obsConfig } from "../../obs-config/route";
import { GET as incidentTraces } from "../incident-traces/route";
import { GET } from "./route";

const VID = "vd_01KB0DEM0DATA0000000000001";
const INC = "inc_01KB0DEM0DATA0000000000001";
const TID = "0123456789abcdef0123456789abcdef";
const get = (path: string, key: string | null) => new Request(`http://web.test${path}`, { headers: key ? { "x-ops-key": key } : {} });
const json = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** A fake API: `operator-key` is an operator, `read-key` has no operator scope, anything else is unknown. */
const fakeApi = (docs: Record<string, unknown> = {}) => {
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const key = new Headers(init?.headers).get("x-api-key");
    if (url.endsWith("/v1/admin/llm-route")) return key === "operator-key" ? json(200) : key === "read-key" ? json(403) : json(401);
    const hit = Object.entries(docs).find(([id]) => url.includes(id));
    return hit ? json(200, hit[1]) : json(404);
  });
  vi.stubGlobal("fetch", f);
  return f;
};

beforeEach(() => {
  resetOperatorCache();
  vi.stubEnv("FL_API_INTERNAL_URL", "http://api.test:8000");
  vi.stubEnv("FL_WEB_READ_KEY", "server-key-not-a-secret");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("operator-only observability routes", () => {
  for (const [name, handler, path] of [
    ["trace-ids", GET, `/api/ops/trace-ids?verdicts=${VID}`],
    ["incident-traces", incidentTraces, `/api/ops/incident-traces?incidents=${INC}`],
    ["obs-config", obsConfig, "/api/obs-config"],
  ] as const) {
    it(`${name}: 401 without a key and the API is never called`, async () => {
      const f = fakeApi();
      expect((await handler(get(path, null))).status).toBe(401);
      expect(f).not.toHaveBeenCalled();
    });
    it(`${name}: 401 for an unknown key, 403 for a key without operator scope, and no server key is used`, async () => {
      const f = fakeApi();
      expect((await handler(get(path, "wrong-key"))).status).toBe(401);
      expect((await handler(get(path, "read-key"))).status).toBe(403);
      for (const call of f.mock.calls) expect(JSON.stringify(call[1])).not.toContain("server-key-not-a-secret");
    });
  }

  it("trace-ids returns only validated 32-hex ids, keyed by verdict id", async () => {
    fakeApi({ [VID]: { verdict_id: VID, trace_id: TID, secret: "x" } });
    const r = await GET(get(`/api/ops/trace-ids?verdicts=${VID}`, "operator-key"));
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ trace_ids: { [VID]: TID } });
  });
  it("trace-ids drops a malformed trace id and rejects bad or too many ids", async () => {
    fakeApi({ [VID]: { trace_id: "<script>" } });
    expect(await (await GET(get(`/api/ops/trace-ids?verdicts=${VID}`, "operator-key"))).json()).toEqual({ trace_ids: {} });
    expect((await GET(get("/api/ops/trace-ids?verdicts=../etc", "operator-key"))).status).toBe(400);
    expect((await GET(get("/api/ops/trace-ids", "operator-key"))).status).toBe(400);
    const many = Array.from({ length: 101 }, (_, i) => `vd_${String(i).padStart(26, "0")}`).join(",");
    expect((await GET(get(`/api/ops/trace-ids?verdicts=${many}`, "operator-key"))).status).toBe(400);
  });
  it("incident-traces returns the latest run's valid trace id and the run time span only", async () => {
    fakeApi({
      [INC]: { runs: [{ trace_id: TID, started_at: "2026-11-24T10:00:00Z", finished_at: "2026-11-24T10:01:00Z", steps: ["x"] }, { trace_id: "bad", started_at: "2026-11-24T10:05:00Z", finished_at: null }] },
    });
    const r = await incidentTraces(get(`/api/ops/incident-traces?incidents=${INC}`, "operator-key"));
    expect(await r.json()).toEqual({ traces: { [INC]: { trace_id: TID, from: Date.parse("2026-11-24T10:00:00Z"), to: Date.parse("2026-11-24T10:05:00Z") } } });
  });
  it("obs-config answers an operator with origins only", async () => {
    fakeApi();
    const r = await obsConfig(get("/api/obs-config", "operator-key"));
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ phoenix: "http://127.0.0.1:6006", grafana: "http://127.0.0.1:3001" });
  });
});
