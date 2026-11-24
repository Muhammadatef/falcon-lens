import { describe, expect, it } from "vitest";
import { safeJoin } from "./route";

describe("voice clip path safety", () => {
  it("accepts known langs and clip files", () => {
    expect(safeJoin("/d", "ar_ae", "ar_ae.found.3.mp3")).toBe("/d/ar_ae/ar_ae.found.3.mp3");
    expect(safeJoin("/d", "en", "manifest.json")).toBe("/d/en/manifest.json");
  });
  it("rejects traversal, unknown langs and other extensions", () => {
    expect(safeJoin("/d", "ar_ae", "../x.mp3")).toBeNull();
    expect(safeJoin("/d", "ar_ae", "..%2fx.mp3")).toBeNull();
    expect(safeJoin("/d", "../etc", "a.mp3")).toBeNull();
    expect(safeJoin("/d", "fr", "a.mp3")).toBeNull();
    expect(safeJoin("/d", "en", "a.sh")).toBeNull();
    expect(safeJoin("/d", "en", ".hidden.mp3")).toBeNull();
  });
});
