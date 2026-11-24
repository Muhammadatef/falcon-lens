/**
 * "What THIS check found": one short written line per evidence code, shown on the Check page and the check trace.
 * It mirrors the spoken lines of lib/voice-script.ts (same evidence codes; formal Arabic here, Emirati only in speech).
 *
 * Values come from the evidence of the run: ages in days, a brand name from the registry table, a defanged host.
 * Anything else the evidence carries (free text, display strings) is never printed by this module, so an attacker's
 * text can only reach the screen through the usual escaped React paths, never through here.
 */
import type { Evidence, Lang, Tier } from "./contracts";
import { BRAND_NAMES } from "./brand-names";
import { defang } from "./defang";

type Ctx = { lang: Lang; brand: string | null; host: string | null; days: number | null; extra: string | null };
type Line = { ar: (c: Ctx) => string; en: (c: Ctx) => string };
const L = (ar: string | ((c: Ctx) => string), en: string | ((c: Ctx) => string)): Line => ({ ar: typeof ar === "string" ? () => ar : ar, en: typeof en === "string" ? () => en : en });

const dayWord = (n: number) => (n === 0 ? "اليوم" : n === 1 ? "قبل يوم واحد" : n === 2 ? "قبل يومين" : n <= 10 ? `قبل ${n} أيام` : `قبل ${n} يوماً`);
const dayWordEn = (n: number) => (n === 0 ? "today" : n === 1 ? "1 day ago" : `${n} days ago`);

