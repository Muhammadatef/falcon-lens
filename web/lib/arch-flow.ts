/**
 * Animated architecture diagrams (components/arch/FlowDiagram.tsx): structure and words, data only.
 *
 * One spec per diagram: bands of groups of nodes, plus the ordered request path the animation follows.
 * Every node carries a badge (a vendored tool logo, a text badge for a tool whose logo is not vendored, or one of
 * our own icons for our own code), a label and one short line in Arabic and English, the capability flag that
 * drives its Live / In progress status, and the repository path that implements it
 * (tests/unit/arch-flow.test.ts checks all of that). Only tools the shipped code uses appear here. No measured
 * figure appears here. This file imports types only, so scripts/build-arch-svg.mjs can load it directly.
 */
import type { IconName } from "@/components/Icon";
import type { CapId } from "./capabilities";
import type { LogoSlug } from "./tool-logos.gen";

export type FlowLang = "ar" | "en";
export type L = Record<FlowLang, string>;
export type Badge = { logo: LogoSlug } | { mono: string; tool: string } | { icon: IconName };

export interface FlowNode {
  id: string;
  badge: Badge;
  label: L;
  sub: L;
  cap: CapId;
  /** Implementation file or directory, relative to the repository root. */
  repo: string;
  /** Node id in lib/arch-graph.ts whose full detail panel opens on click, when there is one. */
  graph?: string;
  /** A model step (drawn with a dashed edge, as in the legend). */
  llm?: boolean;
}
export interface FlowGroup {
  id: string;
  tone: "inv" | "sen" | "plain";
  title?: L;
  badge?: Badge;
  nodes: readonly FlowNode[];
}
export interface FlowBand {
  id: string;
  icon: IconName;
  title: L;
  sub: L;
  groups: readonly FlowGroup[];
}
export interface FlowStep {
  node: string;
  caption: L;
}
export interface FlowSpec {
  id: "main" | "baseer" | "dir" | "dspy" | "route";
  title: L;
  lead: L;
  bands: readonly FlowBand[];
  steps: readonly FlowStep[];
}

const CORE = "packages/falcon_core/src/falcon_core";
const SEN = "services/sentinel/src/falcon_sentinel";
const t = (en: string, ar: string): L => ({ en, ar });
const n = (id: string, badge: Badge, label: L, sub: L, cap: CapId, repo: string, extra: { graph?: string; llm?: boolean } = {}): FlowNode => ({ id, badge, label, sub, cap, repo, ...extra });
const logo = (slug: LogoSlug): Badge => ({ logo: slug });
const mono = (text: string, tool: string): Badge => ({ mono: text, tool });
const icon = (name: IconName): Badge => ({ icon: name });
const same = (s: string): L => ({ en: s, ar: s });

/* Tools without a vendored logo: a neutral text badge that carries the tool's name (public/logos/tools/LOGOS_LICENSES.md). */
const WHISPER = mono("Wh", "Whisper");
const POLLY = mono("Po", "Amazon Polly");
const KOKORO = mono("Ko", "Kokoro");
const PLAYWRIGHT = mono("Pw", "Playwright");
const PGVECTOR = mono("pgv", "pgvector");
const PHOENIX = mono("Px", "Arize Phoenix");
const LOKI = mono("Lo", "Grafana Loki");
const ALERTMANAGER = mono("Am", "Alertmanager");
const DSPY = mono("DS", "DSPy");
const INKLING = mono("In", "Inkling");
const STIX = mono("STIX", "STIX 2.1");

