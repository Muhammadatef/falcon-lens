/**
 * Single source of truth for every SPOKEN line of the "Hey Falcon" voice assistant.
 *
 * - Screen text stays formal MSA (lib/i18n-voice.ts). Speech is Emirati Arabic ("ar_ae") or plain English ("en").
 * - Every spoken output is a concatenation of a FINITE set of pre-recordable clips. A clip id is `<voiceLang>.<key>`,
 *   for example `ar_ae.found.3` or `en.result.dangerous`. Numbers are written out in words, never digits.
 * - Both agents are narrated: the Investigator (`investigator.*`) and the Sentinel (`sentinel.*`).
 * - Product rules: never the word "safe" / «آمن»; the lowest verdict is "no warning signs" plus a caution;
 *   nothing asks for personal, banking or ID details; reporting is generic ("the official channels"), no phone numbers.
 * - packages/falcon_core/src/falcon_core/i18n/voice_script.yaml is generated from this file
 *   (node scripts/gen-voice-script.mjs) and a unit test fails if they drift. Emirati lines await native review
 *   (docs/VOICE_SCRIPT_REVIEW.md).
 *
 * No imports with runtime effect: the generator loads this file directly with Node.
 */
export type VoiceLang = "ar_ae" | "en";
export type SpeechVerdict = "dangerous" | "suspicious" | "no_warning_signs";

export const VOICE_LANGS: readonly VoiceLang[] = ["ar_ae", "en"];
/** Page language ("ar" | "en") to the spoken script language. */
export const toVoiceLang = (lang: "ar" | "en"): VoiceLang => (lang === "ar" ? "ar_ae" : "en");

type Pair = readonly [ar_ae: string, en: string];

const N = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

const FOUND: readonly Pair[] = [
  ["لقيت مسج واحد.", "I found one message."],
  ["لقيت مسجين.", "I found two messages."],
  ["لقيت ثلاث مسجات.", "I found three messages."],
  ["لقيت أربع مسجات.", "I found four messages."],
  ["لقيت خمس مسجات.", "I found five messages."],
  ["لقيت ست مسجات.", "I found six messages."],
  ["لقيت سبع مسجات.", "I found seven messages."],
  ["لقيت ثمان مسجات.", "I found eight messages."],
  ["لقيت تسع مسجات.", "I found nine messages."],
  ["لقيت عشر مسجات.", "I found ten messages."],
];
const ORD_AR = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر"];
const ORD_EN = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"];
/** "of N" for N = 2..10 (index 0 is N = 2). */
const OF: readonly Pair[] = [
  ["من اثنين.", "of two."],
  ["من ثلاث.", "of three."],
  ["من أربع.", "of four."],
  ["من خمس.", "of five."],
  ["من ست.", "of six."],
  ["من سبع.", "of seven."],
  ["من ثمان.", "of eight."],
  ["من تسع.", "of nine."],
  ["من عشر.", "of ten."],
];
/** Counts per verdict, for N = 1..10, phrased as the subject of a short sentence. */
const COUNT_AR = ["مسج واحد", "مسجين", "ثلاث مسجات", "أربع مسجات", "خمس مسجات", "ست مسجات", "سبع مسجات", "ثمان مسجات", "تسع مسجات", "عشر مسجات"];
const COUNT_EN = ["One message", "Two messages", "Three messages", "Four messages", "Five messages", "Six messages", "Seven messages", "Eight messages", "Nine messages", "Ten messages"];
const SUM_AR = { dangerous: "منها خطر.", suspicious: "منها مشكوك فيها.", clear: "ما فيها علامات تحذير.", failed: "ما قدرت أشيّكها." };
const SUM_EN = (n: number) => ({
  dangerous: n === 1 ? "is dangerous." : "are dangerous.",
  suspicious: n === 1 ? "looks suspicious." : "look suspicious.",
  clear: "showed no warning signs.",
  failed: "could not be checked.",
});
export type SummaryKind = "dangerous" | "suspicious" | "clear" | "failed";
const SUMMARY_KINDS: readonly SummaryKind[] = ["dangerous", "suspicious", "clear", "failed"];

