import { describe, expect, it } from "vitest";
import { mergeCapabilities } from "@/lib/capabilities";

describe("capabilities", () => {
  it("treats a missing flag as in progress, never live", () => {
    expect(mergeCapabilities({}, null).message_check).toBe(false);
    expect(mergeCapabilities({ message_check: "yes" }, null).message_check).toBe(false);
  });
  it("runtime /v1/meta flags override the bundled ones", () => {
    const merged = mergeCapabilities({ investigator: false, message_check: true }, { investigator: true });
    expect(merged.investigator).toBe(true);
    expect(merged.message_check).toBe(true);
  });
});
