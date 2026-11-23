import bundled from "../../lib/capabilities.generated.json";

/** Effective flag on the default test stack: the bundled value (a flag missing from the bundle counts as false). */
export const onDefaultStack = (id: string): boolean => (bundled as Record<string, boolean>)[id] === true;

/** Effective flag after forceCaps(context, baseURL, "true"). */
export const onAllOnStack = (id: string): boolean => id !== "";

export const badgeWord = (live: boolean, lang: "ar" | "en"): string => (lang === "en" ? (live ? "Live" : "In progress") : live ? "يعمل الآن" : "قيد الإنجاز");