/* ── 1. Main architecture: voice, the two agents, the platform ───────────────────────────────────────────── */
export const MAIN_FLOW: FlowSpec = {
  id: "main",
  title: t("The architecture in three layers", "البنية في ثلاث طبقات"),
  lead: t(
    "Follow one request: your voice at the top, the two agents in the middle, the platform underneath. Every box is shipped code, shown with the logo of the tool it runs on. Select a box to read what it does.",
    "تابِع طلباً واحداً: صوتك في الأعلى، والوكيلان في الوسط، والمنصة في الأسفل. كل مربع شيفرة منشورة، ومعه شعار الأداة التي يعمل عليها. اختر أي مربع لتقرأ ما يفعله.",
  ),
  bands: [
    {
      id: "voice",
      icon: "mic",
      title: t("Voice layer · \"Hey Falcon\"", "طبقة الصوت · «يا صقر»"),
      sub: t("Speech is understood on our own machine. Answers are spoken from clips prepared in advance.", "يُفهَم الكلام على جهازنا نفسه، وتُنطَق الإجابات من مقاطع مُعَدّة مسبقاً."),
      groups: [
        {
          id: "voice-path",
          tone: "plain",
          nodes: [
            n("v_mic", icon("mic"), t("Browser microphone", "ميكروفون المتصفح"), t("You say \"Hey Falcon\"", "تقول «يا صقر»"), "voice_assistant", "web/lib/vad.ts", { graph: "voice_mic" }),
            n("v_stt", WHISPER, t("Whisper speech to text", "Whisper: الكلام إلى نص"), t("mlx-whisper, on our machine", "mlx-whisper على جهازنا"), "voice_assistant", "services/voice/src/falcon_voice/app.py", { graph: "voice_stt" }),
            n("v_intent", icon("list"), t("Wake phrase and intent", "عبارة التنبيه وفهم الطلب"), t("Fixed rules first", "قواعد ثابتة أولاً"), "voice_assistant", `${CORE}/voice/intent.py`, { graph: "voice_intent" }),
            n("v_polly", POLLY, t("Amazon Polly · Zayd", "Amazon Polly · زايد"), t("Arabic clips, made in advance", "مقاطع عربية مُعَدّة مسبقاً"), "voice_assistant", "tools/voice_clips/src/voice_clips/engines.py"),
            n("v_kokoro", KOKORO, same("Kokoro"), t("English clips, made in advance", "مقاطع إنجليزية مُعَدّة مسبقاً"), "voice_assistant", "tools/voice_clips/src/voice_clips/engines.py"),
            n("v_earcons", icon("spark"), t("Earcons", "الإشارات الصوتية"), t("One short sound per verdict", "نغمة قصيرة لكل حكم"), "voice_assistant", "web/public/voice/sfx"),
          ],
        },
      ],
    },
    {
      id: "agents",
      icon: "spark",
      title: t("The two AI agents", "الوكيلان الذكيان"),
      sub: t("Baseer judges one input. Dir' watches every check around the clock.", "«بصير» يحكم على مدخل واحد، و«درع» يراقب كل الفحوص على مدار الساعة."),
      groups: [
        {
          id: "baseer",
          tone: "inv",
          title: t("Baseer, the Investigator", "«بصير»، المحقّق"),
          nodes: [
            n("t0", logo("redis"), t("T0 · Known reports", "T0 · البلاغات المعروفة"), t("Redis cache and scam-list mirror", "ذاكرة Redis ونسخة قائمة الاحتيال"), "url_check", `${CORE}/signals/cache.py`, { graph: "t0" }),
            n("t1", logo("scikitlearn"), t("T1 · Address and domain", "T1 · العنوان والنطاق"), t("scikit-learn classifier", "مصنِّف scikit-learn"), "t1_measured_model", `${CORE}/scoring/t1_model.py`, { graph: "t1" }),
            n("t2", PLAYWRIGHT, t("T2 · Isolated browser", "T2 · المتصفح المعزول"), t("One passive Playwright visit", "زيارة واحدة سلبية عبر Playwright"), "brand_check", "services/sandbox/src/falcon_sandbox/browser.py", { graph: "t2" }),
            n("t3", icon("spark"), t("T3 · AI second look", "T3 · نظرة الذكاء الاصطناعي"), t("Bounded model, unclear cases only", "نموذج مقيَّد للحالات الغامضة فقط"), "investigator", `${CORE}/agent/investigator.py`, { graph: "t3", llm: true }),
            n("arbiter", icon("scale"), t("Deterministic arbiter", "المحكّم الحتمي"), t("Fixed code sets the verdict", "شيفرة ثابتة تصدر الحكم"), "url_check", `${CORE}/scoring/arbiter.py`, { graph: "arbiter" }),
            n("verdict", icon("no_warning_signs"), t("Verdict and reasons", "الحكم وأسبابه"), t("Streamed to your screen", "يُبَثّ إلى شاشتك مباشرة"), "investigator", `${CORE}/agent/responder.py`, { graph: "verdict" }),
          ],
        },
        {
          id: "dir",
          tone: "sen",
          title: t("Dir', the Sentinel", "«درع»، الحارس"),
          nodes: [
            n("s_correlate", icon("url"), t("Correlation", "ربط المتشابه"), t("Same brand, page or domain pattern", "العلامة أو الصفحة أو نمط النطاق نفسه"), "sentinel_rules", "services/sentinel/sentinel_core/correlate.py", { graph: "correlate" }),
            n("s_rules", icon("list"), t("Incident rules", "قواعد الحوادث"), t("Fixed rules open the incident", "قواعد ثابتة تفتح الحادثة"), "sentinel_rules", "services/sentinel/sentinel_core/rules.py", { graph: "rules" }),
            n("s_graph", logo("langgraph"), same("LangGraph StateGraph"), t("Six steps, checkpointed", "ست خطوات مع حفظ الحالة"), "sentinel_agent", `${SEN}/graph.py`, { graph: "enrich", llm: true }),
            n("s_incident", logo("postgresql"), t("Incident and audit log", "الحادثة وسجل التدقيق"), t("Append-only, in PostgreSQL", "إضافة فقط، في PostgreSQL"), "audit_log", `${SEN}/db.py`, { graph: "audit" }),
            n("s_approval", icon("hand"), t("Human approval", "موافقة بشرية"), t("Outside actions wait for a person", "الإجراءات الخارجية تنتظر إنساناً"), "sentinel_agent", "web/components/IncidentBoard.tsx", { graph: "approval" }),
          ],
        },
      ],
    },
    {
      id: "platform",
      icon: "box",
      title: t("Platform", "المنصة"),
      sub: t("The services both agents run on, in one Docker Compose stack.", "الخدمات التي يعمل فوقها الوكيلان، في حزمة Docker Compose واحدة."),
      groups: [
        {
          id: "interfaces",
          tone: "plain",
          title: t("Interfaces", "الواجهات"),
          nodes: [
            n("p_api", logo("fastapi"), same("FastAPI"), t("REST v1 and live stream", "REST v1 وبث مباشر"), "rest_api", "services/api/src/falcon_api/app.py", { graph: "api" }),
            n("p_mcp", logo("modelcontextprotocol"), t("MCP server", "خادم MCP"), t("Ready to connect; not connected", "جاهز للربط وغير مربوط"), "mcp", "services/mcp/src/falcon_mcp/server.py", { graph: "mcp" }),
            n("p_stix", STIX, t("STIX 2.1 export", "تصدير STIX 2.1"), t("Standard incident format", "صيغة قياسية للحوادث"), "stix", `${CORE}/tools/stix.py`, { graph: "stix" }),
            n("p_web", logo("nextdotjs"), t("Next.js web app", "تطبيق الويب Next.js"), t("Arabic-first, installable", "عربي أولاً وقابل للتثبيت"), "pwa", "web/app/page.tsx", { graph: "clients" }),
          ],
        },
        {
          id: "data",
          tone: "plain",
          title: t("Events and data", "الأحداث والبيانات"),
          nodes: [
            n("p_redis", logo("redis"), same("Redis Streams"), t("Event bus", "ناقل الأحداث"), "pipeline", `${SEN}/consumer.py`, { graph: "bus" }),
            n("p_pg", logo("postgresql"), same("PostgreSQL"), t("Verdicts, evidence, incidents", "الأحكام والأدلة والحوادث"), "audit_log", "services/sentinel/migrations"),
            n("p_pgvector", PGVECTOR, same("pgvector"), t("Scam-script vectors", "متجهات نصوص الاحتيال"), "message_check", `${CORE}/signals/message/scripts.py`),
          ],
        },
        {
          id: "isolation",
          tone: "plain",
          title: t("Isolation", "العزل"),
          nodes: [
            n("p_sandbox", PLAYWRIGHT, t("Playwright sandbox", "بيئة Playwright المعزولة"), t("Isolated network, no forms", "شبكة معزولة ولا إرسال للنماذج"), "brand_check", "services/sandbox/src/falcon_sandbox/browser.py", { graph: "t2" }),
            n("p_egress", icon("keep"), t("Egress proxy", "وسيط الخروج"), t("Blocks private addresses", "يمنع العناوين الداخلية"), "brand_check", "services/egress/src/falcon_egress/guard.py"),
          ],
        },
        {
          id: "models",
          tone: "plain",
          title: t("Models", "النماذج"),
          nodes: [
            n("p_router", icon("refresh"), t("Model router", "موجِّه النماذج"), t("Cloud, or local only", "سحابي أو محلي فقط"), "sovereign", `${CORE}/llm/router.py`, { graph: "router" }),
            n("p_claude", logo("claude"), same("Claude API"), t("Cloud route", "المسار السحابي"), "sovereign", `${CORE}/llm/providers.py`, { graph: "cloud", llm: true }),
            n("p_ollama", logo("ollama"), same("Ollama"), t("Serves the local models", "يشغّل النماذج المحلية"), "sovereign", "infra/ollama", { graph: "local", llm: true }),
            n("p_inkling", INKLING, same("Inkling"), t("Local model", "نموذج محلي"), "sovereign", "infra/ollama/Inkling-2-Mini.chat.Modelfile", { llm: true }),
            n("p_qwen", logo("qwen"), same("Qwen"), t("Local model", "نموذج محلي"), "sovereign", `${CORE}/llm/config.py`, { llm: true }),
            n("p_dspy", DSPY, same("DSPy"), t("Prompts tuned offline", "مطالبات تُضبَط خارج التشغيل"), "dspy_compiled_prompts", "evals/dspy/optimize.py", { graph: "dspy" }),
          ],
        },
        {
          id: "observability",
          tone: "plain",
          title: t("Observability", "المراقبة"),
          nodes: [
            n("p_otel", logo("opentelemetry"), same("OpenTelemetry"), t("Collects traces", "يجمع الآثار"), "llm_tracing", "infra/otel"),
            n("p_phoenix", PHOENIX, same("Arize Phoenix"), t("Model-call traces", "آثار نداءات النموذج"), "llm_tracing", `${CORE}/telemetry/tracing.py`, { graph: "phoenix" }),
            n("p_prom", logo("prometheus"), same("Prometheus"), t("Metrics and alert rules", "المقاييس وقواعد التنبيه"), "observability", "infra/prometheus", { graph: "prometheus" }),
            n("p_grafana", logo("grafana"), same("Grafana"), t("Dashboards", "لوحات المتابعة"), "observability", "infra/grafana/dashboards", { graph: "grafana" }),
            n("p_loki", LOKI, same("Loki"), t("Logs", "السجلات"), "observability", "infra/loki"),
            n("p_alert", ALERTMANAGER, same("Alertmanager"), t("Alerts", "التنبيهات"), "observability", "infra/alertmanager"),
          ],
        },
        {
          id: "runtime",
          tone: "plain",
          title: t("Runtime", "التشغيل"),
          nodes: [
            n("p_caddy", logo("caddy"), same("Caddy"), t("Gateway", "البوابة"), "rest_api", "infra/gateway/Caddyfile"),
            n("p_tunnel", logo("cloudflare"), same("Cloudflare Tunnel"), t("Public demo address", "عنوان العرض العام"), "rest_api", "infra/demo_mode.yaml"),
            n("p_docker", logo("docker"), same("Docker Compose"), t("One stack", "حزمة واحدة"), "rest_api", "docker-compose.yml"),
          ],
        },
      ],
    },
  ],
  steps: [
    { node: "v_mic", caption: t("You say \"Hey Falcon\" and ask for a check. The browser records one short clip.", "تقول «يا صقر» وتطلب فحصاً، فيسجّل المتصفح مقطعاً قصيراً واحداً.") },
    { node: "v_stt", caption: t("Whisper turns the clip into text on our own machine. The audio is not stored.", "يحوّل Whisper المقطع إلى نص على جهازنا نفسه، ولا يُخزَّن الصوت.") },
    { node: "v_intent", caption: t("Fixed rules find the wake phrase and what you asked. The check then starts.", "قواعد ثابتة تتعرّف عبارة التنبيه وطلبك، ثم يبدأ الفحص.") },
    { node: "t0", caption: t("Baseer, T0: is this already known? A recent verdict, a scam-list match or a verified official site.", "«بصير»، T0: هل هذا معروف من قبل؟ حكم حديث، أو تطابق مع قائمة احتيال، أو موقع رسمي موثّق.") },
    { node: "t1", caption: t("T1 studies the address and the domain, and a measured classifier scores them.", "T1 يحلّل العنوان والنطاق، ويقيّمهما مصنِّف مُقاس.") },
    { node: "t2", caption: t("T2 opens the page once, passively, in an isolated browser and compares it with the real brand.", "T2 يفتح الصفحة مرة واحدة دون تفاعل في متصفح معزول، ويقارنها بالعلامة الحقيقية.") },
    { node: "t3", caption: t("T3, unclear cases only: a bounded model gathers a little more evidence. It cannot change the score.", "T3، للحالات الغامضة فقط: نموذج مقيَّد يجمع أدلة إضافية قليلة، ولا يستطيع تغيير الدرجة.") },
    { node: "arbiter", caption: t("The deterministic arbiter weighs the evidence. Fixed code sets the verdict, not the model.", "المحكّم الحتمي يزن الأدلة. الشيفرة الثابتة هي التي تصدر الحكم، لا النموذج.") },
    { node: "verdict", caption: t("The verdict and its reasons reach your screen, and are spoken aloud.", "يصل الحكم وأسبابه إلى شاشتك، ويُنطَق بصوت مسموع.") },
    { node: "p_redis", caption: t("Every finished check is announced on the event bus (Redis Streams).", "يُعلَن عن كل فحص منتهٍ على ناقل الأحداث (Redis Streams).") },
    { node: "s_correlate", caption: t("Dir' links related checks: the same brand, the same page or the same domain pattern.", "«درع» يربط الفحوص المتشابهة: العلامة نفسها، أو الصفحة نفسها، أو نمط النطاق نفسه.") },
    { node: "s_rules", caption: t("Fixed rules decide that the group is an incident, and how severe it is.", "قواعد ثابتة تقرر أن المجموعة حادثة، وتحدد شدتها.") },
    { node: "s_graph", caption: t("A LangGraph graph gathers context, summarises and proposes actions. Its state is checkpointed.", "مخطط LangGraph يجمع السياق ويلخّص ويقترح الإجراءات، مع حفظ حالته.") },
    { node: "s_incident", caption: t("The incident and every action are written to an append-only audit log.", "تُكتَب الحادثة وكل إجراء في سجل تدقيق لا يقبل إلا الإضافة.") },
    { node: "s_approval", caption: t("Anything that would leave the system stays a draft until a person approves it.", "كل ما قد يخرج من النظام يبقى مسوّدة إلى أن يوافق عليه إنسان.") },
  ],
};

