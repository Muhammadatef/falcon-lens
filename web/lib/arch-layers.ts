import type { Lang } from "./contracts";

/**
 * The architecture as three stacked layers (owner request, 24 Nov): voice assistant, the two AI agents, platform.
 * Every line describes shipped code only; the source file is named next to each step so a reviewer can check it
 * (web/tests/unit/arch-layers.test.ts verifies each path exists). No measured figure appears here.
 */
type Text = { t: string; d: string };
export interface LayerStep {
  id: string;
  /** Repository path that implements the step. */
  repo: string;
  ar: Text;
  en: Text;
}
export interface LayerGroup {
  id: string;
  /** Colour family: the Investigator, the Sentinel, or neutral. */
  tone: "inv" | "sen" | "plain";
  ar: Text;
  en: Text;
  /** true: the steps run in order (numbered, with arrows); false: a set of parts. */
  ordered: boolean;
  steps: LayerStep[];
}
export interface Layer {
  id: "voice" | "agents" | "platform";
  ar: Text;
  en: Text;
  groups: LayerGroup[];
}
export interface LayerLink {
  /** Sits under this layer. */
  after: Layer["id"];
  ar: string;
  en: string;
}

const CORE = "packages/falcon_core/src/falcon_core";
const SEN = "services/sentinel/src/falcon_sentinel";

const s = (id: string, repo: string, ar: Text, en: Text): LayerStep => ({ id, repo, ar, en });

