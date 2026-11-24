import { describe, expect, it } from "vitest";
import { adaptFloor } from "@/lib/vad";

describe("noise floor tracking", () => {
  it("does not move on voiced frames", () => {
    expect(adaptFloor(0.01, 0.2, true)).toBe(0.01);
  });
  it("follows the room on silent frames, also while a capture runs (it used to freeze)", () => {
    let floor = 0.005;
    for (let i = 0; i < 100; i++) floor = adaptFloor(floor, 0.02, false); // a fan starts during the recording
    expect(floor).toBeGreaterThan(0.018);
    for (let i = 0; i < 200; i++) floor = adaptFloor(floor, 0.004, false); // and stops again
    expect(floor).toBeLessThan(0.006);
  });
});