/* ── 2. Baseer, the Investigator: cascade, bounded loop, arbiter ─────────────────────────────────────────── */
export const BASEER_FLOW: FlowSpec = {
  id: "baseer",
  title: t("Baseer in motion: cascade, bounded loop, arbiter", "«بصير» أثناء العمل: طبقات متتابعة، ثم حلقة مقيَّدة، ثم المحكّم"),
  lead: t("Deterministic tiers first. A model joins only for the uncertain band, inside a bounded loop, and fixed code decides.", "الطبقات الحتمية أولاً. ولا يشارك النموذج إلا في الحالات الغامضة، داخل حلقة مقيَّدة، والقرار للشيفرة الثابتة."),
  bands: [
    {
      id: "cascade",
      icon: "list",
      title: t("Deterministic cascade", "الطبقات الحتمية"),
      sub: t("Most checks end here, with no model call.", "تنتهي أغلب الفحوص هنا دون استدعاء أي نموذج."),
      groups: [
        {
          id: "tiers",
          tone: "inv",
          nodes: [
            n("b_t0", logo("redis"), t("T0 · Known reports", "T0 · البلاغات المعروفة"), t("Redis cache and scam-list mirror", "ذاكرة Redis ونسخة قائمة الاحتيال"), "url_check", `${CORE}/signals/cache.py`, { graph: "t0" }),
            n("b_t1", logo("scikitlearn"), t("T1 · Address and domain", "T1 · العنوان والنطاق"), t("scikit-learn classifier", "مصنِّف scikit-learn"), "t1_measured_model", `${CORE}/scoring/t1_model.py`, { graph: "t1" }),
            n("b_t2", PLAYWRIGHT, t("T2 · Isolated browser", "T2 · المتصفح المعزول"), t("One passive Playwright visit", "زيارة واحدة سلبية عبر Playwright"), "brand_check", "services/sandbox/src/falcon_sandbox/browser.py", { graph: "t2" }),
          ],
        },
      ],
    },
    {
      id: "loop",
      icon: "spark",
      title: t("T3 · bounded loop", "T3 · الحلقة المقيَّدة"),
      sub: t("Plan, act, observe, decide. At most 6 typed tool calls.", "تخطيط فتنفيذ فملاحظة فقرار. 6 استدعاءات أدوات مكتوبة على الأكثر."),
      groups: [
        {
          id: "machine",
          tone: "inv",
          title: t("State machine", "آلة الحالات"),
          nodes: [
            n("b_plan", icon("spark"), same("plan"), t("The model emits one typed action", "النموذج يُخرج إجراءً مكتوباً واحداً"), "investigator", `${CORE}/agent/investigator.py`, { graph: "t3", llm: true }),
            n("b_act", icon("box"), same("act"), t("Code validates it, then runs the tool", "الشيفرة تتحقق منه ثم تشغّل الأداة"), "investigator", `${CORE}/tools/registry.py`, { graph: "t3" }),
            n("b_observe", icon("eye"), same("observe"), t("New evidence joins the case", "تنضمّ الأدلة الجديدة إلى الحالة"), "investigator", `${CORE}/agent/investigator.py`, { graph: "t3" }),
            n("b_decide", icon("flag"), same("decide"), t("Stop, or one more step", "توقّف أو خطوة أخرى"), "investigator", `${CORE}/agent/investigator.py`, { graph: "t3" }),
          ],
        },
        {
          id: "support",
          tone: "plain",
          title: t("What the loop may use", "ما يجوز للحلقة استخدامه"),
          nodes: [
            n("b_tools", icon("list"), t("Tool registry", "سجل الأدوات"), t("Approved, typed tools only", "أدوات معتمدة ومكتوبة فقط"), "investigator", `${CORE}/tools/registry.py`, { graph: "toolbox_inv" }),
            n("b_router", icon("refresh"), t("Model router", "موجِّه النماذج"), t("Redacts, then picks the route", "يحجب البيانات ثم يختار المسار"), "sovereign", `${CORE}/llm/router.py`, { graph: "router" }),
            n("b_claude", logo("claude"), same("Claude API"), t("Cloud route", "المسار السحابي"), "sovereign", `${CORE}/llm/providers.py`, { graph: "cloud", llm: true }),
            n("b_ollama", logo("ollama"), same("Ollama"), t("Local route", "المسار المحلي"), "sovereign", "infra/ollama", { graph: "local", llm: true }),
          ],
        },
      ],
    },
    {
      id: "decision",
      icon: "scale",
      title: t("Decision", "القرار"),
      sub: t("Fixed code sets the score and the verdict.", "الشيفرة الثابتة هي التي تحدد الدرجة والحكم."),
      groups: [
        {
          id: "out",
          tone: "inv",
          nodes: [
            n("b_arbiter", icon("scale"), t("Deterministic arbiter", "المحكّم الحتمي"), t("Weighs all evidence", "يزن كل الأدلة"), "url_check", `${CORE}/scoring/arbiter.py`, { graph: "arbiter" }),
            n("b_verdict", icon("no_warning_signs"), t("Verdict and reasons", "الحكم وأسبابه"), t("Each reason cites evidence", "كل سبب يستند إلى دليل"), "investigator", `${CORE}/agent/responder.py`, { graph: "verdict", llm: true }),
            n("b_bus", logo("redis"), same("Redis Streams"), t("The finished check is announced", "يُعلَن عن الفحص المنتهي"), "pipeline", `${SEN}/consumer.py`, { graph: "bus" }),
          ],
        },
      ],
    },
  ],
  steps: [
    { node: "b_t0", caption: t("T0 looks for an answer we already hold.", "T0 يبحث عن إجابة لدينا من قبل.") },
    { node: "b_t1", caption: t("T1 scores the address and the domain with a measured classifier.", "T1 يقيّم العنوان والنطاق بمصنِّف مُقاس.") },
    { node: "b_t2", caption: t("T2 visits the page once in the isolated browser and returns features only.", "T2 يزور الصفحة مرة واحدة في المتصفح المعزول، ويعيد السمات فقط.") },
    { node: "b_plan", caption: t("Uncertain band only. plan: the model reads structured evidence and emits one typed action.", "للحالات الغامضة فقط. plan: يقرأ النموذج أدلة منظَّمة ويُخرج إجراءً مكتوباً واحداً.") },
    { node: "b_act", caption: t("act: code checks the action against the tool registry, then runs it.", "act: تتحقق الشيفرة من الإجراء في سجل الأدوات ثم تنفّذه.") },
    { node: "b_tools", caption: t("Only approved tools exist: registration data, certificates, the sealed browser, brand comparison and more.", "لا توجد إلا أدوات معتمدة: بيانات التسجيل، والشهادات، والمتصفح المعزول، ومقارنة العلامة، وغيرها.") },
    { node: "b_observe", caption: t("observe: the new evidence is added to the case.", "observe: تُضاف الأدلة الجديدة إلى الحالة.") },
    { node: "b_decide", caption: t("decide: stop, or plan one more step. The loop ends after at most 6 tool calls.", "decide: توقّف أو خطّط لخطوة أخرى. تنتهي الحلقة بعد 6 استدعاءات أدوات على الأكثر.") },
    { node: "b_arbiter", caption: t("The arbiter weighs all the evidence and sets the verdict. No model can change it.", "المحكّم يزن كل الأدلة ويصدر الحكم، ولا يستطيع أي نموذج تغييره.") },
    { node: "b_verdict", caption: t("Up to three short reasons are written; a reason without valid evidence is dropped.", "تُكتَب ثلاثة أسباب قصيرة على الأكثر، ويُحذَف كل سبب بلا دليل صحيح.") },
    { node: "b_bus", caption: t("The finished check is announced on the event bus for Dir'.", "يُعلَن عن الفحص المنتهي على ناقل الأحداث ليلتقطه «درع».") },
  ],
};

