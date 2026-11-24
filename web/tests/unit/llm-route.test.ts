import { describe, expect, it } from "vitest";
import { parseLlmRoute } from "@/lib/llm-route";
import { parsePublicRoute } from "@/lib/llm-route-public";

const good = { mode: "local", effective_mode: "local", local_model: "qwen3.8:27b", local_models: ["inkling-2-mini-chat", "qwen3.8:27b"], modes: [], cloud_available: false, sovereign_locked: true, source: "runtime", updated_at: null, updated_by: null };

describe("llm route parsing", () => {
  it("accepts the contract shape", () => {
    const r = parseLlmRoute(good);
    expect(r?.effective_mode).toBe("local");
    expect(r?.sovereign_locked).toBe(true);
  });
  it("rejects unknown modes and junk", () => {
    expect(parseLlmRoute({ ...good, mode: "evil" })).toBeNull();
    expect(parseLlmRoute({ ...good, effective_mode: "auto" })).toBeNull();
    expect(parseLlmRoute(null)).toBeNull();
    expect(parseLlmRoute("x")).toBeNull();
  });
  it("public meta flag is read-only and truthful: missing means unknown", () => {
    expect(parsePublicRoute({ llm_route: { mode: "cloud_with_local_fallback", local_model: "inkling-2-mini-chat", sovereign: false } })?.mode).toBe("cloud_with_local_fallback");
    expect(parsePublicRoute({})).toBeNull();
    expect(parsePublicRoute({ llm_route: { mode: "auto", local_model: "x" } })).toBeNull();
  });
});
