/**
 * Copy for the judge-facing pages (Authorities, Privacy; the agents page copy lives in lib/i18n.ts). Plain text only:
 * everything is rendered as React text nodes. Statements here mirror docs/INTEGRATION.md and
 * docs/PRIVACY.md; they describe what the shipped code does or "could" do and carry no numbers
 * (numbers live only in the published evaluation artifact, see lib/results.ts).
 */
import type { Lang } from "./contracts";

export interface Section {
  title: string;
  body?: string[];
  list?: string[];
}

export interface AuthContent {
  title: string;
  lead: string;
  status: string;
  outcomesTitle: string;
  outcomes: { title: string; text: string }[];
  sections: Section[];
  boundaryTitle: string;
  boundaryIn: string;
  boundaryOut: string;
  docs: string;
}

export interface PrivacyContent {
  title: string;
  lead: string;
  sections: Section[];
  note: string;
}

export const AUTH: Record<Lang, AuthContent> = {
  ar: {
    title: "للجهات المختصة: التكامل والربط",
    lead: "عدسة الصقر مصمَّمة لتُربط بالتطبيقات والأنظمة الأمنية عبر واجهات موثّقة. هذه الصفحة تصف كيف يمكن الربط، وما الذي يعبر الحدود وما الذي لا يعبرها.",
    status: "جاهز للربط، وغير مربوط. لا يوجد أي ربط قائم مع شرطة أبوظبي أو أي جهة حكومية، ولا يتضمن هذا الموقع أي تأييد منها. كل ما يلي وصف لإمكانية الربط.",
    outcomesTitle: "ما الذي يمكن أن تحصل عليه الجهة",
    outcomes: [
      { title: "فحص عند الطلب", text: "يرسل نظام الجهة رابطاً أو رسالة ويتلقى حكماً بأسبابه وأدلته." },
      { title: "معلومات الحملات", text: "حملات وحوادث بمؤشرات معطَّلة وأعداد مجمّعة، وتنبيه موقَّع عند رصد حملة، وتصدير STIX لمن يملك صلاحية." },
      { title: "موافقة قبل أي خروج", text: "كل إجراء خارجي يبقى مسودة إلى أن يوافق عليه مشغّل بشري." },
    ],
    sections: [
      { title: "الإنسان في الحلقة", body: ["يقترح الحارس إجراءات مثل حظر مؤشر أو إعداد طلب إزالة أو بلاغ. الإجراءات الداخلية القابلة للتراجع تُنفَّذ تلقائياً، أما أي إجراء خارجي فيبقى مسودة معلّقة إلى أن يوافق عليه مشغّل بشري."] },
      { title: "الوضع السيادي", body: [
        "عند تفعيل الوضع السيادي تُوجَّه كل نداءات النموذج اللغوي إلى نموذج محلي، فلا يغادر أي محتوى الجهاز. وتتصرف واجهة REST وMCP بالطريقة نفسها، وتُبلغ GET /v1/meta بحالة الوضع ليعرضها العميل.",
        "عمليات البحث الخارجية الوحيدة تحمل أسماء النطاقات فقط، ويمكن تعطيلها.",
      ] },
    ],
    boundaryTitle: "حدود البيانات",
    boundaryIn: "يدخل: رابط أو نص رسالة أو ملف بريد أو صورة للفحص. البلاغات والملاحظات تُرسل ببصمة SHA-256، ولا يُخزَّن نصها إلا بموافقة صريحة.",
    boundaryOut: "يخرج: أحكام مع أسبابها وأدلتها وعناوين معطَّلة العرض، وبطاقات حملات وحوادث بمؤشرات معطَّلة وأعداد مجمّعة، ومؤشرات STIX. لا يخرج نص الصفحات أو الرسائل الخام، ولا بيانات شخصية للمُبلِّغين. البيانات المُعاد تشغيلها أو الاصطناعية تحمل وسماً يوضح مصدرها.",
    docs: "التفاصيل التقنية الكاملة (المفاتيح والصلاحيات ونقاط الدخول) في صفحة الربط ضمن التوثيق، وفي وثيقة التكامل المرفقة بالمشروع وعقد OpenAPI.",
  },
  en: {
    title: "For authorities: integration",
    lead: "Falcon Lens is designed to connect to security applications and systems through documented interfaces. This page describes how a connection could work, and what does and does not cross the boundary.",
    status: "Ready to connect, not connected. There is no existing integration with Abu Dhabi Police or any government body, and this site carries no endorsement from them. Everything below describes a possible connection.",
    outcomesTitle: "What an authority could get",
    outcomes: [
      { title: "Checks on request", text: "An authority system sends a link or message and receives a verdict with its reasons and evidence." },
      { title: "Campaign intelligence", text: "Campaigns and incidents with defanged indicators and aggregate counts, a signed alert when a campaign is detected, and a STIX export for key holders with the right scope." },
      { title: "Approval before anything leaves", text: "Every external action stays a draft until a human operator approves it." },
    ],
    sections: [
      { title: "A human in the loop", body: ["The Sentinel proposes actions such as blocking an indicator or drafting a takedown request or police report. Internal, reversible actions run automatically. Any external action stays a held draft until a human operator approves it."] },
      { title: "Sovereign mode", body: [
        "With sovereign mode on, every language-model call goes to a local model, so no content leaves the machine. REST and MCP behave identically, and GET /v1/meta reports the mode so a client can display it.",
        "The only outside lookups carry domain names alone, and they can be disabled.",
      ] },
    ],
    boundaryTitle: "Data boundary",
    boundaryIn: "In: a link, message text, email file or image to check. Reports and feedback arrive as SHA-256 hashes, and their text is stored only with explicit consent.",
    boundaryOut: "Out: verdicts with their reasons, evidence and defanged addresses; campaign and incident cards with defanged indicators and aggregate counts; STIX indicators. Raw page or message text never leaves, nor does any personal data of reporters. Replayed or synthetic data carries a label stating its source.",
    docs: "Technical detail (keys, scopes, entry points) is on the integration page in Docs, in the integration document shipped with the project and in the OpenAPI contract.",
  },
};