/* ── 3. Dir', the Sentinel: events, rules, the LangGraph graph, the human gate ───────────────────────────── */
export const DIR_FLOW: FlowSpec = {
  id: "dir",
  title: t("Dir' in motion: events, rules, the LangGraph graph, a human gate", "«درع» أثناء العمل: أحداث، ثم قواعد، ثم مخطط LangGraph، ثم بوابة بشرية"),
  lead: t("Rules decide what an incident is. The graph enriches it and proposes actions; a person approves anything external.", "القواعد هي التي تقرر ما الحادثة. والمخطط يُثريها ويقترح الإجراءات، وكل إجراء خارجي يوافق عليه إنسان."),
  bands: [
    {
      id: "events",
      icon: "list",
      title: t("Events and rules, in code", "الأحداث والقواعد، بالشيفرة"),
      sub: t("No model takes part in deciding that something is an incident.", "لا يشارك أي نموذج في تقرير أن شيئاً ما حادثة."),
      groups: [
        {
          id: "pre",
          tone: "sen",
          nodes: [
            n("d_bus", logo("redis"), same("Redis Streams"), t("Finished-check events", "أحداث الفحوص المنتهية"), "pipeline", `${SEN}/consumer.py`, { graph: "bus" }),
            n("d_correlate", icon("url"), t("Correlation", "ربط المتشابه"), t("Groups related checks", "يجمع الفحوص المتشابهة"), "sentinel_rules", "services/sentinel/sentinel_core/correlate.py", { graph: "correlate" }),
            n("d_rules", icon("list"), t("Incident rules", "قواعد الحوادث"), t("Open the incident, set severity", "تفتح الحادثة وتحدد شدتها"), "sentinel_rules", "services/sentinel/sentinel_core/rules.py", { graph: "rules" }),
          ],
        },
      ],
    },
    {
      id: "graph",
      icon: "spark",
      title: t("The triage graph", "مخطط الفرز"),
      sub: t("Six steps in a fixed order. State is saved after each one.", "ست خطوات بترتيب ثابت، وتُحفَظ الحالة بعد كل خطوة."),
      groups: [
        {
          id: "stategraph",
          tone: "sen",
          title: same("LangGraph StateGraph"),
          badge: logo("langgraph"),
          nodes: [
            n("d_enrich", icon("list"), same("enrich"), t("Read-only context", "سياق للقراءة فقط"), "sentinel_agent", `${SEN}/graph.py`, { graph: "enrich" }),
            n("d_compare", icon("scale"), same("compare"), t("Seen before? In code", "هل تكرّر؟ بالشيفرة"), "sentinel_agent", `${SEN}/graph.py`, { graph: "compare" }),
            n("d_assess", icon("spark"), same("assess"), t("Explains the severity", "يشرح سبب الشدة"), "sentinel_agent", `${SEN}/llm.py`, { graph: "assess", llm: true }),
            n("d_summarise", icon("spark"), same("summarise"), t("Bilingual summary", "ملخص بالعربية والإنجليزية"), "sentinel_agent", `${SEN}/llm.py`, { graph: "summarise", llm: true }),
            n("d_propose", icon("spark"), same("propose"), t("Typed actions, validated", "إجراءات مكتوبة يُتحقَّق منها"), "sentinel_agent", `${SEN}/graph.py`, { graph: "propose", llm: true }),
            n("d_act", icon("box"), same("act"), t("Internal steps, external drafts", "خطوات داخلية ومسوّدات خارجية"), "sentinel_agent", `${SEN}/graph.py`, { graph: "act" }),
          ],
        },
        {
          id: "state",
          tone: "plain",
          title: t("State and models", "الحالة والنماذج"),
          nodes: [
            n("d_ckpt", logo("postgresql"), t("Postgres checkpointer", "نقطة التفتيش في Postgres"), t("Resumes after a restart", "يستأنف بعد إعادة التشغيل"), "sentinel_agent", `${SEN}/graph.py`, { graph: "approval" }),
            n("d_router", icon("refresh"), t("Model router", "موجِّه النماذج"), t("Structured evidence only", "أدلة منظَّمة فقط"), "sovereign", `${CORE}/llm/router.py`, { graph: "router" }),
          ],
        },
      ],
    },
    {
      id: "gate",
      icon: "hand",
      title: t("Human gate and record", "البوابة البشرية والسجل"),
      sub: t("Nothing is sent outside the system automatically.", "لا يُرسَل شيء إلى خارج النظام تلقائياً."),
      groups: [
        {
          id: "post",
          tone: "sen",
          nodes: [
            n("d_interrupt", icon("hand"), t("interrupt() · human approval", "interrupt() · موافقة بشرية"), t("Approve or reject resumes it", "القبول أو الرفض يستأنفه"), "sentinel_agent", "web/components/IncidentBoard.tsx", { graph: "approval" }),
            n("d_audit", logo("postgresql"), t("Audit log", "سجل التدقيق"), t("Append-only", "إضافة فقط"), "audit_log", `${SEN}/db.py`, { graph: "audit" }),
            n("d_board", logo("nextdotjs"), t("Incident board", "لوحة الحوادث"), t("Where the operator decides", "حيث يقرر المشغّل"), "sentinel_agent", "web/components/IncidentBoard.tsx", { graph: "approval" }),
            n("d_stix", STIX, t("STIX 2.1 export", "تصدير STIX 2.1"), t("A client pulls the file", "يسحب العميل الملف"), "stix", `${CORE}/tools/stix.py`, { graph: "stix" }),
          ],
        },
      ],
    },
  ],
  steps: [
    { node: "d_bus", caption: t("Every finished check arrives as an event on Redis Streams.", "يصل كل فحص منتهٍ حدثاً على Redis Streams.") },
    { node: "d_correlate", caption: t("Plain code groups checks that share a brand, a page fingerprint or a domain pattern.", "شيفرة عادية تجمع الفحوص التي تشترك في علامة أو بصمة صفحة أو نمط نطاق.") },
    { node: "d_rules", caption: t("Fixed rules open the incident and set its severity.", "قواعد ثابتة تفتح الحادثة وتحدد شدتها.") },
    { node: "d_enrich", caption: t("enrich: read-only tools gather related verdicts, domains and past incidents.", "enrich: أدوات للقراءة فقط تجمع الأحكام والنطاقات ذات الصلة والحوادث السابقة.") },
    { node: "d_compare", caption: t("compare: code checks shared infrastructure and whether this was seen before.", "compare: الشيفرة تفحص البنية المشتركة وهل تكرّر هذا من قبل.") },
    { node: "d_assess", caption: t("assess: a model explains the severity in words. It cannot change rules or scores.", "assess: نموذج يشرح الشدة بالكلمات، ولا يستطيع تغيير القواعد أو الدرجات.") },
    { node: "d_summarise", caption: t("summarise: a short bilingual summary; a claim without an evidence id is dropped.", "summarise: ملخص قصير بلغتين، ويُحذَف كل ادعاء بلا معرّف دليل.") },
    { node: "d_propose", caption: t("propose: the model suggests typed actions, and code validates each one.", "propose: يقترح النموذج إجراءات مكتوبة، وتتحقق الشيفرة من كل واحد منها.") },
    { node: "d_act", caption: t("act: reversible internal steps run; anything external becomes a draft.", "act: تُنفَّذ الخطوات الداخلية القابلة للتراجع، وكل ما هو خارجي يصير مسوّدة.") },
    { node: "d_interrupt", caption: t("interrupt() pauses the graph. Only an operator's approve or reject resumes it.", "interrupt() يوقف المخطط، ولا يستأنفه إلا قبول المشغّل أو رفضه.") },
    { node: "d_audit", caption: t("Every action and decision is written to the append-only audit log.", "يُكتَب كل إجراء وقرار في سجل تدقيق لا يقبل إلا الإضافة.") },
  ],
};

