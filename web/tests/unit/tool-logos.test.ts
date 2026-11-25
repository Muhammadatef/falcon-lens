import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LOGO_PATHS } from "@/lib/tool-logos.gen";

const DIR = join(process.cwd(), "public", "logos", "tools");
const files = readdirSync(DIR).filter((f) => f.endsWith(".svg")).sort();
const meta = JSON.parse(readFileSync(join(DIR, "logos.json"), "utf8")) as {
  version: string;
  package_licence: string;
  retrieved: string;
  badges: string[];
  icons: { slug: string; title: string; hex: string; brand_source: string; licence: string; file_url: string }[];
};
const licences = readFileSync(join(DIR, "LOGOS_LICENSES.md"), "utf8");

describe("vendored tool logos", () => {
  it("every vendored logo has a metadata entry and a row in LOGOS_LICENSES.md, and the reverse", () => {
    expect(files.length).toBeGreaterThan(10);
    expect(meta.icons.map((i) => `${i.slug}.svg`).sort()).toEqual(files);
    for (const icon of meta.icons) {
      const row = licences.split("\n").find((line) => line.startsWith(`| \`${icon.slug}.svg\` |`));
      expect(row, `no licence row for ${icon.slug}.svg`).toBeDefined();
      expect(row).toContain(icon.file_url);
      expect(row).toContain(icon.brand_source);
      expect(row).toContain(icon.licence);
      expect(row).toContain(meta.retrieved);
      expect(icon.file_url).toContain(`simple-icons@${meta.version}/icons/${icon.slug}.svg`);
      expect(icon.licence).toMatch(/^(CC0-1\.0|CC-BY-4\.0)$/);
    }
    expect(meta.package_licence).toBe("CC0-1.0");
  });

  it("states the nominative use and lists the tools that get a text badge instead", () => {
    expect(licences).toContain("used nominatively");
    expect(licences).toContain("do not imply");
    for (const name of meta.badges) expect(licences, name).toContain(name);
  });

  it("the files are plain single-path icons: no script, no external reference, no embedded image", () => {
    for (const f of files) {
      const svg = readFileSync(join(DIR, f), "utf8");
      expect(svg, f).toMatch(/^<svg role="img" viewBox="0 0 24 24" xmlns="http:\/\/www\.w3\.org\/2000\/svg"><title>[^<]+<\/title><path d="[^"]+"\/><\/svg>\s*$/);
      expect(svg, f).not.toMatch(/<script|href=|<image|<foreignObject|style=/i);
    }
  });

  it("the generated module matches the files (run scripts/gen-tool-logos.mjs after a change)", () => {
    expect(Object.keys(LOGO_PATHS).sort()).toEqual(files.map((f) => f.replace(/\.svg$/, "")));
    for (const icon of meta.icons) {
      const svg = readFileSync(join(DIR, `${icon.slug}.svg`), "utf8");
      const entry = LOGO_PATHS[icon.slug as keyof typeof LOGO_PATHS];
      expect(svg, icon.slug).toContain(`<path d="${entry.d}"/>`);
      expect(entry.hex.toLowerCase()).toBe(`#${icon.hex}`.toLowerCase());
      expect(entry.title).toBe(icon.title);
    }
  });

  it("holds tool logos only: no police, government, bank or telecom mark", () => {
    const allowed = ["caddy", "claude", "cloudflare", "docker", "fastapi", "grafana", "langgraph", "modelcontextprotocol", "nextdotjs", "ollama", "opentelemetry", "postgresql", "prometheus", "qwen", "redis", "scikitlearn"];
    expect(files.map((f) => f.replace(/\.svg$/, ""))).toEqual(allowed);
  });
});
