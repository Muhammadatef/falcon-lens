import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { readClip, safeJoin } from "./route";

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

describe("readClip", () => {
  const root = mkdtempSync(path.join(tmpdir(), "voice-"));
  const outside = mkdtempSync(path.join(tmpdir(), "outside-"));
  mkdirSync(path.join(root, "en"));
  writeFileSync(path.join(root, "en", "a.mp3"), "audio");
  writeFileSync(path.join(outside, "secret.mp3"), "secret");
  symlinkSync(path.join(outside, "secret.mp3"), path.join(root, "en", "out.mp3"));
  symlinkSync(path.join(root, "en", "a.mp3"), path.join(root, "en", "in.mp3"));
  mkdirSync(path.join(root, "en", "dir.mp3"));

  it("serves a regular file", async () => {
    expect((await readClip(root, "en", "a.mp3"))?.toString()).toBe("audio");
  });
  it("rejects a symlink to outside, a symlink to inside, a directory and a missing file", async () => {
    expect(await readClip(root, "en", "out.mp3")).toBeNull();
    expect(await readClip(root, "en", "in.mp3")).toBeNull();
    expect(await readClip(root, "en", "dir.mp3")).toBeNull();
    expect(await readClip(root, "en", "nope.mp3")).toBeNull();
  });
  it("rejects a language dir that is a symlink escaping the base", async () => {
    const r2 = mkdtempSync(path.join(tmpdir(), "voice2-"));
    symlinkSync(outside, path.join(r2, "en"));
    expect(await readClip(r2, "en", "secret.mp3")).toBeNull();
  });
});