/** Every code that has a written line. Keep in step with the spoken table (a unit test checks the codes are a subset). */
export const FINDING_LINES: Readonly<Record<string, Line>> = {
  "rep.openphish": L("الرابط مسجّل في قائمة احتيال معروفة", "The link is on a known scam list"),
  "rep.urlhaus": L("الرابط مسجّل في قائمة احتيال معروفة", "The link is on a known scam list"),
  "rep.gsb": L("الرابط مسجّل في قائمة احتيال معروفة", "The link is on a known scam list"),
  "rep.feed_hit": L("الرابط مسجّل في قائمة احتيال معروفة", "The link is on a known scam list"),
  "url.combosquat": L((c) => (c.brand ? `العنوان يضيف كلمة إلى اسم ${c.brand}` : "العنوان يضيف كلمة إلى اسم جهة معروفة"), (c) => (c.brand ? `The address adds a word to the name of ${c.brand}` : "The address adds a word to a well-known name")),
  "url.typosquat": L("العنوان قريب جداً من اسم جهة معروفة بحروف مغيّرة", "The address is a near-copy of a well-known name"),
  "url.homograph": L("العنوان يستخدم حروفاً متشابهة الشكل للتمويه", "The address uses look-alike letters to deceive"),
  "url.bidi_or_zero_width": L("العنوان يحوي رموزاً مخفية", "The address contains hidden characters"),
  "url.raw_ip_host": L("العنوان أرقام بدل اسم موقع", "The address is a number instead of a site name"),
  "url.free_host_or_tunnel": L("الموقع على استضافة مجانية أو نفق مؤقت", "The site sits on free hosting or a temporary tunnel"),
  "url.brand_in_subdomain_or_path": L("اسم جهة معروفة موضوع في العنوان والموقع ليس لها", "A well-known name is placed in the address, but the site is not theirs"),
  "url.userinfo_trick": L("العنوان يحوي حيلة تخفي الوجهة الحقيقية", "The address uses a trick to hide its real destination"),
  "url.open_redirect_abuse": L("الرابط يحوّلك إلى موقع آخر", "The link bounces you to another site"),
  "url.redirect_chain": L("الرابط يمر بعدة تحويلات", "The link goes through several redirects"),
  "url.shortener": L("الرابط مختصر ويخفي وجهته", "The link is shortened and hides its destination"),
  "domain.age_days": L((c) => `النطاق مسجّل ${dayWord(c.days ?? 0)}`, (c) => `The domain was registered ${dayWordEn(c.days ?? 0)}`),
  "domain.cert_age_days": L((c) => `شهادة الموقع صدرت ${dayWord(c.days ?? 0)}`, (c) => `The site certificate was issued ${dayWordEn(c.days ?? 0)}`),
  "page.cred_form": L("الصفحة تطلب كلمة المرور ورمز التحقق", "The page asks for a password and a code"),
  "page.cross_origin_post": L((c) => (c.host ? `ما تكتبه يُرسل إلى خادم آخر: ${c.host}` : "ما تكتبه يُرسل إلى خادم آخر"), (c) => (c.host ? `What you type is sent to another server: ${c.host}` : "What you type is sent to another server")),
  "page.cloaking": L("الصفحة تعرض محتوى مختلفاً لأدوات الفحص", "The page shows different content to scanners"),
  "page.hotlinked_brand_assets": L("الصفحة تسحب صور جهة معروفة من موقعها الأصلي", "The page pulls a well-known brand's images from its real site"),
  "visual.favicon_match_brand": L("أيقونة الموقع منسوخة من جهة معروفة", "The site icon is copied from a well-known brand"),
  "brand.claimed_not_owned": L((c) => (c.brand ? `تدّعي أنها ${c.brand} والنطاق ليس من نطاقاتها الرسمية` : "تدّعي أنها جهة معروفة والنطاق ليس من نطاقاتها الرسمية"), (c) => (c.brand ? `It claims to be ${c.brand}, but the domain is not one of its official domains` : "It claims to be a well-known body, but the domain is not one of its official domains")),
  "message.brand_url_mismatch": L("الرابط ليس من الجهة التي تذكرها الرسالة", "The link is not from the organisation the message names"),
  "message.brand_mention": L((c) => (c.brand ? `الرسالة تذكر اسم ${c.brand}` : "الرسالة تذكر اسم جهة معروفة"), (c) => (c.brand ? `The message names ${c.brand}` : "The message names a well-known body")),
  "message.scam_intent": L("الرسالة تطلب رمزاً أو مالاً بأسلوب الاحتيال", "The message asks for a code or money the way scams do"),
  "message.script_match": L("الرسالة تشبه نص احتيال معروفاً", "The message matches a known scam script"),
  "message.contains_url": L((c) => (c.host ? `في الرسالة رابط: ${c.host}` : "في الرسالة رابط"), (c) => (c.host ? `The message contains a link: ${c.host}` : "The message contains a link")),
  "message.contains_phone": L("في الرسالة رقم هاتف للاتصال", "The message contains a phone number to call"),
  "message.rule.urgency": L("الرسالة تستعجلك", "The message rushes you"),
  "message.rule.secrecy": L("الرسالة تطلب منك كتمان الأمر", "The message asks you to keep it secret"),
  "message.rule.otp_request": L("الرسالة تطلب رمز التحقق", "The message asks for your verification code"),
  "message.rule.remote_access": L("الرسالة تطلب تثبيت تطبيق أو مشاركة الشاشة", "The message asks you to install an app or share your screen"),
  "message.rule.payment": L("الرسالة تطلب دفعاً أو تحويل مال", "The message asks you to pay or transfer money"),
  "message.rule.authority": L("الرسالة تنتحل صفة جهة رسمية", "The message claims to come from an official body"),
  "message.rule.prize": L("الرسالة تعدك بجائزة", "The message promises you a prize"),
  "message.rule.job": L("الرسالة تعرض وظيفة مشبوهة", "The message offers a dubious job"),
  "message.rule.investment": L("الرسالة تعرض ربحاً سريعاً", "The message offers fast profit"),
  "message.rule.delivery_fee": L("الرسالة تطلب رسوم توصيل", "The message asks for a delivery fee"),
  "message.rule.fine": L("الرسالة تتحدث عن مخالفة وتطلب سداداً", "The message talks about a fine and asks for payment"),
  "email.auth_fail": L((c) => `فشل التحقق من هوية المرسل${c.extra ? ` (${c.extra})` : ""}`, (c) => `The sender identity check failed${c.extra ? ` (${c.extra})` : ""}`),
  "email.display_name_impersonation": L((c) => (c.brand ? `اسم المرسل يدّعي ${c.brand} والعنوان ليس لها` : "اسم المرسل يدّعي جهة معروفة والعنوان ليس لها"), (c) => (c.brand ? `The sender name claims ${c.brand}, but the address is not theirs` : "The sender name claims a well-known body, but the address is not theirs")),
  "email.reply_to_mismatch": L((c) => (c.host ? `الردود تذهب إلى عنوان آخر: ${c.host}` : "الردود تذهب إلى عنوان غير عنوان المرسل"), (c) => (c.host ? `Replies go to a different address: ${c.host}` : "Replies go to a different address than the sender's")),
  "email.return_path_mismatch": L("مسار الإرجاع يختلف عن عنوان المرسل", "The return path differs from the sender's address"),
  "email.link_text_mismatch": L("الرابط المكتوب يختلف عن الرابط الحقيقي", "The link shown differs from the real link"),
  "email.attachment": L("المرفق قد يحمل رابطاً أو محتوى مشبوهاً", "The attachment may carry a link or suspicious content"),
  "image.qr_decoded": L((c) => (c.host ? `في الصورة رمز QR يقود إلى: ${c.host}` : "في الصورة رمز QR يقود إلى رابط"), (c) => (c.host ? `The image has a QR code leading to: ${c.host}` : "The image has a QR code leading to a link")),
  "qr.ae": L("في الصورة رمز QR يقود إلى رابط", "The image has a QR code leading to a link"),
  "sandbox.not_rendered": L("تعذّر فتح الصفحة كاملة", "The page could not be fully opened"),
  "sandbox.unreachable": L("تعذّر فتح الصفحة كاملة", "The page could not be fully opened"),
  "sandbox.partial_render": L("تعذّر فتح الصفحة كاملة", "The page could not be fully opened"),
  "page.truncated": L("تعذّر فتح الصفحة كاملة", "The page could not be fully opened"),
  "page.static_fallback": L("تعذّر فتح الصفحة كاملة", "The page could not be fully opened"),
  "page.cloaking_inconclusive": L("تعذّر فتح الصفحة كاملة", "The page could not be fully opened"),
};
export const NO_FINDING = { ar: "لا شيء لافت في هذه الطبقة", en: "Nothing notable at this layer" } as const;

