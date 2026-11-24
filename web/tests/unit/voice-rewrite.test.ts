import { describe, expect, it } from "vitest";
import config from "../../next.config";

// Only the two clip languages go through the private-clip route; /voice/sfx/* is served from public/ (the earcons).
describe("voice clip rewrite", () => {
  it("rewrites only ar_ae and en clip paths", async () => {
    const r = await (config as { rewrites: () => Promise<{ beforeFiles: { source: string }[] }> }).rewrites();
    const src = r.beforeFiles.map((x) => x.source);
    expect(src).toContain("/voice/:lang(ar_ae|en)/:file");
    expect(src.some((s) => s === "/voice/:lang/:file")).toBe(false);
  });
});
