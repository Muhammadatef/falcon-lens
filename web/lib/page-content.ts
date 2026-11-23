/**
 * Copy for the judge-facing pages (How it works, Authorities, Privacy). Plain text only:
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

export interface HowContent {
  title: string;
  lead: string;
  stepsTitle: string;
  steps: { title: string; text: string }[];
  figureAlt: string;
  layersTitle: string;
  layersLead: string;
  agentsTitle: string;
  agentsLead: string;
  agentsAlt: string;
  investigator: { title: string; role: string; list: string[] };
  sentinel: { title: string; role: string; list: string[] };
  principle: string;
  cta: string;
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

export const HOW: Record<Lang, HowContent> = {
  ar: {
    title: "كيف تعمل عدسة الصقر",
    lead: "من لحظة وصول رسالة مشبوهة إلى حكم واضح مدعوم بالأدلة، في أربع خطوات يمكن لأي شخص متابعتها.",
    stepsTitle: "أربع خطوات",
    steps: [
      { title: "تقدّم ما تشتبه به", text: "تلصق رابطاً مشبوهاً أو تشاركه من هاتفك مباشرة. فحص الرسائل والبريد الإلكتروني والصور يظهر حالته أدناه. لا نطلب منك أي بيانات شخصية أو مصرفية أو رقم هوية." },
      { title: "نفحص العنوان", text: "نطابق العنوان مع القوائم المعروفة للبلاغات، ونتحقق مما إذا كان ينتحل اسماً معروفاً، وكم مضى على تسجيل النطاق." },
      { title: "نزور الصفحة في بيئة معزولة", text: "نفتح الصفحة في متصفح مغلق بعيداً عن هاتفك، دون كتابة أي شيء أو إرسال أي نموذج، ونقارن ما تدّعيه الصفحة بالجهة المالكة للعنوان فعلاً." },
      { title: "تحصل على حكم واضح", text: "الحكم أحد ثلاثة: خطِر، أو مريب، أو لم نجد علامات تحذير. يرافقه الأسباب والأدلة وما ينبغي فعله الآن. لا تصف عدسة الصقر أي رابط بأنه مأمون أبداً." },
    ],
    figureAlt: "رسم توضيحي للخطوات الأربع: تقديم الرابط، فحص العنوان، زيارة معزولة للصفحة، ثم حكم واضح بالعربية والإنجليزية.",
    layersTitle: "طبقات الفحص",
    layersLead: "تبدأ العدسة بالأسرع والأقل كلفة، ولا تنتقل إلى الطبقة الأعمق إلا عند الحاجة. وإذا حسمت قاعدة قاطعة النتيجة مبكراً توقف الفحص عندها.",
    agentsTitle: "المساعدان الذكيان",
    agentsLead: "يعمل في النظام وكيلان من الذكاء الاصطناعي، لكلٍّ منهما دور محدد وحدود واضحة. ولا يحدد أيٌّ منهما الدرجة النهائية.",
    agentsAlt: "رسم توضيحي للمساعدين: المحقّق الذي يتعمق في الحالات الغامضة، والحارس الذي يراقب الفحوص على مدار الساعة ويربط الحملات المتشابهة.",
    investigator: {
      title: "المحقّق",
      role: "يتعمق في الحالات غير الواضحة",
      list: [
        "يُستدعى فقط حين لا تستطيع القواعد الثابتة حسم الحالة.",
        "يعمل بقائمة قصيرة من الأدوات المعتمدة.",
        "صُمّم بحيث لا يغيّر نص الصفحة الدرجة. تقييم مقاومة الحقن: انظر صفحة النتائج.",
        "لا يغيّر الدرجة. الدرجة يحددها محكّم حتمي من الأدلة.",
      ],
    },
    sentinel: {
      title: "الحارس",
      role: "يراقب الفحوص على مدار الساعة",
      list: [
        "يربط الفحوص المتشابهة ليكشف الحملة مبكراً.",
        "يحظر المؤشرات المعروفة داخل نظامنا فقط، وبشكل قابل للتراجع.",
        "يعدّ مسودات طلبات الإزالة وبلاغات الشرطة.",
        "لا يرسل شيئاً إلى الخارج بنفسه. لا بد من موافقة شخص مسؤول.",
      ],
    },
    principle: "الذكاء الاصطناعي يساعد ويشرح، ولا يحدد الحكم. الحكم يصدره محكّم حتمي من الأدلة، ويمكن تتبّع كل سبب إلى دليل محدد.",
    cta: "جرّب الفحص الآن",
  },
  en: {
    title: "How Falcon Lens works",
    lead: "From a suspicious message arriving to a clear, evidence-backed verdict, in four steps that anyone can follow.",
    stepsTitle: "Four steps",
    steps: [
      { title: "You submit what looks suspicious", text: "Paste a suspicious link, or share it straight from your phone. The status of message, email and image checking is shown below. We never ask for personal, banking or ID details." },
      { title: "We examine the address", text: "We match the address against known report lists and check whether it imitates a known name and how recently the domain was registered." },
      { title: "We visit the page in isolation", text: "We open the page in a sealed browser away from your phone, typing nothing and submitting no form, and compare what the page claims with who actually owns the address." },
      { title: "You get a clear verdict", text: "One of three: dangerous, suspicious, or no warning signs found, with the reasons, the evidence and what to do now. Falcon Lens never describes a link as trustworthy." },
    ],
    figureAlt: "Illustration of the four steps: submit the link, examine the address, isolated page visit, then a clear verdict in Arabic and English.",
    layersTitle: "The checking layers",
    layersLead: "The lens starts with the fastest, cheapest check and goes deeper only when it must. If a decisive rule settles the case early, checking stops there.",
    agentsTitle: "The two AI agents",
    agentsLead: "Two AI agents work inside the system, each with a defined role and clear limits. Neither of them sets the final score.",
    agentsAlt: "Illustration of the two agents: the Investigator, which looks closer at unclear cases, and the Sentinel, which watches every check around the clock and links similar scams.",
    investigator: {
      title: "The Investigator",
      role: "Looks closer at unclear cases",
      list: [
        "Called only when the fixed rules cannot settle a case.",
        "Works with a short list of approved tools.",
        "Designed so that page text cannot change the score. Injection-resistance evaluation: see Results.",
        "It cannot change the score. A deterministic arbiter sets it from the evidence.",
      ],
    },
    sentinel: {
      title: "The Sentinel",
      role: "Watches every check, around the clock",
      list: [
        "Links similar checks to spot a campaign early.",
        "Blocks known indicators inside our own system only, and reversibly.",
        "Drafts takedown requests and police reports.",
        "It sends nothing outside by itself. A responsible person must approve.",
      ],
    },
    principle: "AI assists and explains. It never sets the verdict. A deterministic arbiter issues it from the evidence, and every reason traces back to a specific piece of evidence.",
    cta: "Try a check now",
  },
};

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
