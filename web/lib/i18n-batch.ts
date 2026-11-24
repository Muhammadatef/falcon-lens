/** Strings of the operator batch page (/ops/batch). Formal Modern Standard Arabic; the word "safe" never appears. */
import type { Lang } from "./contracts";

const ar = {
  title: "فحص قائمة روابط",
  sub: "ارفع ملفًا نصيًا (رابط في كل سطر) أو ملف CSV فيه عمود url، حتى 500 رابط. تُفحص الروابط بالمسار الكامل ويُنزَّل ملف CSV بالنتائج.",
  key: "مفتاح المشغّل",
  file: "ملف الروابط (‎.txt أو ‎.csv)",
  mode: "طريقة التصنيف الثنائي",
  strict: "صارم (مُوصى به): احتيال = خطير أو مشبوه",
  lenient: "متساهل: احتيال = خطير فقط",
  start: "ابدأ الفحص",
  progress: "تم فحص {d} من {n}",
  download: "نزّل ملف CSV",
  done: "اكتمل الفحص. «تعذّر الفحص» يُحسب احتيالًا في الوضع الصارم ويُعرض منفصلًا.",
  summary: "خطير {a} · مشبوه {b} · لم نجد علامات تحذير {c} · تعذّر الفحص {d}",
  e_key: "مفتاح المشغّل غير صحيح.",
  e_conf: "هذه الخدمة غير مهيأة على الخادم.",
  e_file: "الملف فارغ أو لا يحوي روابط.",
  e_many: "الحد الأقصى 500 رابط.",
  e_big: "الملف كبير جدًا.",
} as const;

const en: Record<keyof typeof ar, string> = {
  title: "Check a list of URLs",
  sub: "Upload a text file (one URL per line) or a CSV with a url column, up to 500 URLs. Each goes through the full cascade and you download the results as CSV.",
  key: "Operator key",
  file: "URL file (.txt or .csv)",
  mode: "Binary label mode",
  strict: "Strict (recommended): fraud = dangerous or suspicious",
  lenient: "Lenient: fraud = dangerous only",
  start: "Start checking",
  progress: "Checked {d} of {n}",
  download: "Download CSV",
  done: 'Finished. "Could not check" counts as fraud in strict mode and is reported separately.',
  summary: "Dangerous {a} · Suspicious {b} · No warning signs found {c} · Could not check {d}",
  e_key: "The operator key is not correct.",
  e_conf: "This service is not configured on the server.",
  e_file: "The file is empty or has no URLs.",
  e_many: "At most 500 URLs.",
  e_big: "The file is too large.",
};

export type BatchKey = keyof typeof ar;
export const bt = (lang: Lang, key: BatchKey, vars: Record<string, string | number> = {}): string =>
  (lang === "ar" ? ar : en)[key].replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? ""));
