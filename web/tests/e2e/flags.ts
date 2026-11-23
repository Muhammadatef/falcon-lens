import { readFileSync } from "node:fs";
import { join } from "node:path";
import bundled from "../../lib/capabilities.generated.json";

const source = readFileSync(join(process.cwd(), "lib", "capabilities.ts"), "utf8");

/** Whether lib/capabilities.ts lists this flag (the four agent / interface flags arrive with the capability-flags card). */
export const known = (id: string): boolean => source.includes(`"${id}"`);

/** Effective flag on the default test stack: the bundled value, and false for any id the code does not list yet. */
export const onDefaultStack = (id: string): boolean => known(id) && (bundled as Record<string, boolean>)[id] === true;

/** Effective flag on the all-true stack (MOCK_CAPS in playwright.config.ts). */
export const onAllOnStack = (id: string): boolean => known(id);

export const badgeWord = (live: boolean, lang: "ar" | "en"): string => (lang === "en" ? (live ? "Live" : "In progress") : live ? "يعمل الآن" : "قيد الإنجاز");