/* ── 4. DSPy: prompts tuned offline, frozen, loaded with a fallback ──────────────────────────────────────── */
export const DSPY_FLOW: FlowSpec = {
  id: "dspy",
  title: t("The DSPy pipeline", "مسار DSPy"),
  lead: t("Prompts are tuned offline against the production validators, frozen, and loaded with the hand-written prompt as the fallback.", "تُضبَط المطالبات خارج التشغيل بمقياس المدقّقات الإنتاجية نفسها، ثم تُجمَّد، وتُحمَّل مع بقاء المطالبة المكتوبة يدوياً بديلاً."),
  bands: [
    {
      id: "offline",
      icon: "refresh",
      title: t("Offline, before a release", "خارج التشغيل، قبل الإصدار"),
      sub: t("Nothing here runs in production.", "لا يعمل شيء من هذا في الإنتاج."),
      groups: [
        {
          id: "tune",
          tone: "plain",
          nodes: [
            n("y_cases", icon("list"), t("Training and validation cases", "حالات التدريب والتحقق"), t("The held-out test split is never read", "لا تُقرأ مجموعة الاختبار المحجوبة"), "dspy_compiled_prompts", "evals/dspy/fl_data.py"),
            n("y_sig", DSPY, same("dspy.Predict + Signature"), t("Typed inputs and outputs per role", "مدخلات ومخرجات مكتوبة لكل دور"), "dspy_compiled_prompts", "evals/dspy/roles.py", { graph: "dspy" }),
            n("y_opt", DSPY, same("BootstrapFewShot · MIPROv2"), t("Tune instructions and examples", "ضبط التعليمات والأمثلة"), "dspy_compiled_prompts", "evals/dspy/optimize.py", { graph: "dspy" }),
            n("y_metric", icon("scale"), t("Production validators", "المدقّقات الإنتاجية"), t("The metric is our own checks", "المقياس هو مدقّقاتنا نفسها"), "dspy_compiled_prompts", "evals/dspy/fl_metrics.py"),
            n("y_frozen", icon("keep"), t("Frozen prompt file", "ملف مطالبة مجمَّد"), t("JSON with a checksum", "JSON بمجموع اختباري"), "dspy_compiled_prompts", `${CORE}/prompts/compiled`),
          ],
        },
      ],
    },
    {
      id: "runtime",
      icon: "box",
      title: t("At run time", "أثناء التشغيل"),
      sub: t("A frozen file is read; DSPy itself is not imported.", "يُقرأ ملف مجمَّد، ولا تُستورَد مكتبة DSPy نفسها."),
      groups: [
        {
          id: "serve",
          tone: "plain",
          nodes: [
            n("y_loader", icon("box"), t("Prompt loader", "محمِّل المطالبات"), t("Falls back to the hand-written prompt", "يعود إلى المطالبة المكتوبة يدوياً"), "dspy_compiled_prompts", `${CORE}/prompts/__init__.py`, { graph: "dspy" }),
            n("y_router", icon("refresh"), t("Model router", "موجِّه النماذج"), t("One compiled prompt per route", "مطالبة مُصرَّفة لكل مسار"), "sovereign", `${CORE}/llm/router.py`, { graph: "router" }),
            n("y_claude", logo("claude"), same("Claude API"), t("Cloud route", "المسار السحابي"), "sovereign", `${CORE}/llm/providers.py`, { graph: "cloud", llm: true }),
            n("y_ollama", logo("ollama"), same("Ollama"), t("Local route", "المسار المحلي"), "sovereign", "infra/ollama", { graph: "local", llm: true }),
          ],
        },
      ],
    },
  ],
  steps: [
    { node: "y_cases", caption: t("Training cases tune, validation cases select. The held-out test split is never read.", "حالات التدريب للضبط وحالات التحقق للاختيار، ولا تُقرأ مجموعة الاختبار المحجوبة أبداً.") },
    { node: "y_sig", caption: t("A DSPy Signature fixes the typed inputs and outputs of one model role.", "توقيع DSPy يثبّت المدخلات والمخرجات المكتوبة لدور نموذج واحد.") },
    { node: "y_opt", caption: t("BootstrapFewShot and MIPROv2 tune the instructions and the few-shot examples.", "يضبط BootstrapFewShot وMIPROv2 التعليمات والأمثلة القليلة.") },
    { node: "y_metric", caption: t("Each candidate is scored by the production validators, on the production path.", "يُقيَّم كل مرشّح بالمدقّقات الإنتاجية، وعلى المسار الإنتاجي نفسه.") },
    { node: "y_frozen", caption: t("A candidate is kept only if it beats the hand-written prompt; then it is frozen with a checksum.", "لا يُعتمَد المرشّح إلا إذا تفوّق على المطالبة المكتوبة يدوياً، ثم يُجمَّد بمجموع اختباري.") },
    { node: "y_loader", caption: t("At run time the loader reads the frozen file. Missing or altered: the hand-written prompt is used.", "أثناء التشغيل يقرأ المحمِّل الملف المجمَّد، وإن فُقد أو عُدّل استُخدمت المطالبة المكتوبة يدوياً.") },
    { node: "y_router", caption: t("The router uses a compiled prompt only on the route it was compiled for.", "يستخدم الموجِّه المطالبة المُصرَّفة على المسار الذي صُرّفت له فقط.") },
  ],
};