/** Exact number words 0..100 (Emirati spoken Arabic; English). */
const NUM_AR = ["صفر", "واحد", "ثنين", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة", "إحداعش", "اثناعش", "ثلاثطعش", "أربعطعش", "خمسطعش", "ستطعش", "سبعطعش", "ثمانطعش", "تسعطعش"];
const NUM_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS_AR = ["عشرين", "ثلاثين", "أربعين", "خمسين", "ستين", "سبعين", "ثمانين", "تسعين"];
const TENS_AR_AND = ["وعشرين", "وثلاثين", "وأربعين", "وخمسين", "وستين", "وسبعين", "وثمانين", "وتسعين"];
const TENS_EN = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
function numberWords(n: number): Pair {
  if (n < 20) return [NUM_AR[n]!, NUM_EN[n]!];
  if (n === 100) return ["مية", "one hundred"];
  const t = Math.floor(n / 10) - 2;
  const u = n % 10;
  return u === 0 ? [TENS_AR[t]!, TENS_EN[t]!] : [`${NUM_AR[u]} ${TENS_AR_AND[t]}`, `${TENS_EN[t]}-${NUM_EN[u]}`];
}

/**
 * Scam-safety FAQ: pre-written answers, never generated. The id is `faq.<name>`; the Python matcher
 * (falcon_core/voice/faq.py) returns the name and the web plays the clip. Scams only, no phone numbers or links.
 */
export const FAQ: readonly (readonly [name: string, ar_ae: string, en: string])[] = [
  ["otp", "البنك ما يطلب منك الرمز أبداً. لا تعطيه لأي أحد، حتى لو قال إنه من البنك.", "Your bank never asks for your one-time code. Never share it with anyone, even if they say they are the bank."],
  ["clicked_link", "لا تخاف، بس تصرّف بسرعة. لا تدخل أي بيانات، وكلّم بنكك، وغيّر أرقامك السرية.", "Don't panic, but act fast. Don't enter any details, call your bank, and change your passcodes."],
  ["shared_card", "كلّم بنكك الحين على الرقم اللي ورا بطاقتك، وقل لهم يوقفون البطاقة. وبعدها بلّغ عن اللي صار.", "Call your bank right now on the number on your card and ask them to block it. Then report what happened."],
  ["fake_police", "الشرطة ما تطلب فلوس بالتلفون. سكّر المكالمة، وبلّغ من القنوات الرسمية.", "The police never ask for money over the phone. Hang up, and report it through the official channels."],
  ["parcel_fee", "رسالة رسوم التوصيل غالباً نصب. لا تضغط الرابط، واسأل شركة الشحن من تطبيقها الرسمي.", "A delivery fee message is often a scam. Don't tap the link, and ask the courier through its official app."],
  ["prize", "ما تربح جايزة في سحب ما دخلته. لا ترد على الرسالة، ولا تدفع رسوم عشان تستلمها.", "You can't win a draw you never entered. Don't reply, and never pay a fee to collect a prize."],
  ["investment", "أي عرض يوعدك بربح سريع ومضمون هو نصب غالباً. لا تحوّل فلوس، واسأل جهة مرخصة.", "An offer promising fast, guaranteed profit is usually a scam. Don't transfer money, and ask a licensed firm."],
  ["fake_job", "الوظيفة الحقيقية ما تطلب منك فلوس قبل لا تبدأ. تأكد من الشركة من موقعها الرسمي.", "A real job never asks you to pay before you start. Check the company on its official website."],
  ["report", "بلّغ من القنوات الرسمية للجهات المختصة في الدولة. واحتفظ بالرسالة، ولا تحذفها.", "Report it through the official channels of the authorities. Keep the message, and don't delete it."],
  ["about", "أنا عدسة الصقر. أفحص الرسائل والروابط، وأقول لك إذا فيها علامات نصب، وأعطيك الأدلة.", "I'm Falcon Lens. I check messages and links for scam signs, and show you the evidence."],
  ["agents", "بصير يفحص الرسالة، ودرع يربط البلاغات المتشابهة. وما يطلع أي بلاغ أو تنبيه للجهات من غير موافقة شخص.", "Baseer checks the message, Dir links similar reports. No alert or report goes out without a person's approval."],
  ["data_stored", "صوتك ينعالج على سيرفرنا وما ينحفظ. من الفحص نحفظ بس نسخة معطّلة من الرابط والأدلة ونتيجة الفحص. ونص رسالتك ما ينحفظ، إلا إذا اخترت تبلّغ عنها.", "Your voice is processed on our own server and isn't kept. From a check we keep only a defanged copy of the link, the evidence and the result. Your message text isn't kept unless you choose to report it."],
  ["bank_link", "البنك ما يرسل لك رابط عشان تحدّث بياناتك. افتح تطبيق البنك بنفسك، أو كلّمه.", "Your bank doesn't send links to update your details. Open your bank app yourself, or call it."],
  ["friend_money", "إذا واحد من ربعك يطلب فلوس برسالة، كلّمه بالتلفون أول. يمكن حسابه انسرق.", "If a friend asks for money by message, call them first. Their account may have been hacked."],
  ["relative_urgent", "اتصال عن قريب محتاج فلوس بسرعة؟ سكّر، وكلّم قريبك على رقمه اللي تعرفه.", "A call saying a relative urgently needs money? Hang up and call your relative on the number you know."],
  ["remote_access", "لا تحمّل برنامج ولا تشارك شاشتك مع أحد يتصل فيك. هذي طريقة النصابين عشان يدخلون جهازك.", "Never install an app or share your screen for a caller. That's how scammers get into your phone."],
  ["qr_code", "لا تمسح رمز كيو آر من مصدر ما تعرفه. افتح الموقع بنفسك بدل ما تمسحه.", "Don't scan a QR code from a source you don't know. Open the website yourself instead."],
  ["online_shop", "الأسعار الرخيصة مرة ممكن تكون فخ. اشتر من مواقع تعرفها، وادفع بطريقة فيها حماية.", "Prices that look too good can be a trap. Buy from sites you know, and pay by a method with protection."],
  ["sent_money", "كلّم بنكك فوراً، يمكن يقدرون يوقفون التحويل. وبلّغ من القنوات الرسمية، وكل ما أسرعت أحسن.", "Call your bank immediately, they may be able to stop the transfer. Then report it through the official channels."],
  ["shared_login", "غيّر رقمك السري الحين، وكلّم بنكك. وفعّل التحقق بخطوتين.", "Change your passcode right now and call your bank. Then turn on two-step verification."],
  ["spot_scam", "علامات النصب: استعجال، وتهديد، ورابط غريب، وطلب رمز أو فلوس. إذا شفت وحدة منها، وقّف.", "Scam signs: urgency, threats, a strange link, or a request for a code or money. If you see one, stop."],
  ["limits", "ما فيه نظام يكشف كل شي. أنا أعطيك علامات وأدلة، وإذا شكيت، كلّم بنكك.", "No system catches everything. I show you signs and evidence, and if in doubt, call your bank."],
];
/** Polite redirects for anything outside scams; the web rotates through them. */
export const OFF_TOPIC: readonly Pair[] = [
  ["هذا خارج شغلي. أنا أساعدك تكشف رسائل النصب. قل: يا صقر، افحص رسائلي.", "That's outside what I do. I help you spot scam messages. Say: Hey Falcon, check my messages."],
  ["ما أقدر أساعدك في هذا. أنا متخصص بالنصب والاحتيال. انسخ رسالتك، وقل: يا صقر، افحصها.", "I can't help with that. I only handle scams and fraud. Copy your message and say: Hey Falcon, check it."],
  ["سؤالك حلو، بس مو من اختصاصي. اسألني عن رسائل النصب، أو قل: يا صقر، ساعدني.", "Good question, but not my area. Ask me about scam messages, or say: Hey Falcon, help me."],
];
export const FAQ_PREFIXES = ["faq.", "offtopic.", "ack."] as const;
/** Keys that belong to the FAQ script file (voice_faq.yaml), not to voice_script.yaml. */
export const isFaqKey = (key: string): boolean => FAQ_PREFIXES.some((p) => key.startsWith(p));
/** Spoken the moment speech ends, before the transcript returns. */
export const ACK_KEY = "ack.moment";
export const offTopicKey = (i: number): string => `offtopic.${(((Math.floor(i) % OFF_TOPIC.length) + OFF_TOPIC.length) % OFF_TOPIC.length) + 1}`;
export const faqKey = (name: string): string => `faq.${name}`;
/** The FAQ answer keys the API may return (validated before anything is played). */
export const FAQ_KEYS: readonly string[] = FAQ.map(([n]) => faqKey(n));


/**
 * What THIS check found: one short spoken line per evidence code (the real signal names from falcon_core). A code that
 * is not in this table is never spoken (no raw or untrusted text ever reaches speech). Several codes may share a line.
 */
type Finding = readonly [codes: readonly string[], key: string, ar_ae: string, en: string];
const FINDINGS: readonly Finding[] = [
  [["rep.openphish", "rep.urlhaus", "rep.gsb", "rep.feed_hit"], "find.listed", "الرابط مسجّل في قائمة نصب معروفة.", "The link is on a known scam list."],
  [["url.combosquat"], "find.combosquat", "العنوان يضيف كلمة لاسم جهة معروفة.", "The address adds a word to a well-known name."],
  [["url.typosquat"], "find.typosquat", "العنوان قريب مرة من اسم جهة معروفة، بس حروفه مغيّرة.", "The address is a near-copy of a well-known name."],
  [["url.homograph"], "find.homograph", "العنوان فيه حروف تشبه غيرها عشان تخدعك.", "The address uses look-alike letters to fool you."],
  [["url.bidi_or_zero_width"], "find.hidden_chars", "العنوان فيه رموز مخفية.", "The address contains hidden characters."],
  [["url.raw_ip_host"], "find.ip_host", "العنوان أرقام بدل اسم موقع.", "The address is a number instead of a site name."],
  [["url.free_host_or_tunnel"], "find.free_host", "الموقع على استضافة مجانية أو نفق مؤقت.", "The site sits on free hosting or a temporary tunnel."],
  [["url.brand_in_subdomain_or_path"], "find.brand_in_path", "اسم جهة معروفة محطوط في العنوان، والموقع مو لها.", "A well-known name is placed in the address, but the site is not theirs."],
  [["url.userinfo_trick"], "find.userinfo", "العنوان فيه حيلة تخفي الوجهة الحقيقية.", "The address uses a trick to hide where it really goes."],
  [["url.open_redirect_abuse"], "find.open_redirect", "الرابط يحوّلك لموقع ثاني.", "The link bounces you to another site."],
  [["url.redirect_chain"], "find.redirects", "الرابط يمر بعدة تحويلات.", "The link goes through several redirects."],
  [["url.shortener"], "find.shortener", "الرابط مختصر ويخفي وجهته.", "The link is shortened and hides its destination."],
  [["page.cross_origin_post"], "find.cross_post", "اللي تكتبه يروح لخادم ثاني.", "What you type goes to a different server."],
  [["page.cloaking"], "find.cloaking", "الصفحة تعرض شي مختلف لأدوات الفحص.", "The page shows something different to scanners."],
  [["page.hotlinked_brand_assets"], "find.hotlinked", "الصفحة تسحب صور جهة معروفة من موقعها الأصلي.", "The page pulls a well-known brand's images from its real site."],
  [["visual.favicon_match_brand"], "find.favicon", "أيقونة الموقع منسوخة من جهة معروفة.", "The site icon is copied from a well-known brand."],
  [["message.brand_url_mismatch"], "find.brand_url_mismatch", "الرابط مو من الجهة اللي تذكرها الرسالة.", "The link is not from the organisation the message names."],
  [["message.scam_intent"], "find.scam_intent", "الرسالة تطلب رمز أو فلوس بأسلوب النصابين.", "The message asks for a code or money the way scammers do."],
  [["message.script_match"], "find.script_match", "الرسالة تشبه نص نصب معروف.", "The message matches a known scam script."],
  [["message.rule.urgency"], "find.urgency", "الرسالة تستعجلك.", "The message rushes you."],
  [["message.rule.secrecy"], "find.secrecy", "الرسالة تطلب منك تخبي الموضوع.", "The message asks you to keep it secret."],
  [["message.rule.otp_request"], "find.otp_request", "الرسالة تطلب رمز التحقق.", "The message asks for your verification code."],
  [["message.rule.remote_access"], "find.remote_access", "الرسالة تطلب تحميل برنامج أو مشاركة شاشتك.", "The message asks you to install an app or share your screen."],
  [["message.rule.payment"], "find.payment_request", "الرسالة تطلب دفع أو تحويل فلوس.", "The message asks you to pay or transfer money."],
  [["message.rule.authority"], "find.authority", "الرسالة تدّعي إنها من جهة رسمية.", "The message claims to come from an official body."],
  [["message.rule.prize"], "find.prize", "الرسالة توعدك بجايزة.", "The message promises you a prize."],
  [["message.rule.job"], "find.job", "الرسالة تعرض وظيفة مشبوهة.", "The message offers a dubious job."],
  [["message.rule.investment"], "find.investment", "الرسالة تعرض ربح سريع.", "The message offers fast profit."],
  [["message.rule.delivery_fee"], "find.delivery_fee", "الرسالة تطلب رسوم توصيل.", "The message asks for a delivery fee."],
  [["message.rule.fine"], "find.fine", "الرسالة تتكلم عن مخالفة وتطلب دفع.", "The message talks about a fine and asks for payment."],
  [["email.auth_fail"], "find.email_auth", "الإيميل فشل في فحص هوية المرسل.", "The email failed the sender identity check."],
  [["email.display_name_impersonation"], "find.display_spoof", "اسم المرسل يتظاهر بجهة معروفة.", "The sender name pretends to be a well-known body."],
  [["email.reply_to_mismatch"], "find.reply_to", "الرد يروح لعنوان غير عنوان المرسل.", "Replies go to a different address than the sender's."],
  [["email.link_text_mismatch"], "find.link_text", "الرابط المكتوب غير الرابط الحقيقي.", "The link shown is not the real link."],
  [["image.qr_decoded"], "find.qr_link", "في الصورة رمز كيو آر يودّي لرابط.", "The image has a QR code that leads to a link."],
  [["message.contains_url"], "find.contains_url", "في الرسالة رابط.", "The message contains a link."],
  [["message.contains_phone"], "find.contains_phone", "في الرسالة رقم تتصل عليه.", "The message has a number to call."],
  [["email.return_path_mismatch"], "find.return_path", "مسار الإرجاع غير عنوان المرسل.", "The return path differs from the sender's address."],
  [["email.attachment"], "find.attachment", "المرفق ممكن يحمل رابط أو شي مشبوه.", "The attachment may carry a link or something suspicious."],
];
/** The page could not be fully opened: said even when it carries no weight. */
const INCOMPLETE_CODES: readonly string[] = ["sandbox.not_rendered", "sandbox.unreachable", "sandbox.partial_render", "page.truncated", "page.static_fallback", "page.cloaking_inconclusive"];
/** Brands that may be spoken by name (invented demo brand plus a few registry brands); any other brand is spoken as "a well-known body". */
const BRAND_CLIPS: readonly (readonly [id: string, ar_ae: string, en: string])[] = [
  ["falcon_demo_bank", "بنك الصقر التجريبي", "Falcon Demo Bank"],
  ["emirates_post", "بريد الإمارات", "Emirates Post"],
  ["etisalat_by_eand", "اتصالات", "Etisalat"],
  ["salik", "سالك", "Salik"],
  ["dewa", "كهرباء ومياه دبي", "Dubai Electricity and Water"],
  ["fab", "بنك أبوظبي الأول", "First Abu Dhabi Bank"],
  ["adcb", "بنك أبوظبي التجاري", "Abu Dhabi Commercial Bank"],
  ["emirates_nbd", "بنك الإمارات دبي الوطني", "Emirates NBD"],
  ["mashreq", "بنك المشرق", "Mashreq"],
  ["rakbank", "بنك رأس الخيمة الوطني", "RAKBANK"],
  ["uae_pass", "الهوية الرقمية", "UAE PASS"],
];
const BRAND_IDS: ReadonlySet<string> = new Set(BRAND_CLIPS.map(([id]) => id));
/** Informational codes (weight 0) that still earn a spoken line. */
const INFO_CODES: readonly string[] = ["message.contains_url", "message.contains_phone", "image.qr_decoded", "email.attachment"];
/** Every evidence code that has a spoken line (the written table in lib/findings.ts must cover all of them). */
export const SPOKEN_CODES: readonly string[] = [...FINDINGS.flatMap(([codes]) => codes), ...INCOMPLETE_CODES, "domain.age_days", "domain.cert_age_days", "brand.claimed_not_owned", "page.cred_form"];
const CODE_KEY: ReadonlyMap<string, string> = new Map(FINDINGS.flatMap(([codes, key]) => codes.map((c) => [c, key] as const)));
/** What a credential form asked for, by field kind (the real kinds of falcon_core cascade/page.py). */
const CRED_LINES: readonly (readonly [key: string, ar_ae: string, en: string])[] = [
  ["card", "الصفحة تطلب بيانات بطاقتك.", "The page asks for your card details."],
  ["eid", "الصفحة تطلب رقم هويتك الإماراتية.", "The page asks for your Emirates ID number."],
  ["uae_pass", "الصفحة تطلب بيانات الهوية الرقمية.", "The page asks for your digital identity login."],
  ["pin", "الصفحة تطلب الرقم السري.", "The page asks for your PIN."],
  ["password_otp", "الصفحة تطلب كلمة السر والرمز.", "The page asks for a password and a code."],
  ["password", "الصفحة تطلب كلمة السر.", "The page asks for a password."],
  ["otp", "الصفحة تطلب رمز التحقق.", "The page asks for a verification code."],
  ["generic", "الصفحة تطلب بيانات دخول أو بيانات حساسة.", "The page asks for login or sensitive details."],
];
const CRED_KINDS = new Set(["password", "card", "cvv", "otp", "pin", "emirates_id", "uae_pass", "card_expiry"]);
/** The clip for what the page really asked, from observed.field_kinds; the generic line when the kinds are unknown. */
export function credFormKey(observed: unknown): string {
  const raw = isObjLike(observed) && Array.isArray(observed.field_kinds) ? observed.field_kinds : [];
  const k = new Set(raw.filter((x): x is string => typeof x === "string" && CRED_KINDS.has(x)));
  if (k.has("card") || k.has("cvv") || k.has("card_expiry")) return "find.cred.card";
  if (k.has("emirates_id")) return "find.cred.eid";
  if (k.has("uae_pass")) return "find.cred.uae_pass";
  if (k.has("pin")) return "find.cred.pin";
  if (k.has("password") && k.has("otp")) return "find.cred.password_otp";
  if (k.has("password")) return "find.cred.password";
  if (k.has("otp")) return "find.cred.otp";
  return "find.cred.generic";
}
/** Day counts that have their own wording (0, 1, 2); other counts up to 100 use "before N days" with the exact number clip. */
const AGE_SPECIAL: readonly Pair[] = [["اليوم.", "today."], ["قبل يوم واحد.", "one day ago."], ["قبل يومين.", "two days ago."]];

export const ARBITER_VERDICTS = ["dangerous", "suspicious", "no_warning_signs", "could_not_check"] as const;

function build(): Record<VoiceLang, Record<string, string>> {
  const ar: Record<string, string> = {};
  const en: Record<string, string> = {};
  const put = (key: string, a: string, e: string) => {
    ar[key] = a;
    en[key] = e;
  };
  put("wake.ack", "هلا، سامعك.", "Yes, I'm listening.");
  put("clip.reading", "لحظة، أقرا اللي نسخته.", "One moment, reading what you copied.");
  N.forEach((n, i) => put(`found.${n}`, FOUND[i]![0], FOUND[i]![1]));
  N.forEach((n, i) => put(`checking.${n}`, `أشيّك المسج ${ORD_AR[i]}`, `Checking the ${ORD_EN[i]} message`));
  N.slice(1).forEach((n, i) => put(`of.${n}`, OF[i]![0], OF[i]![1]));

  // The Investigator agent, step by step (only narrated when the verdict stream proves the step ran).
  N.forEach((n, i) => put(`investigator.start.${n}`, `بصير يشيّك على المسج ${ORD_AR[i]}.`, `Baseer, the Investigator, is checking the ${ORD_EN[i]} message.`));
  put("investigator.lists", "أطابقه مع قوائم النصب المعروفة.", "Checking known scam lists.");
  put("investigator.address", "أشوف عنوان الموقع، يمكن فيه تشابه مخادع.", "Checking the web address for look-alike tricks.");
  put("investigator.page", "أفتح الصفحة في متصفح معزول عندنا، وما يندخل فيها شي.", "Opening the page in our isolated browser. Nothing is typed.");
  put("investigator.ai_second_look_local", "نظرة ثانية بالذكاء الاصطناعي، بموديل محلي.", "AI second look, with our local model.");
  put("investigator.ai_second_look_cloud", "نظرة ثانية بالذكاء الاصطناعي، بنموذج لغوي سحابي.", "AI second look, with a cloud language model.");

  // What this check found (see FINDINGS), spoken under each tier.
  put("find.none", "ما لقينا شي ملفت في هذه الطبقة.", "Nothing notable at this layer.");
  put("investigator.wording", "أقرا صياغة المسج، وأدوّر على الاستعجال والضغط.", "Reading the wording for urgency and pressure.");
  for (const [, key, a, e] of FINDINGS) put(key, a, e);
  for (const [k, a, e] of CRED_LINES) put(`find.cred.${k}`, a, e);
  put("find.incomplete", "ما قدرنا نفتح الصفحة كامل.", "We couldn't open the page fully.");
  for (const [kind, ar0, en0] of [["age", "النطاق مسجّل", "The domain was registered"], ["cert", "شهادة الموقع صدرت", "The site certificate was issued"]] as const) {
    AGE_SPECIAL.forEach(([a, e], i) => put(`find.${kind}.${i}`, `${ar0} ${a}`, `${en0} ${e}`));
    put(`find.${kind}.lead`, `${ar0} قبل`, `${en0}`);
    put(`find.${kind}.days`, "يوم.", "days ago.");
  }
  for (const [id, a, e] of BRAND_CLIPS) put(`brand.${id}`, a, e);
  put("find.brand.a", "تدّعي إنها", "It claims to be");
  put("find.brand.b", "والنطاق مو لهم.", "but the domain is not theirs.");
  put("find.brand.generic", "تدّعي إنها جهة معروفة والنطاق مو لهم.", "It claims to be a well-known body, but the domain is not theirs.");
  put("sentinel.campaign", "والحملة تنتحل اسم", "The campaign imitates");
  put("investigator.rules_only", "القواعد حكمت، من غير ذكاء اصطناعي.", "The rules decided, without AI.");
  put("investigator.arbiter_result.dangerous", "الحكم النهائي: المسج خطر!", "The arbiter's decision: dangerous.");
  put("investigator.arbiter_result.suspicious", "الحكم النهائي: المسج مشكوك فيه.", "The arbiter's decision: suspicious.");
  put("investigator.arbiter_result.no_warning_signs", "الحكم النهائي: ما لقينا علامات تحذير.", "The arbiter's decision: no warning signs found.");
  put("investigator.arbiter_result.could_not_check", "ما قدرنا نشيّك هذا المسج.", "The message could not be checked.");

  // Scores: separate clips, "score.lead" + exact number clip + "score.of".
  put("score.lead", "الدرجة", "The score is");
  for (let s = 0; s <= 100; s++) put(`num.${s}`, numberWords(s)[0], numberWords(s)[1]);
  put("score.of", "من مية.", "out of one hundred.");

  // The Sentinel agent.
  put("sentinel.handover", "أسلّم النتايج لدرع.", "Handing the results to Dir, the Sentinel.");
  for (let n = 2; n <= 10; n++) put(`sentinel.linked.${n}`, `درع ربط ${COUNT_AR[n - 1]} في حملة نصب وحدة.`, `Dir linked ${NUM_EN[n]} reports into one campaign.`);
  put("sentinel.summary", "درع كتب ملخص بالعربي والإنجليزي.", "Dir wrote a summary in Arabic and English.");
  put("sentinel.draft", "درع جهّز مسودة طلب لإزالة الموقع.", "Dir prepared a takedown request draft.");
  put("sentinel.awaiting_approval", "ننتظر موافقة ضابط. ما يُرسل شي بدونها.", "Waiting for an officer's approval. Nothing is sent without it.");
  put("sentinel.watching", "درع يظل يراقب أي بلاغات مشابهة.", "Dir keeps watching for similar reports.");
  put("final.both_agents", "بصير شيّك، ودرع ربطها وصار يتابع.", "Baseer checked, and Dir linked them and follows up.");
  put("sentinel.unavailable", "ما وصلت لدرع الحين، فما أعرف إذا فيه حملة.", "I couldn't reach the Sentinel (Dir) right now, so I can't say whether there is a campaign.");
  put("nothing_checked", "ما قدرنا نكمّل أي فحص، فما سلّمت شي لدرع.", "No check could be completed, so I handed nothing to Dir.");
  put("mic.denied", "ما قدرت أستخدم المايك. اسمح له من المتصفح، أو الصق المسجات.", "I couldn't use the microphone. Allow it in your browser settings, or paste your messages in the box.");
  put("voice.unavailable", "خدمة الصوت مو متوفرة الحين. استخدم خانة اللصق.", "The voice service isn't available right now. Please use the paste box.");
  put("final.sentinel_unavailable", "بصير شيّك، بس ما قدرت أوصل لدرع.", "Baseer checked, but I couldn't reach Dir.");
  put("final.sentinel_watching", "بصير شيّك، ودرع يظل يراقب.", "Baseer checked, and Dir keeps watching.");

  N.forEach((n, i) => {
    const en_ = SUM_EN(n);
    for (const k of SUMMARY_KINDS) {
      // One message is masculine singular ("مسج واحد ... فيه / أشيّكه"); two or more take the plural "منها / فيها".
      const ar1 = { dangerous: "منها خطِر.", suspicious: "منها مشكوك فيه.", clear: "ما فيه علامات تحذير.", failed: "ما قدرت أشيّكه." };
      put(`sum.${k}.${n}`, `${COUNT_AR[i]} ${n === 1 ? ar1[k] : SUM_AR[k]}`, `${COUNT_EN[i]} ${en_[k]}`);
    }
  });
  put("result.dangerous", "هذا المسج خطر!", "This message is dangerous.");
  put("result.suspicious", "هذا المسج مشكوك فيه.", "This message looks suspicious.");
  put("result.no_warning_signs", "ما لقيت فيه علامات تحذير.", "I found no warning signs in it.");
  put("result.could_not_check", "ما قدرت أشيّك هذا المسج.", "I could not check this message.");
  // Per-message spoken result: "Message one:" + verdict + the one thing to do now (an earcon plays right before).
  N.forEach((n, i) => put(`msg.ord.${n}`, `المسج ${ORD_AR[i]}:`, `Message ${NUM_EN[n]}:`));
  put("msg.verdict.dangerous", "خطِر. لا تضغط الرابط ولا تعطي أي بيانات.", "dangerous. Don't tap the link or share any details.");
  put("msg.verdict.suspicious", "مشكوك فيه. تأكد من الجهة الرسمية قبل لا ترد.", "suspicious. Check with the official source before you reply.");
  put("msg.verdict.no_warning_signs", "ما لقينا علامات تحذير، بس خلّك منتبه.", "no warning signs found, but stay careful.");
  put("msg.verdict.could_not_check", "ما قدرنا نشيّكه كامل. لا تفتح الرابط لين تتأكد.", "could not be fully checked. Don't open the link until you are sure.");
  put("todo.lead", "نصيحتي لك:", "What to do now:");
  put("todo.link", "لا تضغط على الرابط، ولا تدوس عليه.", "Don't tap the link.");
  put("todo.otp", "ولا تعطي حد الرمز أبداً.", "Never share a code with anyone.");
  put("todo.bank", "كلّم بنكك على الرقم اللي على بطاقتك.", "Call your bank on the number on your card.");
  put("todo.report", "وبلّغ عن المسج من القنوات الرسمية.", "Report the message through the official channels.");
  put("todo.careful", "بس خلّك حذر.", "But stay careful.");
  put("todo.wait", "لا تفتح الرابط لين نشيّكه.", "Don't open the link until it is checked.");
  put("help", "انسخ المسجات، وقل: يا صقر، شيّك مسجاتي.", "Copy your messages, then say: Hey Falcon, check my messages.");
  put("stop", "تمام، وقّفت.", "Okay, I've stopped.");
  put("didnt", "ما فهمت عليك. عيد، لو سمحت.", "Sorry, I didn't catch that. Please say it again.");
  put("clip.empty", "ما لقيت مسجات في اللي نسخته. انسخها وعيد علي.", "I found no messages in what you copied. Copy them and try again.");
  put("greet.hello", "هلا! شلون أقدر أساعدك اليوم؟", "Hi, how can I help you today?");
  put("error", "صار خلل. جرّب مرة ثانية، ولا تفتح أي رابط.", "Something went wrong. Try again, and don't open any link.");
  put("voice.too_long", "الكلام طويل شوي، قوله باختصار.", "That was a bit long. Please say it more briefly.");
  put("voice.catching_up", "لحظة، خلني ألحق عليك.", "One moment, catching up.");
  put("voice.still_checking", "لحظة، لسا أشيّك.", "Still checking, one moment.");
  put("goodbye", "يزاك الله خير. الله يحفظك.", "Thank you. Take care.");
  for (const [name, a, e] of FAQ) put(faqKey(name), a, e);
  OFF_TOPIC.forEach(([a, e], i) => put(`offtopic.${i + 1}`, a, e));
  put(ACK_KEY, "لحظة…", "One moment…");
  return { ar_ae: ar, en };
}

export const SCRIPT: Record<VoiceLang, Record<string, string>> = build();
export const SCRIPT_KEYS: readonly string[] = Object.keys(SCRIPT.en);

export interface Clip {
  id: string;
  lang: VoiceLang;
  key: string;
  text: string;
}
/** Verdict sound effects (web/public/voice/sfx, generated in-repo by tools/voice_clips/sfx.py): language-neutral, no text. */
export const SFX_KEYS = ["sfx.clear", "sfx.suspicious", "sfx.dangerous"] as const;
export const isSfx = (key: string): boolean => key.startsWith("sfx.");
export const clipId = (lang: VoiceLang, key: string): string => (isSfx(key) ? key : `${lang}.${key}`);

export type ResultTone = "dangerous" | "suspicious" | "no_warning_signs" | "could_not_check";
const TONE_SFX: Record<ResultTone, string | null> = { dangerous: "sfx.dangerous", suspicious: "sfx.suspicious", no_warning_signs: "sfx.clear", could_not_check: null };
/** One checked message, spoken: earcon, "Message N:", the verdict and the one thing to do now. */
export const messageResultKeys = (i: number, verdict: ResultTone | null): string[] => {
  const tone: ResultTone = verdict ?? "could_not_check";
  const sfx = TONE_SFX[tone];
  return [...(sfx ? [sfx] : []), `msg.ord.${clampN(i)}`, `msg.verdict.${tone}`];
};
/** Every pre-recordable clip, both languages. */
export const CLIPS: readonly Clip[] = VOICE_LANGS.flatMap((lang) => SCRIPT_KEYS.map((key) => ({ id: clipId(lang, key), lang, key, text: SCRIPT[lang][key]! })));

/** Turns clip keys into the spoken text (pieces joined with a space; each piece is one pre-recorded clip). */
export function render(lang: VoiceLang, keys: readonly string[]): string {
  return keys
    .filter((k) => !isSfx(k))
    .map((k) => {
      const t = SCRIPT[lang][k];
      if (t === undefined) throw new Error(`unknown voice clip: ${k}`);
      return t;
    })
    .join(" ");
}

/* ── Composers: each returns clip KEYS only ───────────────────────────── */

const clampN = (n: number) => Math.max(1, Math.min(10, Math.floor(n)));

export const foundClips = (total: number): string[] => [`found.${clampN(total)}`];

/** "Checking message i of N" (for N = 1 just the ordinal). */
export const checkingClips = (i: number, total: number): string[] => (total <= 1 ? [`checking.${clampN(i)}`] : [`checking.${clampN(i)}`, `of.${clampN(total)}`]);

/** The Investigator agent starts on message i. */
export const investigatorStartClips = (i: number): string[] => [`investigator.start.${clampN(i)}`];

export type InvestigatorStep = "lists" | "address" | "wording" | "page" | "ai_second_look_local" | "ai_second_look_cloud" | "rules_only";
export const investigatorStepClips = (step: InvestigatorStep): string[] => [`investigator.${step}`];


/** The slice of an evidence item that speech may look at. Free text (display, strings inside observed) is never spoken. */
export interface FindingEvidence {
  signal: string;
  observed?: unknown;
  weight: number;
  polarity?: string;
  tier: string;
  error?: string | null;
}
const isObjLike = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const BRAND_ID = /^[a-z0-9_]{2,40}$/;

/** "claims to be {brand}": the brand is named only when it has its own clip, else a generic body. */
export function brandClaimClips(brandId: unknown): string[] {
  return typeof brandId === "string" && BRAND_ID.test(brandId) && BRAND_IDS.has(brandId) ? ["find.brand.a", `brand.${brandId}`, "find.brand.b"] : ["find.brand.generic"];
}

/** The clip keys for ONE evidence item, or null when it has no spoken line (unknown code, trust or neutral, errored). */
export function findingKeysFor(e: FindingEvidence, verdictBrandId?: string | null): string[] | null {
  if (INCOMPLETE_CODES.includes(e.signal)) return ["find.incomplete"];
  if (e.error || e.polarity === "trust" || (!(e.weight > 0) && !INFO_CODES.includes(e.signal))) return null;
  if (e.signal === "domain.age_days" || e.signal === "domain.cert_age_days") {
    const kind = e.signal === "domain.age_days" ? "age" : "cert";
    // Real shape: {age_days: N} (domain/rdap.py) and {cert_age_days: N} (domain/crt.py); a bare number is tolerated.
    const raw = isObjLike(e.observed) ? e.observed[kind === "age" ? "age_days" : "cert_age_days"] : e.observed;
    const n = typeof raw === "number" && Number.isFinite(raw) ? Math.round(raw) : -1;
    if (n < 0 || n > 100) return null; // older than 100 days is not a warning sign; the exact number clips stop at one hundred
    return n <= 2 ? [`find.${kind}.${n}`] : [`find.${kind}.lead`, `num.${n}`, `find.${kind}.days`];
  }
  if (e.signal === "page.cred_form") return [credFormKey(e.observed)];
  if (e.signal === "brand.claimed_not_owned") {
    const id = isObjLike(e.observed) && typeof e.observed.brand_id === "string" ? e.observed.brand_id : verdictBrandId;
    return brandClaimClips(id);
  }
  const key = CODE_KEY.get(e.signal);
  return key ? [key] : null;
}

/**
 * What one tier found: up to two strongest findings (by weight), spoken from real evidence only. A tier that ran with
 * nothing speakable says so ("nothing notable at this layer"); the AI tier (T3) never does.
 */
export function tierFindingGroups(evidence: readonly FindingEvidence[], tier: "T0" | "T1" | "T2" | "T3", verdictBrandId?: string | null): string[][] {
  const out: string[][] = [];
  const seen = new Set<string>();
  const ranked = evidence.filter((e) => e.tier === tier).sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  for (const e of ranked) {
    const keys = findingKeysFor(e, verdictBrandId);
    if (!keys) continue;
    const id = keys.join("|");
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(keys);
    if (out.length === 2) break;
  }
  return out.length || tier === "T3" ? out : [["find.none"]];
}

/** A score 0..100 spoken as words from exact number clips. */
export function scoreClips(score: number): string[] {
  const s = Math.max(0, Math.min(100, Math.round(Number.isFinite(score) ? score : 0)));
  return ["score.lead", `num.${s}`, "score.of"];
}

/** The arbiter's decision for one message; the score is spoken for every checked message, never for a failed one. */
export function arbiterClips(verdict: SpeechVerdict | null, score = 0): string[] {
  return verdict ? [`investigator.arbiter_result.${verdict}`, ...scoreClips(score)] : ["investigator.arbiter_result.could_not_check"];
}

/** Short per-message result (used when narration is off the agent track). */
export function resultClips(verdict: SpeechVerdict | null, score = 0): string[] {
  return verdict ? [`result.${verdict}`, ...scoreClips(score)] : ["result.could_not_check"];
}

export interface SpeechCounts {
  total: number;
  dangerous: number;
  suspicious: number;
  clear: number;
  failed: number;
}

/** Counts per verdict, only for more than one message (a single message was already read out with its result). */
export function summaryClips(c: SpeechCounts): string[] {
  if (c.total < 2) return [];
  return SUMMARY_KINDS.flatMap((k) => (c[k] > 0 ? [`sum.${k}.${clampN(c[k])}`] : []));
}

/** What to do, chosen by the most severe verdict. Generic wording only: no phone numbers, nothing personal. */
export function todoClips(c: SpeechCounts): string[] {
  if (c.total === 0) return [];
  if (c.dangerous > 0) return ["todo.lead", "todo.link", "todo.otp", "todo.bank", "todo.report", ...(c.failed ? ["todo.wait"] : [])];
  if (c.suspicious > 0) return ["todo.lead", "todo.link", "todo.otp", "todo.bank", ...(c.failed ? ["todo.wait"] : [])];
  if (c.clear > 0) return ["todo.careful", ...(c.failed ? ["todo.wait"] : [])];
  return ["todo.wait"];
}

/** The Sentinel hand-over line, naming the campaign size only when the data links 2+ reports. */
export function sentinelClips(campaignSize: number): string[] {
  const out = ["sentinel.handover"];
  if (campaignSize >= 2) out.push(`sentinel.linked.${Math.min(10, Math.floor(campaignSize))}`, "sentinel.summary");
  return out;
}

/** Draft and approval lines: said only when the dangerous verdict proves a takedown draft exists. */
export const takedownClips = (): string[] => ["sentinel.draft", "sentinel.awaiting_approval"];

/** What the polled Sentinel incident actually showed (all false/0 when no incident was found). */
export interface SentinelFinding {
  /** Linked checks in the incident. */
  linked: number;
  /** The real trace shows the linking nodes ran. */
  linkStep: boolean;
  /** The real trace shows the summary node ran. */
  summary: boolean;
  /** The incident holds an external takedown draft. */
  drafted: boolean;
  /** Registry id of the brand the linked checks impersonate, when known (named only when it has a clip). */
  brand?: string | null;
  /** That draft is awaiting an officer's approval. */
  awaiting: boolean;
}

/** Spoken ONLY for what the incident shows: nothing is said that the data does not prove. */
export function sentinelFindingGroups(f: SentinelFinding): string[][] {
  const out: string[][] = [];
  if (f.linkStep && f.linked >= 2) {
    out.push([`sentinel.linked.${Math.min(10, Math.floor(f.linked))}`]);
    if (typeof f.brand === "string" && BRAND_IDS.has(f.brand)) out.push(["sentinel.campaign", `brand.${f.brand}`]);
  }
  if (f.summary) out.push(["sentinel.summary"]);
  if (f.drafted) out.push(["sentinel.draft"]);
  if (f.drafted && f.awaiting) out.push(["sentinel.awaiting_approval"]);
  return out;
}
export const sentinelFindingClips = (f: SentinelFinding): string[] => sentinelFindingGroups(f).flat();

/**
 * The closing utterance: summary, what to do, then the one-line wrap-up that names what actually happened:
 * "found" when a real Sentinel incident links these checks, "watching" when none did within the wait.
 */
export function finalClips(c: SpeechCounts, sentinel: "found" | "watching" | "unavailable" | "none"): string[] {
  if (c.total === 0) return [];
  const wrap = sentinel === "found" ? ["final.both_agents"] : sentinel === "watching" ? ["final.sentinel_watching"] : sentinel === "unavailable" ? ["final.sentinel_unavailable"] : [];
  return [...summaryClips(c), ...todoClips(c), ...wrap];
}
