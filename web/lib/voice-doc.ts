/**
 * Copy for the voice-assistant section of /docs/agents.
 * Restates only what is on main: services/voice, services/api/src/falcon_api/voice.py, web/app/api/voice/route.ts,
 * web/components/VoiceAssistant.tsx, web/lib/voice*.ts and docs/PRIVACY.md. Plain text only.
 */
import type { Lang } from "./contracts";

export interface VoiceStep {
  tag: string;
  title: string;
  body: string;
}
export interface VoiceDoc {
  title: string;
  lead: string;
  stepsLabel: string;
  steps: VoiceStep[];
  limitsTitle: string;
  limits: string[];
  tryLabel: string;
}

const en: VoiceDoc = {
  title: "Voice assistant | المساعد الصوتي",
  lead: "Say \"Hey Falcon | يا صقر\" and the assistant checks what you copied, then tells you each step aloud: Baseer (the Investigator) first, then Dir' (the Sentinel).",
  stepsLabel: "The voice path, step by step",
  steps: [
    { tag: "MIC", title: "Wake phrase", body: "You switch on the microphone and say \"Hey Falcon\". The browser records one short clip (at most fifteen seconds) and sends it to our own web route, /api/voice." },
    { tag: "STT", title: "Speech to text, locally", body: "The API passes the clip to a Whisper model on our own machine: native mlx-whisper first, the voice container (faster-whisper, small model) as the fallback. The audio stays in memory. Audio and transcripts are never stored and never logged." },
    { tag: "INTENT", title: "Intent by fixed rules", body: "Fixed rules, not a model, decide what you asked: check what you copied, check some text, help, or stop." },
    { tag: "CHECK", title: "The same check as the Check page", body: "Each message you copied goes through the same public check API as the Check page, with the channel set to voice. Nothing is checked differently because you spoke." },
    { tag: "BASEER", title: "Baseer narrates each live step", body: "Baseer, the Investigator, is narrated only for steps the verdict stream shows really ran: known scam lists, the web address, the isolated page, an AI second look if it was needed. Then the verdict, how sure it is, and what to do now." },
    { tag: "DIR'", title: "Hand-over to Dir'", body: "The results go to Dir', the Sentinel. If the data links two or more checks, the assistant says so: one incident or campaign. If Dir' is not reachable it says that, and does not guess. Any outside action waits for an officer's approval." },
    { tag: "VOICE", title: "Spoken in your language", body: "The language is detected for each sentence you say, so the answer follows you between English and Arabic. It is built from clips generated in advance from our own script and played locally. No text you typed or said is sent to a speech engine while you use it. English clips use Kokoro (am_fenrir). Arabic clips use Amazon Polly neural Zayd (ar-AE, an Emirati male voice), generated offline once and kept private." },
  ],
  limitsTitle: "Limits and privacy",
  limits: [
    "A clip is at most fifteen seconds and one megabyte.",
    "Rate limits apply per visitor on the web route and per address on the API.",
    "The voice container has no direct internet access; its only outbound traffic is the one-time download of the open Whisper weights through an allow-listing proxy.",
    "The wake phrase and the intent are decided by fixed rules; the model never sets a score.",
  ],
  tryLabel: "Try it on the Check page",
};

const ar: VoiceDoc = {
  title: "المساعد الصوتي | Voice assistant",
  lead: "قل «يا صقر» فيفحص المساعد ما نسخته، ثم يخبرك بكل خطوة بصوت مسموع: «بصير»، المحقّق، أولاً ثم «درع»، الحارس.",
  stepsLabel: "المسار الصوتي خطوة بخطوة",
  steps: [
    { tag: "MIC", title: "عبارة التنبيه", body: "تشغّل الميكروفون وتقول «يا صقر». يسجّل المتصفح مقطعاً قصيراً (خمس عشرة ثانية على الأكثر) ويرسله إلى مسار الويب لدينا /api/voice." },
    { tag: "STT", title: "تحويل الكلام إلى نص محلياً", body: "تمرّر الواجهة البرمجية المقطع إلى نموذج Whisper على جهازنا نفسه: محرّك mlx-whisper الأصلي أولاً، وحاوية الصوت (faster-whisper بالنموذج الصغير) احتياطاً. يبقى الصوت في الذاكرة فقط، ولا يُخزَّن الصوت ولا النص المفرَّغ ولا يُسجَّلان." },
    { tag: "INTENT", title: "فهم الطلب بقواعد ثابتة", body: "قواعد ثابتة، لا نموذج، تحدد ما طلبته: فحص ما نسخته، أو فحص نص، أو مساعدة، أو إيقاف." },
    { tag: "CHECK", title: "الفحص نفسه في صفحة الفحص", body: "تمرّ كل رسالة نسختها عبر واجهة الفحص العامة نفسها التي تستخدمها صفحة الفحص بقناة «صوت». لا يختلف الفحص لأنك تحدثت." },
    { tag: "BASEER", title: "«بصير» يروي كل خطوة مباشرة", body: "يروي المساعد خطوات «بصير»، المحقّق، التي يثبت تدفق الحكم أنها جرت فعلاً فقط: قوائم الاحتيال المعروفة، وعنوان الموقع، والصفحة في المتصفح المعزول، والنظرة الثانية بالذكاء الاصطناعي إن لزمت. ثم الحكم ودرجة الثقة وما عليك فعله الآن." },
    { tag: "DIR'", title: "التسليم إلى «درع»", body: "تُسلَّم النتائج إلى «درع»، الحارس. فإن ربطت البيانات فحصين أو أكثر قال المساعد ذلك: حادثة أو حملة واحدة. وإن تعذّر الوصول إلى «درع» قال ذلك ولم يخمّن. وأي إجراء خارجي ينتظر موافقة ضابط." },
    { tag: "VOICE", title: "الرد بلغتك", body: "تُكتشف اللغة لكل جملة تقولها، فيتبعك الرد بين الإنجليزية والعربية. ويُركَّب من مقاطع صوتية مولَّدة مسبقاً من نصنا نفسه وتُشغَّل محلياً. لا يُرسَل نص كتبته أو قلته إلى أي محرّك كلام أثناء الاستخدام. المقاطع الإنجليزية بصوت Kokoro (am_fenrir). والعربية بصوت Amazon Polly العصبي «زايد» (ar-AE، صوت إماراتي ذكوري)، مولَّدة مرة واحدة دون اتصال وتبقى خاصة." },
  ],
  limitsTitle: "الحدود والخصوصية",
  limits: [
    "المقطع خمس عشرة ثانية وميغابايت واحد على الأكثر.",
    "تُطبَّق حدود للمعدّل لكل زائر على مسار الويب ولكل عنوان على الواجهة البرمجية.",
    "حاوية الصوت لا تصل إلى الإنترنت مباشرة، وحركتها الخارجية الوحيدة تنزيل أوزان Whisper المفتوحة مرة واحدة عبر وسيط يسمح بنطاقات محددة.",
    "عبارة التنبيه والطلب تحددهما قواعد ثابتة، والنموذج لا يحدد أي درجة.",
  ],
  tryLabel: "جرّبه في صفحة الفحص",
};

export const VOICE_DOC: Record<Lang, VoiceDoc> = { ar, en };
