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

export interface Row {
  name: string;
  entry: string;
  detail: string;
}

export interface AuthContent {
  title: string;
  lead: string;
  status: string;
  surfacesTitle: string;
  cols: [string, string, string];
  rows: Row[];
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
    surfacesTitle: "واجهات الربط",
    cols: ["الواجهة", "نقطة الدخول", "التوثيق والتفاصيل"],
    rows: [
      { name: "REST الإصدار 1", entry: "/v1/*", detail: "عقد OpenAPI موثّق. مفتاح عبر X-API-Key أو Authorization: Bearer. أخطاء بصيغة RFC 9457 لا تعيد محتوى المُرسَل." },
      { name: "MCP", entry: "/mcp", detail: "خادم بروتوكول سياق النموذج (HTTP قابل للبث) بمفتاح حامل. أدواته: فحص رابط أو رسالة أو بريد، وجلب حكم، وقوائم الحملات والحوادث، وإرسال بلاغ. تعمل بصلاحيتي الفحص والقراءة فقط، فلا تستطيع الموافقة على إجراء أو تصدير معلومات التهديد." },
      { name: "STIX 2.1", entry: "GET /v1/intel/stix", detail: "تصدير مؤشرات التهديد بصيغة STIX لمن يملك مفتاحاً بصلاحية intel فقط." },
      { name: "الخطافات الخارجية (Webhooks)", entry: "campaign.alert", detail: "إشعار موقَّع بـ HMAC-SHA256 عند رصد حملة، مع نافذة إعادة تشغيل مدتها 300 ثانية وإعادة محاولة عند الفشل. على المستقبِل التحقق من التوقيع وإزالة التكرار." },
    ],
    sections: [
      { title: "المفاتيح والصلاحيات", list: [
        "أربع صلاحيات: check لإرسال الفحوص، وread لقراءة الحملات والحوادث، وintel لتصدير STIX، وoperator للموافقة على الإجراءات المعلّقة.",
        "لا تُحفظ المفاتيح نفسها، بل بصمة مجزّأة (argon2id) منها فقط، ولكل مفتاح حد خاص بالطلبات في الدقيقة. عند تجاوزه يُعاد الرمز 429 مع Retry-After.",
        "كل نداء بمفتاح يُسجَّل في سجل تدقيق للإضافة فقط، دون محتوى الطلبات.",
      ] },
      { title: "الإنسان في الحلقة", body: ["يقترح الحارس إجراءات مثل حظر مؤشر أو إعداد طلب إزالة أو بلاغ. الإجراءات الداخلية القابلة للتراجع تُنفَّذ تلقائياً، أما أي إجراء خارجي فيبقى مسودة معلّقة إلى أن يوافق عليه مشغّل بشري."] },
      { title: "الوضع السيادي", body: [
        "عند تفعيل الوضع السيادي تُوجَّه كل نداءات النموذج اللغوي إلى نموذج محلي، فلا يغادر أي محتوى الجهاز. وتتصرف واجهة REST وMCP بالطريقة نفسها، وتُبلغ GET /v1/meta بحالة الوضع ليعرضها العميل.",
        "عمليات البحث الخارجية الوحيدة تحمل أسماء النطاقات فقط، ويمكن تعطيلها.",
      ] },
    ],
    boundaryTitle: "حدود البيانات",
    boundaryIn: "يدخل: رابط أو نص رسالة أو ملف بريد أو صورة للفحص. البلاغات والملاحظات تُرسل ببصمة SHA-256، ولا يُخزَّن نصها إلا بموافقة صريحة.",
    boundaryOut: "يخرج: أحكام مع أسبابها وأدلتها وعناوين معطَّلة العرض، وبطاقات حملات وحوادث بمؤشرات معطَّلة وأعداد مجمّعة، ومؤشرات STIX. لا يخرج نص الصفحات أو الرسائل الخام، ولا بيانات شخصية للمُبلِّغين. البيانات المُعاد تشغيلها أو الاصطناعية تحمل وسماً يوضح مصدرها.",
    docs: "التفاصيل الكاملة في وثيقة التكامل المرفقة بالمشروع (docs/INTEGRATION.md) وعقد OpenAPI (contracts/openapi.yaml).",
  },
  en: {
    title: "For authorities: integration",
    lead: "Falcon Lens is designed to connect to security applications and systems through documented interfaces. This page describes how a connection could work, and what does and does not cross the boundary.",
    status: "Ready to connect, not connected. There is no existing integration with Abu Dhabi Police or any government body, and this site carries no endorsement from them. Everything below describes a possible connection.",
    surfacesTitle: "Connection surfaces",
    cols: ["Surface", "Entry point", "Authentication and details"],
    rows: [
      { name: "REST v1", entry: "/v1/*", detail: "Documented OpenAPI contract. Key via X-API-Key or Authorization: Bearer. Errors follow RFC 9457 and never echo what was submitted." },
      { name: "MCP", entry: "/mcp", detail: "Model Context Protocol server (streamable HTTP) with a bearer token. Tools: check a link, message or email, fetch a verdict, list campaigns and incidents, submit a report. It runs with check and read scopes only, so it cannot approve an action or export intelligence." },
      { name: "STIX 2.1", entry: "GET /v1/intel/stix", detail: "Threat-indicator export in STIX, available only to a key holding the intel scope." },
      { name: "Webhooks", entry: "campaign.alert", detail: "HMAC-SHA256 signed notification when a campaign is detected, with a 300-second replay window and retries on failure. Receivers must verify the signature and de-duplicate." },
    ],
    sections: [
      { title: "Keys and scopes", list: [
        "Four scopes: check to submit checks, read for campaigns and incidents, intel for the STIX export, operator to approve held actions.",
        "Keys themselves are never stored, only an argon2id hash of each, each with its own per-minute rate limit. Beyond it the API answers 429 with Retry-After.",
        "Every keyed call is written to an append-only audit log, without request bodies.",
      ] },
      { title: "A human in the loop", body: ["The Sentinel proposes actions such as blocking an indicator or drafting a takedown request or police report. Internal, reversible actions run automatically. Any external action stays a held draft until a human operator approves it."] },
      { title: "Sovereign mode", body: [
        "With sovereign mode on, every language-model call goes to a local model, so no content leaves the machine. REST and MCP behave identically, and GET /v1/meta reports the mode so a client can display it.",
        "The only outside lookups carry domain names alone, and they can be disabled.",
      ] },
    ],
    boundaryTitle: "Data boundary",
    boundaryIn: "In: a link, message text, email file or image to check. Reports and feedback arrive as SHA-256 hashes, and their text is stored only with explicit consent.",
    boundaryOut: "Out: verdicts with their reasons, evidence and defanged addresses; campaign and incident cards with defanged indicators and aggregate counts; STIX indicators. Raw page or message text never leaves, nor does any personal data of reporters. Replayed or synthetic data carries a label stating its source.",
    docs: "Full detail is in the integration document shipped with the project (docs/INTEGRATION.md) and the OpenAPI contract (contracts/openapi.yaml).",
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
        "الوضع السحابي: يُرسل نص محجوب الحقول الحساسة ومحمي من الحقن إلى واجهة نموذج لغوي. ولا يغادر الجهاز غير ذلك سوى عمليات بحث تحمل أسماء النطاقات فقط.",
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
        "Cloud mode: redacted, injection-guarded text goes to a language-model API. Nothing else leaves the machine except lookups that carry domain names only.",
        "Sovereign mode: every model call goes to a local model, so no content leaves the machine. Outside lookups can be disabled as well.",
      ] },
      { title: "Retention", body: ["A retention policy is planned (verdicts kept for a limited period, then aggregated) but it is not yet automated. The audit log is append-only. Local snapshots stay on the machine."] },
    ],
    note: "This describes how the system handles data. It is not a claim of compliance with any specific legal regime.",
  },
};