/* ── 5. Model route: redaction, router, cloud or local, traces ───────────────────────────────────────────── */
export const ROUTE_FLOW: FlowSpec = {
  id: "route",
  title: t("Where a model call goes", "أين يذهب نداء النموذج"),
  lead: t("Every model call passes the same guard. An operator chooses cloud with a local fallback, or local only; sovereign mode locks it to local.", "يمرّ كل نداء لنموذج بالحارس نفسه. ويختار المشغّل المسار السحابي مع بديل محلي، أو المحلي فقط، والوضع السيادي يثبّته محلياً."),
  bands: [
    {
      id: "guard",
      icon: "keep",
      title: t("Before any model", "قبل أي نموذج"),
      sub: t("Models see structured evidence, never raw page text.", "ترى النماذج أدلة منظَّمة، لا نص الصفحة الخام."),
      groups: [
        {
          id: "prep",
          tone: "plain",
          nodes: [
            n("r_evidence", icon("list"), t("Structured evidence", "أدلة منظَّمة"), t("From the tiers and the tools", "من الطبقات والأدوات"), "investigator", `${CORE}/agent/investigator.py`, { graph: "t3" }),
            n("r_redact", icon("eye"), t("Redaction and spotlighting", "الحجب والتمييز"), t("Personal details hidden, text marked as data", "تُحجَب البيانات الشخصية ويُعلَّم النص بوصفه بيانات"), "injection_defence", `${CORE}/llm/spotlight.py`, { graph: "redact" }),
            n("r_router", icon("refresh"), t("Model router", "موجِّه النماذج"), t("One place for every call", "موضع واحد لكل النداءات"), "sovereign", `${CORE}/llm/router.py`, { graph: "router" }),
          ],
        },
      ],
    },
    {
      id: "models",
      icon: "spark",
      title: t("Cloud, or our own machine", "السحابة أو جهازنا نفسه"),
      sub: t("Sovereign mode sends every call to the local route.", "الوضع السيادي يرسل كل النداءات إلى المسار المحلي."),
      groups: [
        {
          id: "cloud",
          tone: "plain",
          title: t("Cloud route", "المسار السحابي"),
          nodes: [n("r_claude", logo("claude"), same("Claude API"), t("Only with a key, sovereign mode off", "بمفتاح فقط والوضع السيادي متوقف"), "sovereign", `${CORE}/llm/providers.py`, { graph: "cloud", llm: true })],
        },
        {
          id: "local",
          tone: "plain",
          title: t("Local route", "المسار المحلي"),
          nodes: [
            n("r_ollama", logo("ollama"), same("Ollama"), t("Serves the local models", "يشغّل النماذج المحلية"), "sovereign", "infra/ollama", { graph: "local", llm: true }),
            n("r_inkling", INKLING, same("Inkling"), t("Default local model", "النموذج المحلي الافتراضي"), "sovereign", "infra/ollama/Inkling-2-Mini.chat.Modelfile", { llm: true }),
            n("r_qwen", logo("qwen"), same("Qwen"), t("Optional local model", "نموذج محلي اختياري"), "sovereign", `${CORE}/llm/config.py`, { llm: true }),
          ],
        },
      ],
    },
    {
      id: "watch",
      icon: "eye",
      title: t("Every call is counted and traced", "كل نداء يُعَدّ ويُتتبَّع"),
      sub: t("On the internal observability network only.", "على شبكة المراقبة الداخلية فقط."),
      groups: [
        {
          id: "obs",
          tone: "plain",
          nodes: [
            n("r_otel", logo("opentelemetry"), same("OpenTelemetry"), t("Collects the spans", "يجمع الآثار"), "llm_tracing", "infra/otel"),
            n("r_phoenix", PHOENIX, same("Arize Phoenix"), t("Shows each model call", "يعرض كل نداء لنموذج"), "llm_tracing", `${CORE}/telemetry/tracing.py`, { graph: "phoenix" }),
            n("r_prom", logo("prometheus"), same("Prometheus"), t("Counts calls and fallbacks", "يعدّ النداءات والتحويلات"), "observability", "infra/prometheus", { graph: "prometheus" }),
            n("r_grafana", logo("grafana"), same("Grafana"), t("Dashboards", "لوحات المتابعة"), "observability", "infra/grafana/dashboards", { graph: "grafana" }),
          ],
        },
      ],
    },
  ],
  steps: [
    { node: "r_evidence", caption: t("A model step starts from structured evidence, not from raw page text.", "تبدأ خطوة النموذج من أدلة منظَّمة، لا من نص الصفحة الخام.") },
    { node: "r_redact", caption: t("Personal details are redacted, and untrusted text is delimited and marked as data.", "تُحجَب البيانات الشخصية، ويُحدَّد النص غير الموثوق ويُعلَّم بوصفه بيانات.") },
    { node: "r_router", caption: t("The router picks the route the operator chose and validates the reply against a schema.", "يختار الموجِّه المسار الذي حدده المشغّل، ويتحقق من الرد وفق مخطط.") },
    { node: "r_claude", caption: t("Cloud route: Claude, only with a key and with sovereign mode off.", "المسار السحابي: Claude، بمفتاح فقط ومع إيقاف الوضع السيادي.") },
    { node: "r_ollama", caption: t("On an error or a timeout, and always in sovereign mode, the call goes to the local route.", "عند الخطأ أو انتهاء المهلة، ودائماً في الوضع السيادي، يذهب النداء إلى المسار المحلي.") },
    { node: "r_inkling", caption: t("A local model answers on our own machine, so the text stays there.", "يجيب نموذج محلي على جهازنا نفسه، فيبقى النص هناك.") },
    { node: "r_otel", caption: t("OpenTelemetry collects a span for the call.", "يجمع OpenTelemetry أثراً لهذا النداء.") },
    { node: "r_phoenix", caption: t("Arize Phoenix shows what the model was asked and what it answered.", "يعرض Arize Phoenix ما سُئل عنه النموذج وما أجاب به.") },
  ],
};


