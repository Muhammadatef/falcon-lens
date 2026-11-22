/**
 * Extension strings. Arabic is written first and natively; English mirrors it.
 * The word "safe" (and «آمن») never appears: the lowest state is "no warning signs found".
 */
import type { BrandRef, LocalSignal } from "./prefilter";

export type Lang = "ar" | "en";
export type VerdictWord = "dangerous" | "suspicious" | "no_warning_signs";

const S = {
  brand: { ar: "عدسة الصقر", en: "Falcon Lens" },
  lang_switch: { ar: "English", en: "العربية" },
  lang_switch_label: { ar: "Switch to English", en: "التبديل إلى العربية" },

  v_dangerous: { ar: "خطِر", en: "Dangerous" },
  v_suspicious: { ar: "مريب", en: "Suspicious" },
  v_no_warning_signs: { ar: "لم نجد علامات تحذير", en: "No warning signs found" },

  warn_title: { ar: "توقّف. لا تكتب أي معلومات هنا", en: "Stop. Do not type anything here" },
  warn_lead: {
    ar: "أوقفنا فتح هذه الصفحة لأن عنوانها يحمل علامات احتيال.",
    en: "We paused this page because its address shows signs of a scam.",
  },
  warn_danger_lead: {
    ar: "الفحص العميق أكّد الخطر. أغلق هذه الصفحة.",
    en: "The deeper check confirmed the danger. Close this page.",
  },
  warn_nws_lead: {
    ar: "الفحص العميق لم يجد علامات تحذير. هذا ليس ضمانًا، فابقَ حذرًا.",
    en: "The deeper check found no warning signs. That is not a guarantee, so stay careful.",
  },
  address: { ar: "العنوان الذي كنت ستفتحه", en: "The address you were about to open" },
  why: { ar: "لماذا أوقفناك", en: "Why we stopped you" },
  why_local: { ar: "ما لاحظه الفحص على جهازك", en: "What the check on your device noticed" },
  reasons: { ar: "الأسباب", en: "Reasons" },
  caution: { ar: "ابقَ حذرًا", en: "Stay careful" },
  do_now: { ar: "ماذا تفعل الآن", en: "What to do now" },
  go_back: { ar: "رجوع", en: "Go back" },
  continue_anyway: { ar: "متابعة على مسؤوليتي", en: "Continue at my own risk" },
  continue_note: {
    ar: "سنتذكر اختيارك لهذا الموقع مدة 10 دقائق.",
    en: "We remember this choice for this site for 10 minutes.",
  },
  official_is: { ar: "العنوان الرسمي:", en: "The official address is:" },

  st_checking: { ar: "نتأكد الآن بفحص أعمق…", en: "Confirming with a deeper check…" },
  st_confirmed: { ar: "اكتمل الفحص العميق.", en: "Deeper check finished." },
  st_partial: {
    ar: "الفحص العميق لم يكتمل بعد. هذه نتيجة أولية.",
    en: "The deeper check is not finished. This result is provisional.",
  },
  st_offline: {
    ar: "تعذّر الوصول إلى خادم الفحص. هذه نتيجة فحص جهازك فقط.",
    en: "Could not reach the check server. This is your device's check only.",
  },
  st_disabled: {
    ar: "الفحص العميق متوقف من الإعدادات. هذه نتيجة فحص جهازك فقط.",
    en: "Deeper checks are turned off in settings. This is your device's check only.",
  },
  st_rate: { ar: "طلبات كثيرة. حاول بعد دقيقة.", en: "Too many requests. Try again in a minute." },
  st_perm: {
    ar: "لا يملك الامتداد إذن الاتصال بهذا الخادم. افتح الإعدادات واحفظ العنوان.",
    en: "The extension has no permission for this server. Open settings and save the address.",
  },
  degraded: { ar: "بعض الفحوص لم تكتمل.", en: "Some checks did not finish." },
  demo_data: { ar: "بيانات تجريبية", en: "DEMO DATA" },
  risk_by_arbiter: { ar: "درجة الخطر (من المحكّم)", en: "Risk score (from the arbiter)" },
  not_legal: {
    ar: "فحص آلي يساعدك على القرار ولا يضمن شيئًا. لن نطلب منك أي بيانات شخصية أو بنكية.",
    en: "An automated check to help you decide. It guarantees nothing. We never ask for personal or bank details.",
  },

  pop_this_page: { ar: "هذه الصفحة", en: "This page" },
  pop_unsupported: { ar: "لا يمكن فحص هذه الصفحة.", en: "This page cannot be checked." },
  pop_local_none: { ar: "فحص جهازك لم يلاحظ شيئًا في العنوان.", en: "Your device's check noticed nothing in the address." },
  pop_official: { ar: "العنوان ضمن النطاقات الرسمية المسجّلة لدينا لـ", en: "This address is on our verified list for" },
  pop_official_note: {
    ar: "تأكد دائمًا من العنوان قبل إدخال أي بيانات.",
    en: "Always check the address before you enter anything.",
  },
  pop_open_app: { ar: "افتح تطبيق عدسة الصقر", en: "Open the Falcon Lens app" },
  pop_settings: { ar: "الإعدادات", en: "Settings" },
  pop_local_only: { ar: "فحص الجهاز فقط", en: "Device check only" },
  pop_noted: { ar: "ملاحظة على العنوان", en: "A note on the address" },

  tip_checking: { ar: "جارٍ الفحص…", en: "Checking…" },
  tip_caution: { ar: "ابقَ حذرًا", en: "stay careful" },
  tip_local_only: { ar: "فحص الجهاز فقط", en: "device check only" },
  tip_note: { ar: "انتبه", en: "Take care" },

  opt_title: { ar: "إعدادات عدسة الصقر", en: "Falcon Lens settings" },
  opt_api: { ar: "عنوان خادم الفحص", en: "Check server address" },
  opt_api_help: {
    ar: "يجب أن يبدأ بـ https، ويُسمح بـ http للجهاز المحلي فقط.",
    en: "Must start with https. http is allowed for this computer only.",
  },
  opt_key: { ar: "مفتاح الخدمة (اختياري)", en: "API key (optional)" },
  opt_key_help: {
    ar: "يُحفظ على هذا الجهاز فقط ويُرسل إلى خادم الفحص وحده.",
    en: "Stored on this device only and sent to the check server alone.",
  },
  opt_web: { ar: "عنوان تطبيق الويب", en: "Web app address" },
  opt_server: { ar: "تأكيد النتيجة بفحص أعمق على الخادم", en: "Confirm results with a deeper server check" },
  opt_server_help: {
    ar: "عند الإيقاف يبقى الفحص على جهازك فقط ولا يُرسل أي عنوان.",
    en: "When off, checks stay on your device and no address is sent.",
  },
  opt_lang: { ar: "اللغة", en: "Language" },
  opt_save: { ar: "حفظ", en: "Save" },
  opt_test: { ar: "اختبار الاتصال", en: "Test connection" },
  opt_saved: { ar: "تم الحفظ.", en: "Saved." },
  opt_bad_url: { ar: "العنوان غير صالح.", en: "That address is not valid." },
  opt_denied: {
    ar: "لم يُمنح إذن الاتصال بهذا الخادم، فلم يُحفظ العنوان.",
    en: "Permission for this server was not granted, so the address was not saved.",
  },
  opt_test_ok: { ar: "الخادم يستجيب.", en: "The server responds." },
  opt_test_fail: { ar: "الخادم لا يستجيب.", en: "The server does not respond." },
  opt_privacy: {
    ar: "يُرسل الامتداد العنوان الذي يُفحص فقط. لا يُحفظ سجل تصفحك؛ تُحفظ النتائج في الذاكرة 10 دقائق ثم تُمحى.",
    en: "The extension sends only the address being checked. Your browsing history is not stored; results stay in memory for 10 minutes and are then erased.",
  },
} as const;

