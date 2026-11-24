import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { DEMO_DANGEROUS } from "@/lib/demo";
import { render, finalClips } from "@/lib/voice-script";
import { usedModel, voiceBackoffMs } from "@/lib/voice";

const repo = fileURLToPath(new URL("../../..", import.meta.url));

describe("voice hardening", () => {
  it("the gateway defers to the app's Permissions-Policy (it is only a default), so /voice keeps microphone=(self)", () => {
    const caddy = readFileSync(`${repo}/infra/gateway/Caddyfile`, "utf8");
    expect(caddy).toMatch(/^\s*\?Permissions-Policy "camera=\(\), microphone=\(\)/m);
    expect(caddy).not.toMatch(/^\s*Permissions-Policy /m);
  });
  it("back-off doubles from one second and stops at fifteen", () => {
    expect([1, 2, 3, 4, 5, 6, 10].map(voiceBackoffMs)).toEqual([1000, 2000, 4000, 8000, 15000, 15000, 15000]);
  });
  it("one decision for the AI second look: a model answered unless the route is none", () => {
    expect(usedModel({ ...DEMO_DANGEROUS, model_route: "none" })).toBe(false);
    expect(usedModel({ ...DEMO_DANGEROUS, model_route: "local" })).toBe(true);
    expect(usedModel({ ...DEMO_DANGEROUS, model_route: "cloud" })).toBe(true);
  });
  it("the closing line names only what happened to the Sentinel", () => {
    const c = { total: 2, dangerous: 1, suspicious: 0, clear: 1, failed: 0 };
    expect(finalClips(c, "found").at(-1)).toBe("final.both_agents");
    expect(finalClips(c, "watching").at(-1)).toBe("final.sentinel_watching");
    expect(finalClips(c, "unavailable").at(-1)).toBe("final.sentinel_unavailable");
    expect(finalClips(c, "none").some((k) => k.startsWith("final."))).toBe(false);
    expect(render("en", ["sentinel.unavailable"])).toContain("couldn't reach the Sentinel");
  });
});