/**
 * One fuller sentence for the nodes that have no entry in lib/arch-graph.ts (those open the full panel instead).
 * Keyed by node id; tests/unit/arch-flow.test.ts checks that every node has one or the other.
 */
const D_INKLING = t("The default local model (inkling-2-mini-chat), served by Ollama on our own machine. Sovereign mode sends every model call to the local route.", "النموذج المحلي الافتراضي (inkling-2-mini-chat)، يشغّله Ollama على جهازنا نفسه. والوضع السيادي يرسل كل نداءات النماذج إلى المسار المحلي.");
const D_QWEN = t("An optional local model (Qwen 3.8) that an operator can select for the local route. A Qwen embedding model also matches spoken questions to prepared answers.", "نموذج محلي اختياري (Qwen 3.8) يستطيع المشغّل اختياره للمسار المحلي. ويطابق نموذج تضمين من Qwen الأسئلة المنطوقة بالإجابات المُعَدّة.");
const D_OTEL = t("The OpenTelemetry collector receives a span for each model call and forwards it to Arize Phoenix on the internal observability network.", "يستقبل مجمِّع OpenTelemetry أثراً لكل نداء لنموذج ويمرّره إلى Arize Phoenix على شبكة المراقبة الداخلية.");
export const NODE_DESC: Record<string, L> = {
  v_polly: t("Arabic narration clips are generated in advance from our own script with the Amazon Polly voice Zayd. Polly is an offline preparation tool: it receives no user data, and the site plays local files.", "تُولَّد مقاطع الرواية العربية مسبقاً من نصّنا بصوت «زايد» من Amazon Polly. وهو أداة إعداد خارج التشغيل: لا تصله أي بيانات للمستخدمين، والموقع يشغّل ملفات محلية."),
  v_kokoro: t("English narration clips are generated in advance from our own script with the open Kokoro voice model. The site plays local files.", "تُولَّد مقاطع الرواية الإنجليزية مسبقاً من نصّنا بنموذج الصوت المفتوح Kokoro. والموقع يشغّل ملفات محلية."),
  v_earcons: t("Three short cue sounds, one per verdict level, so the result is recognisable before the words are spoken.", "ثلاث نغمات تنبيه قصيرة، واحدة لكل مستوى حكم، ليُعرَف الحكم قبل أن تُنطَق الكلمات."),
  p_pg: t("PostgreSQL stores verdicts, evidence, incidents, the append-only audit log and the saved state of the Sentinel's graph.", "يخزّن PostgreSQL الأحكام والأدلة والحوادث وسجل التدقيق الذي لا يقبل إلا الإضافة، والحالة المحفوظة لمخطط «درع»."),
  p_pgvector: t("The pgvector extension finds known scam messages that read like a new one. It returns ids and labels only, never the stored text.", "تعثر إضافة pgvector على رسائل احتيال معروفة تشبه الرسالة الجديدة. وتعيد المعرّفات والتصنيفات فقط، لا النص المخزَّن."),
  p_egress: t("The only way out of the isolated network. It resolves each address itself and refuses private and internal destinations.", "المنفذ الوحيد من الشبكة المعزولة. يحلّ كل عنوان بنفسه ويرفض الوجهات الخاصة والداخلية."),
  p_inkling: D_INKLING,
  r_inkling: D_INKLING,
  p_qwen: D_QWEN,
  r_qwen: D_QWEN,
  p_otel: D_OTEL,
  r_otel: D_OTEL,
  p_loki: t("Loki keeps the structured logs of every service, so an operator can follow one check by its identifier.", "يحفظ Loki السجلات المنظَّمة لكل الخدمات، فيستطيع المشغّل تتبّع فحص واحد بمعرّفه."),
  p_alert: t("Alertmanager routes the alerts raised by the Prometheus rules. Each alert has an entry in the runbook.", "يوجّه Alertmanager التنبيهات التي تطلقها قواعد Prometheus. ولكل تنبيه مدخل في دليل التشغيل."),
  p_caddy: t("Caddy is the single gateway in front of the web app and the API, and sets the security headers.", "Caddy هو البوابة الوحيدة أمام تطبيق الويب والواجهة البرمجية، ويضبط ترويسات الأمان."),
  p_tunnel: t("A Cloudflare quick tunnel gives the gateway a public address for the demo. It is started on demand and is off otherwise.", "نفق سريع من Cloudflare يمنح البوابة عنواناً عاماً للعرض. يُشغَّل عند الطلب ويبقى متوقفاً في غير ذلك."),
  p_docker: t("Every service runs in one Docker Compose stack, on separate networks for the edge, the app, the data, the sandbox and observability.", "تعمل كل الخدمات في حزمة Docker Compose واحدة، على شبكات منفصلة للواجهة والتطبيق والبيانات والبيئة المعزولة والمراقبة."),
  y_cases: t("Training cases are used to tune and validation cases to select. The frozen test split and the held-out sets are never read by the optimiser.", "تُستخدَم حالات التدريب للضبط وحالات التحقق للاختيار. أما مجموعة الاختبار المجمَّدة والمجموعات المحجوبة فلا يقرؤها المُحسِّن أبداً."),
  y_metric: t("The metric is the production validators themselves: the reply must parse into the schema, cite evidence ids that exist, and carry valid tool arguments.", "المقياس هو المدقّقات الإنتاجية نفسها: يجب أن يُحلَّل الرد إلى المخطط، وأن يستشهد بمعرّفات أدلة موجودة، وأن يحمل وسائط أدوات صحيحة."),
  y_frozen: t("An adopted prompt is stored as a frozen JSON file with a checksum, one per role and route. A missing or altered file falls back to the hand-written prompt.", "تُحفَظ المطالبة المعتمدة في ملف JSON مجمَّد بمجموع اختباري، واحد لكل دور ومسار. وإن فُقد الملف أو عُدّل عُدنا إلى المطالبة المكتوبة يدوياً."),
};

