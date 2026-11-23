import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import bundled from "@/lib/results.generated.json";
import { formatCi, formatMetric, loadResults, parseResults } from "@/lib/results";

const published = join(fileURLToPath(new URL("../../..", import.meta.url)), "evals", "results", "published");

describe("results (published eval artifact only)", () => {
  it("reports 'in progress' (null) when no artifact is bundled", () => {
    expect(parseResults({ available: false })).toBeNull();
    expect(parseResults({ available: true, artifact: "x.json", data: { metrics: {} } })).toBeNull();
  });

  it("formats from artifact values and never invents one", () => {
    const view = parseResults({
      available: true,
      artifact: "a.json",
      data: { created_at: "t", dataset_hash: "h", scope: "s", metrics: { "test.n": 10, "test.recall": 0.5, "test.recall_ci95": [0.25, 0.75], "test.official_false_dangerous": 0 } },
    })!;
    expect(view.splits).toHaveLength(1);
    const row = view.splits[0]!.rows[0]!;
    expect(formatMetric("recall", row.value, "en")).toBe("50.0%");
    expect(formatCi(row, "en")).toBe("25.0% – 75.0%");
    expect(view.splits[0]!.officialFalseDangerous).toBe(0);
  });

  it("the bundled copy equals the newest published artifact when the monorepo is present", () => {
    if (!existsSync(published)) return;
    const newest = readdirSync(published).filter((f) => f.endsWith(".json")).sort().at(-1);
    if (!newest) return;
    const file = bundled as unknown as { artifact: string; data: unknown };
    expect(file.artifact).toBe(newest);
    expect(file.data).toEqual(JSON.parse(readFileSync(join(published, newest), "utf8")));
    expect(loadResults()).not.toBeNull();
  });
});