/** Codes that are informational (weight 0) but still worth a line: what is in the message, what the image holds. */
const INFO_CODES: ReadonlySet<string> = new Set(["message.contains_url", "message.contains_phone", "message.brand_mention", "image.qr_decoded", "email.attachment"]);
const INCOMPLETE: ReadonlySet<string> = new Set(["sandbox.not_rendered", "sandbox.unreachable", "sandbox.partial_render", "page.truncated", "page.static_fallback", "page.cloaking_inconclusive"]);
const BRAND_ID = /^[a-z0-9_]{2,40}$/;
const AUTH = new Set(["spf", "dkim", "dmarc"]);

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const brandName = (id: unknown, lang: Lang): string | null => (typeof id === "string" && BRAND_ID.test(id) && Object.hasOwn(BRAND_NAMES, id) ? BRAND_NAMES[id]![lang] : null);
/** A defanged host from a URL-ish string; only host characters survive (no markup, no path, no query). */
export function safeHost(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const host = defang(value.trim()).replace(/^[a-z][a-z0-9+.-]*:\/\//i, "").split(/[/?#\s]/)[0] ?? "";
  const clean = host.replace(/[^A-Za-z0-9.[\]-]/g, "").slice(0, 64);
  return clean.length >= 3 ? clean : null;
}

function context(e: Evidence, lang: Lang, verdictBrand: string | null): Ctx {
  const o = e.observed;
  let brand = verdictBrand;
  let host: string | null = null;
  let extra: string | null = null;
  let days: number | null = null;
  if (typeof o === "number" && Number.isFinite(o)) days = Math.max(0, Math.round(o));
  if (isObj(o)) {
    if (typeof o.brand_id === "string") brand = brandName(o.brand_id, lang);
    if (Array.isArray(o.brands)) brand = o.brands.map((b) => brandName(b, lang)).find((x): x is string => !!x) ?? brand;
    if (Array.isArray(o.urls)) host = safeHost(o.urls[0]);
    host = host ?? safeHost(o.reply_to_domain) ?? safeHost(o.host);
    if (Array.isArray(o.failures)) extra = o.failures.filter((f): f is string => typeof f === "string" && AUTH.has(f.toLowerCase())).map((f) => f.toUpperCase()).join(" / ") || null;
  }
  if (e.signal === "page.cross_origin_post") host = safeHost(o);
  return { lang, brand, host, days, extra };
}

/** The written line for one evidence item, or null when it has none (unknown code, trust, zero weight, errored). */
export function findingLine(e: Evidence, lang: Lang, verdictBrandId: string | null = null): string | null {
  const line = FINDING_LINES[e.signal];
  if (!line) return null;
  if (INCOMPLETE.has(e.signal)) return line[lang](context(e, lang, null));
  if (e.error || e.polarity === "trust") return null;
  if (!(e.weight > 0) && !INFO_CODES.has(e.signal)) return null;
  if (e.signal === "domain.age_days" || e.signal === "domain.cert_age_days") {
    if (typeof e.observed !== "number" || !Number.isFinite(e.observed) || e.observed > 100) return null;
  }
  return line[lang](context(e, lang, brandName(verdictBrandId, lang)));
}

/** Up to `max` strongest findings of one tier; an empty list means the tier found nothing speakable. */
export function tierFindingLines(evidence: readonly Evidence[], tier: Tier, lang: Lang, verdictBrandId: string | null = null, max = 3): string[] {
  const out: string[] = [];
  const ranked = evidence.filter((e) => e.tier === tier).sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  for (const e of ranked) {
    const t = findingLine(e, lang, verdictBrandId);
    if (t && !out.includes(t)) out.push(t);
    if (out.length === max) break;
  }
  return out;
}