export const LAYERS: readonly Layer[] = [
  {
    id: "voice",
    ar: { t: "طبقة المساعد الصوتي", d: "تقول «يا صقر» فيفهم طلبك على جهازنا نفسه، ثم يروي لك ما يفعله الوكيلان بصوت مسموع." },
    en: { t: "Voice assistant layer", d: "You say \"Hey Falcon\"; your request is understood on our own machine, then the assistant tells you aloud what the two agents do." },
    groups: [
      {
        id: "voice-path",
        tone: "plain",
        ordered: true,
        ar: { t: "من صوتك إلى الإجابة المسموعة", d: "مسار واحد مرتّب، وكل خطوة فيه شيفرة منشورة." },
        en: { t: "From your voice to a spoken answer", d: "One ordered path; every step is shipped code." },
        steps: [
          s("mic", "web/lib/vad.ts", { t: "ميكروفون المتصفح وكشف نهاية الكلام", d: "استماع بلا لمس. ينتهي المقطع بعد صمت قصير، ويُرسَل مقطع واحد قصير." }, { t: "Browser microphone and end-of-speech detection", d: "Hands-free listening. A clip ends after a short silence, and one short clip is sent." }),
          s("web-route", "web/app/api/voice/route.ts", { t: "مسار الويب ‎/api/voice", d: "مفتاح الخدمة يبقى على الخادم، ويُطبَّق حدّ للمعدّل لكل زائر." }, { t: "Web route /api/voice", d: "The service key stays on the server, and a rate limit applies per visitor." }),
          s("api", "services/api/src/falcon_api/voice.py", { t: "الواجهة البرمجية ‎/v1/voice/utterance", d: "يبقى الصوت في الذاكرة فقط: لا يُخزَّن ولا يُسجَّل." }, { t: "API /v1/voice/utterance", d: "Audio is held in memory only: never stored, never logged." }),
          s("stt", "services/voice/src/falcon_voice/app.py", { t: "تحويل الكلام إلى نص محلياً", d: "محرّك mlx-whisper (النموذج large-v3-turbo) على معالج الرسوميات في الجهاز، وحاوية faster-whisper (النموذج small) احتياطاً. لا خدمة كلام سحابية." }, { t: "Speech to text, locally", d: "mlx-whisper (large-v3-turbo) on the machine's own GPU; the faster-whisper container (small) as the fallback. No cloud speech service." }),
          s("wake", `${CORE}/voice/intent.py`, { t: "عبارة التنبيه واللغة", d: "«يا صقر» أو \"Hey Falcon\" بقواعد ثابتة، ويتبع الرد لغة كل جملة تقولها." }, { t: "Wake phrase and language", d: "\"Hey Falcon\" or «يا صقر» by fixed rules; the reply follows the language of each sentence you say." }),
          s("intent", `${CORE}/voice/faq_semantic.py`, { t: "فهم الطلب", d: "قواعد ثابتة أولاً، ثم نموذج تضمين محلي (qwen3-embedding) يطابق السؤال بأقرب سؤال مُعَدّ، وما عدا ذلك توجيه مهذّب إلى فحص الاحتيال. محاولات تغيير التعليمات تُرفَض." }, { t: "Intent", d: "Fixed rules first, then a local embedding model (qwen3-embedding) matches a question to the nearest prepared one; anything else gets a polite redirect to scam checking. Attempts to override the instructions are refused." }),
          s("actions", "web/components/VoiceAssistant.tsx", { t: "الإجراء", d: "فحص ما نسخته، أو إجابة سؤال عن الحماية من الاحتيال، أو مساعدة، أو إيقاف." }, { t: "Action", d: "Check what you copied, answer a scam-safety question, help, or stop." }),
          s("narration", "web/lib/voice-player.ts", { t: "الرواية الصوتية", d: "مقاطع مولَّدة مسبقاً من نصّنا: العربية بصوت Amazon Polly «زايد» الإماراتي، والإنجليزية بصوت Kokoro (am_fenrir). النص المعروض هو الكلام المنطوق نفسه، والخطوات مرقّمة." }, { t: "Narration", d: "Clips generated in advance from our own script: Arabic by Amazon Polly Zayd (Emirati), English by Kokoro (am_fenrir). The caption is exactly what is spoken, and the steps are numbered." }),
          s("trace", "web/components/HistoryBoard.tsx", { t: "الأثر", d: "يظهر الفحص الصوتي في السجل بشارة «صوت»، وله صف في لوحة Grafana." }, { t: "Trace", d: "A voice check appears in History with a Voice badge, and has its own row in Grafana." }),
        ],
      },
    ],
  },
  {
    id: "agents",
    ar: { t: "طبقة الوكيلين الذكيين", d: "«بصير»، المحقّق، يحكم على مدخل واحد. و«درع»، الحارس، يراقب كل الفحوص على مدار الساعة." },
    en: { t: "The two AI agents layer", d: "Baseer, the Investigator, judges one input. Dir', the Sentinel, watches every check around the clock." },
    groups: [
      {
        id: "baseer",
        tone: "inv",
        ordered: true,
        ar: { t: "«بصير»، المحقّق", d: "طبقات متتابعة، ولا يُستدعى النموذج إلا في الحالات الغامضة. الحكم يصدره محكّم حتمي، لا النموذج." },
        en: { t: "Baseer, the Investigator", d: "Tiers in order; a model is called only for the uncertain band. A deterministic arbiter sets the verdict, not the model." },
        steps: [
          s("t0", `${CORE}/signals/cache.py`, { t: "T0 · البلاغات المعروفة", d: "حكم حديث محفوظ، أو تطابق مع قائمة احتيال، أو موقع رسمي موثّق." }, { t: "T0 · Known reports", d: "A recent cached verdict, a scam-list match, or a verified official site." }),
          s("t1", `${CORE}/scoring/t1_model.py`, { t: "T1 · العنوان والنطاق", d: "تحليل العنوان وبيانات التسجيل ومصنِّف مُقاس." }, { t: "T1 · Address and domain", d: "URL analysis, registration data and a measured classifier." }),
          s("t2", "services/sandbox/src/falcon_sandbox/browser.py", { t: "T2 · المتصفح المعزول", d: "زيارة واحدة سلبية في شبكة معزولة، ومطابقة العلامة مع النطاق." }, { t: "T2 · Isolated browser", d: "One passive visit on an isolated network, and a brand-versus-domain check." }),
          s("t3", `${CORE}/agent/investigator.py`, { t: "T3 · نظرة الذكاء الاصطناعي", d: "للحالات الغامضة فقط، بأدوات محددة ومعتمدة. لا يغيّر الدرجة." }, { t: "T3 · AI second look", d: "Only for the uncertain band, with a short list of approved tools. It cannot change the score." }),
          s("arbiter", `${CORE}/scoring/arbiter.py`, { t: "المحكّم الحتمي", d: "شيفرة ثابتة تزن الأدلة وتصدر الحكم: خطِر، أو مريب، أو لم نجد علامات تحذير." }, { t: "Deterministic arbiter", d: "Fixed code weighs the evidence and sets the verdict: dangerous, suspicious, or no warning signs found." }),
          s("route", `${CORE}/llm/router.py`, { t: "مسار النموذج", d: "Claude مع بديل محلي (Inkling)، أو محلي فقط (Inkling أو Qwen 3.8). يختاره المشغّل من صفحة ‎/ops، والوضع السيادي يثبّته محلياً." }, { t: "Model route", d: "Claude with a local fallback (Inkling), or local only (Inkling or Qwen 3.8). An operator picks it on /ops; sovereign mode locks it to local." }),
        ],
      },
      {
        id: "dir",
        tone: "sen",
        ordered: true,
        ar: { t: "«درع»، الحارس", d: "القواعد هي التي تقرر ما الحادثة. والنموذج يلخّص ويقترح فقط، وكل إجراء خارجي ينتظر موافقة إنسان." },
        en: { t: "Dir', the Sentinel", d: "Rules decide what an incident is. The model only summarises and proposes, and every outside action waits for a person." },
        steps: [
          s("listen", `${SEN}/consumer.py`, { t: "يستمع لكل فحص", d: "يستهلك أحداث الفحوص المنتهية من ناقل الأحداث." }, { t: "Listens to every check", d: "Consumes finished-check events from the event bus." }),
          s("correlate", "services/sentinel/sentinel_core/correlate.py", { t: "يربط المتشابه", d: "العلامة المنتحَلة نفسها، أو بصمة الصفحة نفسها، أو نمط النطاق الشبيه نفسه." }, { t: "Correlates", d: "The same impersonated brand, the same page fingerprint, or the same lookalike-domain pattern." }),
          s("rules", "services/sentinel/sentinel_core/rules.py", { t: "القواعد تقرر الحادثة", d: "قواعد ثابتة تفتح الحادثة وتحدد شدتها." }, { t: "Rules decide the incident", d: "Fixed rules open the incident and set its severity." }),
          s("graph", `${SEN}/graph.py`, { t: "فرز بمخطط LangGraph", d: "جمع السياق، والمقارنة، والتقدير، والتلخيص، واقتراح الإجراءات، مع حفظ الحالة." }, { t: "LangGraph triage", d: "Gather context, compare, assess, summarise and propose actions, with checkpointed state." }),
          s("approval", "web/components/IncidentBoard.tsx", { t: "موافقة بشرية", d: "الإجراءات الداخلية تلقائية وقابلة للتراجع. أما مسوّدات طلبات الإزالة والبلاغات فتنتظر موافقة مشغّل." }, { t: "Human approval", d: "Internal actions are automatic and reversible. Takedown and report drafts wait for an operator." }),
          s("campaigns", "web/components/CampaignBoard.tsx", { t: "الحوادث والحملات", d: "تظهر في لوحة الحملات العامة وفي سجل عمل الوكيلين." }, { t: "Incidents and campaigns", d: "Shown on the public campaigns board and in the agent run history." }),
        ],
      },
    ],
  },
  {
    id: "platform",
    ar: { t: "طبقة المنصة", d: "الخدمات التي يعمل فوقها الوكيلان: الواجهات، والأحداث، والبيانات، والعزل، والربط، والمراقبة." },
    en: { t: "Platform layer", d: "The services the agents run on: interfaces, events, data, isolation, integration and monitoring." },
    groups: [
      {
        id: "platform-parts",
        tone: "plain",
        ordered: false,
        ar: { t: "مكوّنات المنصة", d: "كلها في حزمة Docker Compose واحدة." },
        en: { t: "Platform parts", d: "All in one Docker Compose stack." },
        steps: [
          s("rest", "contracts/openapi.yaml", { t: "الواجهة البرمجية REST v1 وبث SSE", d: "طلب الفحص، وبث مباشر لخطوات الحكم، ومفاتيح بصلاحيات وحدود للمعدّل." }, { t: "REST v1 API and SSE", d: "Check requests, a live stream of verdict steps, scoped keys and rate limits." }),
          s("bus", "contracts/event.schema.json", { t: "ناقل الأحداث (Redis Streams)", d: "يُعلَن عن كل فحص منتهٍ ليلتقطه «درع»." }, { t: "Event bus (Redis Streams)", d: "Every finished check is announced so that Dir' picks it up." }),
          s("store", "services/sentinel/migrations", { t: "Postgres و pgvector", d: "الأحكام والأدلة والحوادث وسجل التدقيق، ومتجهات نصوص الاحتيال." }, { t: "Postgres and pgvector", d: "Verdicts, evidence, incidents and the audit log, plus scam-script vectors." }),
          s("sandbox", "services/egress", { t: "البيئة المعزولة ووسيط الخروج", d: "المتصفح في شبكة معزولة، ولا يخرج أي اتصال إلا عبر وسيط يمنع العناوين الداخلية." }, { t: "Sandbox and egress proxy", d: "The browser sits on an isolated network; nothing leaves except through a proxy that blocks private addresses." }),
          s("integ", "services/mcp/src/falcon_mcp/server.py", { t: "MCP و STIX 2.1 والإشعارات (webhooks)", d: "جاهز للربط مع أنظمة الجهات المختصة، وغير مربوط بأي جهة." }, { t: "MCP, STIX 2.1 and webhooks", d: "Ready to connect to the authorities' systems; not connected to any." }),
          s("obs", "infra/prometheus", { t: "المراقبة", d: "Prometheus و Grafana و Alertmanager، وتتبّع نداءات النموذج في Phoenix." }, { t: "Observability", d: "Prometheus, Grafana and Alertmanager, with model-call traces in Phoenix." }),
          s("pages", "web/app/history/page.tsx", { t: "الصفحات العامة", d: "الفحص، والسجل، ومسار كل فحص وحادثة، والحملات، والنتائج. للقراءة فقط." }, { t: "Public pages", d: "Check, History, the trace of each check and incident, Campaigns and Results. Read-only." }),
        ],
      },
    ],
  },
];

export const LAYER_LINKS: readonly LayerLink[] = [
  { after: "voice", ar: "واجهة الفحص العامة نفسها التي تستخدمها صفحة الفحص", en: "The same public check API as the Check page" },
  { after: "agents", ar: "الحكم يعود ببث مباشر، وحدث لكل فحص منتهٍ على ناقل الأحداث", en: "The verdict returns as a live stream, and each finished check is an event on the bus" },
];

export const LAYERS_UI: Record<Lang, { title: string; lead: string; other: Lang; stepsLabel: string; partsLabel: string; flow: string }> = {
  ar: { title: "البنية في ثلاث طبقات", lead: "من صوتك في الأعلى إلى المنصة في الأسفل. اضغط على أي طبقة لطيّها أو فتحها.", other: "en", stepsLabel: "الخطوات بالترتيب", partsLabel: "المكوّنات", flow: "يمرّ الطلب من الأعلى إلى الأسفل" },
  en: { title: "The architecture in three layers", lead: "From your voice at the top to the platform at the bottom. Select a layer to fold or open it.", other: "ar", stepsLabel: "Steps in order", partsLabel: "Parts", flow: "A request travels from top to bottom" },
};
