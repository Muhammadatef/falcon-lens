import type { Lang } from "./contracts";

/**
 * Internal degraded-reason codes (for example `not_rendered:metadata`) are never shown to a reader.
 * Each is mapped to one plain sentence fragment; unknown codes fall back to a generic line. Duplicates collapse.
 */
const PLAIN: readonly { test: RegExp; ar: string; en: string }[] = [
  { test: /^not_rendered/, ar: "تعذّر فتح الصفحة في بيئة العزل", en: "the page could not be opened in the isolated browser" },
  { test: /^sandbox_unavailable/, ar: "بيئة العزل غير متاحة حالياً", en: "the isolated browser was not available" },
  { test: /^static_fallback|^partial_render/, ar: "قرأنا الصفحة قراءة جزئية فقط", en: "the page was only partly read" },
  { test: /^t1_model_unavailable/, ar: "نموذج التحليل غير متاح حالياً", en: "the analysis model was not available" },
  { test: /^ocr_unavailable/, ar: "تعذّرت قراءة النص داخل الصورة", en: "text inside the image could not be read" },
  { test: /^invalid_url/, ar: "الرابط غير صالح", en: "the link is not valid" },
  { test: /^links_over_limit/, ar: "عدد الروابط تجاوز الحد المسموح للفحص", en: "there were more links than one check can cover" },
  { test: /^child_check/, ar: "تعذّر فحص أحد الروابط الفرعية", en: "one of the linked addresses could not be checked" },
];
const GENERIC = { ar: "لم يستجب أحد مصادر الفحص", en: "one of the sources did not respond" };

export function plainDegradedReasons(codes: readonly string[] | undefined, lang: Lang): string[] {
  const out = new Set<string>();
  for (const code of codes ?? []) out.add((PLAIN.find((p) => p.test.test(code)) ?? GENERIC)[lang]);
  return [...out];
}