export const PRIVACY: Record<Lang, PrivacyContent> = {
  ar: {
    title: "الخصوصية",
    lead: "نحتفظ بأقل قدر ممكن من البيانات، ونحجب المعلومات الحساسة قبل أي معالجة إضافية.",
    sections: [
      { title: "ما الذي نحفظه", list: [
        "لا نحفظ ما تلصقه. نحتفظ بنسخة معطَّلة من الروابط التي تفحصها، وبصمة (SHA-256) للمدخل بعد تطبيعه، والأدلة والحكم.",
        "لا نحفظ نص الرسائل أو البريد الإلكتروني إلا إذا اخترت الإبلاغ عنه وأعطيت موافقتك.",
      ] },
      { title: "ما الذي لا نحفظه ولا نطلبه", list: [
        "لا نطلب منك أبداً بيانات شخصية أو مصرفية أو رقم هوية.",
        "لا ندخل أي بيانات في الصفحات المشبوهة، ولا نرسل أي نموذج فيها. تُزار الصفحة مرة واحدة في بيئة معزولة وبصورة سلبية.",
      ] },
      { title: "الحجب قبل المعالجة", body: ["قبل أي نداء لنموذج ذكاء اصطناعي سحابي نحجب أرقام الهاتف الإماراتية وأرقام الهوية الإماراتية وأرقام البطاقات المصرفية وعناوين البريد الإلكتروني وأرقام الآيبان. أما السجلات التشغيلية فتهرّب فيها محارف التحكم ولا تحمل نصوص الرسائل."] },
      { title: "الوضع السحابي والوضع السيادي", list: [
        "الوضع السحابي: يُرسل نص محجوب الحقول الحساسة ومُعلَّم (spotlighted): محاط بحدود ومُوسَّم على أنه غير موثوق قبل أن يراه أي نموذج، إلى واجهة نموذج لغوي. ولا يغادر الجهاز غير ذلك سوى عمليات بحث تحمل أسماء النطاقات فقط.",
        "الوضع السيادي: تذهب كل نداءات النموذج إلى نموذج محلي، فلا يغادر أي محتوى الجهاز. ويمكن تعطيل عمليات البحث الخارجية أيضاً.",
      ] },
      { title: "الاحتفاظ", body: ["سياسة الاحتفاظ مخطَّطة (حفظ الأحكام مدة محدودة ثم تجميعها إحصائياً) لكنها لم تُؤتمت بعد. سجل التدقيق للإضافة فقط. اللقطات المحلية تبقى على الجهاز."] },
    ],
    note: "هذا وصف لطريقة معالجة البيانات في النظام، وليس إقراراً بالامتثال لنظام قانوني بعينه.",
  },
  en: {
    title: "Privacy",
    lead: "We keep as little data as possible, and we redact sensitive details before any further processing.",
    sections: [
      { title: "What we store", list: [
        "We do not store what you paste. We keep a defanged copy of the links you check, a SHA-256 hash of the normalised input, and the evidence and verdict.",
        "We do not store message or email text unless you choose to report it and give your consent.",
      ] },
      { title: "What we do not store or ask for", list: [
        "We never ask you for personal, banking or ID details.",
        "We never enter data into a suspicious page or submit any form on it. The page is visited once, passively, in an isolated environment.",
      ] },
      { title: "Redaction before processing", body: ["Before any cloud AI-model call we redact UAE phone numbers, Emirates ID numbers, card numbers, email addresses and IBANs. Operational logs are separate: they escape control characters and carry no message bodies."] },
      { title: "Cloud mode and sovereign mode", list: [
        "Cloud mode: redacted, spotlighted text (delimited and datamarked as untrusted before any model sees it) goes to a language-model API. Nothing else leaves the machine except lookups that carry domain names only.",
        "Sovereign mode: every model call goes to a local model, so no content leaves the machine. Outside lookups can be disabled as well.",
      ] },
      { title: "Retention", body: ["A retention policy is planned (verdicts kept for a limited period, then aggregated) but it is not yet automated. The audit log is append-only. Local snapshots stay on the machine."] },
    ],
    note: "This describes how the system handles data. It is not a claim of compliance with any specific legal regime.",
  },
};