/** Badges for the lane diagram (components/arch/ArchDiagram.tsx), keyed by the node id in lib/arch-graph.ts. */
export const GRAPH_BADGE: Record<string, Badge> = {
  clients: logo("nextdotjs"), api: logo("fastapi"), voice_mic: icon("mic"), voice_stt: WHISPER, voice_intent: icon("list"),
  t0: logo("redis"), t1: logo("scikitlearn"), t2: PLAYWRIGHT, t3: icon("spark"), arbiter: icon("scale"), verdict: icon("no_warning_signs"),
  bus: logo("redis"), correlate: icon("url"), rules: icon("list"), enrich: logo("langgraph"), compare: logo("langgraph"), assess: logo("langgraph"),
  summarise: logo("langgraph"), propose: logo("langgraph"), act: logo("langgraph"), approval: icon("hand"), audit: logo("postgresql"),
  router: icon("refresh"), redact: icon("eye"), cloud: logo("claude"), local: logo("ollama"), dspy: DSPY,
  prometheus: logo("prometheus"), grafana: logo("grafana"), phoenix: PHOENIX,
  rest: logo("fastapi"), mcp: logo("modelcontextprotocol"), stix: STIX, webhooks: icon("url"),
  toolbox_inv: icon("list"), toolbox_sen: icon("list"),
  render_page: PLAYWRIGHT, search_similar_scripts: PGVECTOR, export_stix: STIX,
};

export const FLOWS: readonly FlowSpec[] = [MAIN_FLOW, BASEER_FLOW, DIR_FLOW, DSPY_FLOW, ROUTE_FLOW];

export const nodesOf = (spec: FlowSpec): FlowNode[] => spec.bands.flatMap((b) => b.groups.flatMap((g) => [...g.nodes]));

/** The text name of a node's badge: the tool it identifies, or null when the badge is one of our own icons. */
export function badgeTool(badge: Badge, titles: Record<string, { title: string }>): string | null {
  if ("logo" in badge) return titles[badge.logo]?.title ?? null;
  if ("mono" in badge) return badge.tool;
  return null;
}

/** Words of the player and the text alternative. */
export const FLOW_UI: Record<FlowLang, {
  play: string; pause: string; replay: string; prev: string; next: string; step: string; of: string; controls: string;
  idleStatic: string; alt: string; altSteps: string; altParts: string; live: string; progress: string; status: string; logos: string; model: string;
  panelWhat: string; panelTool: string; panelCode: string; codeLink: string; close: string; badgeNote: string; diagram: string; idle: string;
}> = {
  en: {
    play: "Play", pause: "Pause", replay: "Replay", prev: "Previous step", next: "Next step", step: "Step", of: "of", controls: "Animation controls",
    alt: "Text version of this diagram", altSteps: "The request path, step by step", altParts: "Every part shown", live: "Live", progress: "In progress", status: "Status",
    logos: "Logos belong to their owners; shown to identify the tools used.", model: "model step",
    panelWhat: "What it does", panelTool: "Tool", panelCode: "In the code", codeLink: "Open the source on GitHub", close: "Close", badgeNote: "text badge, no logo vendored", diagram: "Animated diagram", idle: "Press Play to follow one request through the system.", idleStatic: "Use Next step to read the path one step at a time.",
  },
  ar: {
    play: "تشغيل", pause: "إيقاف مؤقت", replay: "إعادة", prev: "الخطوة السابقة", next: "الخطوة التالية", step: "الخطوة", of: "من", controls: "أزرار التحكم في الحركة",
    alt: "النسخة النصية من هذا المخطط", altSteps: "مسار الطلب خطوة بخطوة", altParts: "كل الأجزاء المعروضة", live: "يعمل الآن", progress: "قيد الإنجاز", status: "الحالة",
    logos: "الشعارات ملك لأصحابها، وتُعرَض للتعريف بالأدوات المستخدمة فقط.", model: "خطوة نموذج",
    panelWhat: "ما يفعله", panelTool: "الأداة", panelCode: "في الشيفرة", codeLink: "افتح الشيفرة على GitHub", close: "إغلاق", badgeNote: "شارة نصية، دون شعار", diagram: "مخطط متحرك", idle: "اضغط «تشغيل» لتتابع طلباً واحداً عبر النظام.", idleStatic: "استخدم «الخطوة التالية» لتقرأ المسار خطوة بخطوة.",
  },
};
