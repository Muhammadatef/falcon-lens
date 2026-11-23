import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import { NODES, flatSteps, liveRun, parseAgentTrace } from "@/lib/agent-trace";
import { DEMO_TRACE } from "@/lib/demo";

const schema = JSON.parse(readFileSync(fileURLToPath(new URL("../../../contracts/agent_trace.schema.json", import.meta.url)), "utf8"));
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
const valid = ajv.compile(schema);

describe("agent trace", () => {
  it("the demo trace validates against agent_trace.schema.json and parses unchanged", () => {
    expect(valid(DEMO_TRACE), JSON.stringify(valid.errors)).toBe(true);
    const parsed = parseAgentTrace(DEMO_TRACE)!;
    expect(parsed.runs[0]!.steps.map((s) => s.node)).toEqual([...NODES]);
    expect(liveRun(parsed)?.status).toBe("interrupted");
    expect(flatSteps(parsed).map((x) => x.step.seq)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("drops hostile or malformed parts instead of passing them on", () => {
    const hostile = {
      incident_id: DEMO_TRACE.incident_id,
      thread_id: 5,
      runs: [
        {
          run_id: "r1",
          status: "weird",
          steps: [
            { seq: 1, node: "enrich", status: "completed", tools: [{ name: "x", mode: "root" }, { name: "ok", mode: "read", duration_ms: -4 }], llm: { route: "mars" } },
            { seq: 2, node: "rm -rf", status: "completed" },
            "junk",
          ],
          interrupt: { action_id: 7 },
        },
        "junk",
      ],
    };
    const t = parseAgentTrace(hostile)!;
    expect(t.thread_id).toBe("");
    expect(t.runs).toHaveLength(1);
    expect(t.runs[0]!.status).toBe("running");
    expect(t.runs[0]!.steps).toHaveLength(1);
    expect(t.runs[0]!.steps[0]!.tools).toEqual([{ name: "ok", mode: "read", status: "ok", evidence_ids: [], duration_ms: 0 }]);
    expect(t.runs[0]!.steps[0]!.llm).toBeNull();
    expect(t.runs[0]!.interrupt).toBeNull();
    expect(parseAgentTrace({ incident_id: "nope", runs: [] })).toBeNull();
    expect(parseAgentTrace(null)).toBeNull();
  });
});