export type StringKey = keyof typeof S;

export const t = (key: StringKey, lang: Lang): string => S[key][lang];
export const verdictWord = (v: VerdictWord, lang: Lang): string => S[`v_${v}`][lang];
export const dirOf = (lang: Lang): "rtl" | "ltr" => (lang === "ar" ? "rtl" : "ltr");

/** One plain sentence per on-device signal. Brand names are inserted as text only. */
export function signalText(sig: LocalSignal, brand: BrandRef | undefined, lang: Lang): string {
  const name = brand ? (lang === "ar" ? brand.name_ar : brand.name_en) : "";
  const ar = lang === "ar";
  switch (sig.id) {
    case "brand_in_host":
      return ar
        ? `العنوان يستخدم اسم «${name}» لكنه ليس موقعها الرسمي.`
        : `The address uses the name "${name}" but is not its official site.`;
    case "brand_lookalike":
      return ar
        ? `العنوان يشبه اسم «${name}» مع تغيير حرف أو رقم.`
        : `The address looks like "${name}" with a letter or digit changed.`;
    case "homograph":
      return ar
        ? `العنوان يقلّد اسم «${name}» بأحرف من أبجدية أخرى.`
        : `The address imitates "${name}" with letters from another alphabet.`;
    case "mixed_script":
      return ar ? "اسم الموقع يخلط أحرفًا من أبجديات مختلفة." : "The site name mixes letters from different alphabets.";
    case "ip_host":
      return ar ? "العنوان أرقام فقط بدل اسم موقع." : "The address is only numbers instead of a site name.";
    case "userinfo":
      return ar
        ? "العنوان يخفي الموقع الحقيقي بعد علامة @."
        : "The address hides the real site after an @ sign.";
    case "free_host":
      return ar
        ? "الموقع على استضافة مجانية أو رابط مؤقت يستطيع أي شخص إنشاءه."
        : "The site is on free hosting or a temporary link that anyone can create.";
  }
}
