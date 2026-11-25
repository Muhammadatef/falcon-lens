/**
 * Copy and diagram data for /docs/building-agents: how the two agents were built, and why LangGraph and DSPy.
 * Every statement restates the repository (services/sentinel/src/falcon_sentinel/graph.py, evals/dspy/, DECISIONS.md).
 * Plain text only. Counts are written in words; the only digits are identifiers (T0, R1, v1). Measured numbers are
 * never typed here: the DSPy table is rendered from lib/dspy-results.ts (the published eval artifacts).
 */
import type { Lang } from "./contracts";

export type NodeKind = "code" | "llm" | "gate" | "store";

export interface PipeNode {
  /** Code identifier shown as-is (left-to-right). */
  id: string;
  name: string;
  note: string;
  kind: NodeKind;
  /** Capability flag whose badge this node carries. */
  cap?: string;
}
export interface PipeLane {
  title: string;
  nodes: PipeNode[];
}
export interface Item {
  title: string;
  body: string;
  /** Repository path, shown in monospace. */
  path?: string;
}

export interface BuildingAgentsCopy {
  lead: string;
  legend: Record<NodeKind, string>;
  process: { title: string; intro: string; items: Item[] };
  sentinel: { title: string; intro: string; label: string; lanes: PipeLane[]; notes: Item[] };
  dspy: { title: string; intro: string; label: string; lanes: PipeLane[]; notes: Item[] };
  whyLg: { title: string; intro: string; items: Item[]; coreTitle: string; core: string; invTitle: string; inv: string };
  whyDspy: { title: string; intro: string; items: Item[]; resultTitle: string; result: string; none: string; tableCaption: string; cols: [string, string, string, string, string]; yes: string; no: string; synthetic: string; gateTitle: string; gate: string };
  notUsed: { title: string; intro: string; items: Item[] };
  back: string;
}

const en: BuildingAgentsCopy = {
  lead: "How we built the two agents, the two tools we chose to run them (LangGraph for the Sentinel, DSPy for every prompt), and what each choice did and did not deliver.",
  legend: { code: "Plain code", llm: "Model step", gate: "Human or rule gate", store: "Stored state" },
  process: {
    title: "How we built our two agents",
    intro: "The same six habits shaped both agents. Each one is a rule in the repository, not a slogan.",
    items: [
      { title: "Contracts first", body: "One typed tool registry is shared by the Investigator, the Sentinel and the MCP server. A model can only ask for a tool by emitting a typed action that the registry validates; there are no free-form calls. Schemas for verdicts, evidence, events and incidents were written before the services that use them.", path: "contracts/tools.schema.json" },
      { title: "The arbiter sets every score", body: "Signals return evidence, never a verdict. A deterministic arbiter turns evidence into the score and the band. A model never sets or changes a score, and never touches a rule or a threshold.", path: "packages/falcon_core/src/falcon_core/scoring/arbiter.py" },
      { title: "Evals before claims", body: "Every number the site shows is read from a generated evaluation artifact. Data is split into train, validation and a frozen test set, and a change is merged only when it holds up on held-out cases.", path: "evals/" },
      { title: "Red-team as a gate", body: "A suite of prompt-injection, obfuscation and SSRF cases runs against the shipped code. Untrusted text is delimited and datamarked before any model sees it, and the agents see structured evidence only.", path: "evals/redteam/" },
      { title: "A human before anything external", body: "Reversible internal steps run at once. Anything that would leave the system is prepared as a draft and waits for a person to approve it. The Sentinel does this with a built-in pause in its graph; this build prepares drafts only.", path: "services/sentinel/src/falcon_sentinel/graph.py" },
      { title: "A sovereign route", body: "A single switch sends every model call to the local model. The same roles, the same validators and the same prompt structure run on both routes, so nothing depends on a cloud provider being reachable.", path: "packages/falcon_core/src/falcon_core/llm/" },
    ],
  },
  sentinel: {
    title: "The Sentinel architecture (Dir' | درع) on LangGraph",
    intro: "Events and rules decide what an incident is. The graph only enriches and explains it, and it stops for a person before any external action.",
    label: "Sentinel architecture: events, deterministic correlation and rules, then a LangGraph state graph with a human approval pause, and the platform services beneath it.",
    lanes: [
      { title: "Listen and decide (plain code)", nodes: [
        { id: "fl:events", name: "Redis Streams", note: "At-least-once events; handlers are idempotent.", kind: "store" },
        { id: "correlate", name: "Deterministic correlation", note: "Groups checks by kit fingerprint, brand, network and time.", kind: "code" },
        { id: "rules.yaml", name: "Rule triggers", note: "Campaign, kit reuse, report burst, reputation flip, quality.", kind: "code" },
      ] },
      { title: "Triage graph (one thread per incident)", nodes: [
        { id: "enrich", name: "Enrich", note: "Read-only lookups.", kind: "code" },
        { id: "compare", name: "Compare", note: "Shared infrastructure and past incidents.", kind: "code" },
        { id: "assess", name: "Assess", note: "Why this severity.", kind: "llm" },
        { id: "summarise", name: "Summarise", note: "Bilingual summary.", kind: "llm" },
        { id: "propose", name: "Propose", note: "Typed actions from a fixed menu.", kind: "llm" },
        { id: "act", name: "Act", note: "Internal steps now; external steps as drafts.", kind: "code" },
      ] },
      { title: "Human gate", nodes: [
        { id: "interrupt()", name: "Pause for approval", note: "The graph stops until an operator approves or rejects.", kind: "gate" },
        { id: "external", name: "External action", note: "Only after approval. Drafts only in this build.", kind: "code" },
      ] },
      { title: "Underneath every node", nodes: [
        { id: "Postgres checkpointer", name: "Saved state", note: "Thread is the incident; resumes after a restart.", kind: "store" },
        { id: "RetryPolicy", name: "Per-node retries", note: "Transient errors only.", kind: "code" },
        { id: "budget", name: "Budget", note: "Eight steps, twenty thousand tokens and one hundred twenty seconds per incident.", kind: "gate" },
        { id: "audit_log", name: "Audit log", note: "Append-only; cites evidence ids.", kind: "store", cap: "audit_log" },
        { id: "Phoenix", name: "Traces", note: "Model calls traced through OpenTelemetry.", kind: "store", cap: "llm_tracing" },
      ] },
    ],
    notes: [
      { title: "The model is a worker, not the boss", body: "Past the budget the model is skipped and a template is used. A verifier keeps a claim only if it cites an evidence id that exists, and the proposed actions are validated by the same registry the Investigator uses." },
      { title: "Built to survive a restart", body: "State is kept in Postgres under the incident id. After a restart the service continues every incident that was paused or interrupted." },
    ],
  },
  dspy: {
    title: "The DSPy architecture in our pipeline",
    intro: "DSPy works offline. It proposes better prompts; the production services never import it and only load a frozen file, and only after a gate says the gain is real.",
    label: "DSPy pipeline: a typed Signature per role, an offline optimiser per route, selection on validation, the adoption gate, then frozen compiled prompts or the hand-written prompt.",
    lanes: [
      { title: "Define (typed contracts)", nodes: [
        { id: "extractor", name: "Extractor", note: "Reads a message into typed fields.", kind: "llm" },
        { id: "investigator", name: "Investigator", note: "Chooses the next typed tool call.", kind: "llm" },
        { id: "sentinel_assess", name: "Sentinel assess", note: "Severity reason.", kind: "llm" },
        { id: "sentinel_summarise", name: "Sentinel summarise", note: "Bilingual summary.", kind: "llm" },
        { id: "sentinel_propose", name: "Sentinel propose", note: "Typed actions.", kind: "llm" },
      ] },
      { title: "Optimise offline, per route", nodes: [
        { id: "train split", name: "Optimiser", note: "BootstrapFewShot and MIPROv2 try instructions and examples on the train split.", kind: "code" },
        { id: "validation", name: "Select", note: "The best candidate is chosen on validation, scored by the production validators.", kind: "code" },
        { id: "route", name: "Cloud model or local model", note: "Each route gets its own result; one never loads the other's.", kind: "code" },
      ] },
      { title: "Adoption gate", nodes: [
        { id: "paired interval", name: "Gain outside noise?", note: "Adopt only if the paired interval of after minus before excludes zero.", kind: "gate" },
        { id: "compiled/", name: "Frozen compiled prompt", note: "Stored as JSON with a checksum; loaded without importing DSPy.", kind: "store", cap: "dspy_compiled_prompts" },
        { id: "hand-written", name: "Hand-written prompt stays", note: "The fallback when the gain is within noise, or a file is missing or altered.", kind: "store" },
      ] },
      { title: "Shipped", nodes: [
        { id: "role", name: "Shipped role", note: "Runs with whichever prompt passed the gate.", kind: "llm" },
        { id: "verifier", name: "Verifier", note: "Checks every reply: schema, evidence ids, tool arguments.", kind: "gate" },
      ] },
    ],
    notes: [
      { title: "What the metric is", body: "The metric is the production validators themselves, not a separate score. A prompt that looks better but breaks the schema or cites a missing evidence id scores badly.", path: "evals/dspy/roles.py" },
      { title: "What it never reads", body: "The frozen test split is never read by the optimiser. Untrusted text keeps its delimiters and datamarks inside the optimisation requests.", path: "evals/dspy/optimize.py" },
    ],
  },
  whyLg: {
    title: "Why LangGraph",
    intro: "We chose LangGraph for the Sentinel because its job is long-running, must be explained afterwards, and must stop for a person.",
    items: [
      { title: "An explicit, auditable map", body: "The graph is a visible list of steps and edges, and each step has a defined set of tools it may call. A reviewer can read the map instead of inferring behaviour from a prompt." },
      { title: "It survives restarts and resumes", body: "A Postgres checkpointer saves state after each node, keyed by the incident. A crash or a deployment does not lose an investigation; it continues from the last saved step." },
      { title: "A built-in pause before anything external", body: "The interrupt call stops the graph inside the act node and resumes only through an approve or reject decision. The stop is part of the structure, so no instruction in a message can skip it. This is the property police workflows need most." },
      { title: "Retries, budgets and traces per node", body: "Each node has its own retry policy, and each incident has a budget of steps, tokens and time. Per-node metrics and traces show where time and tokens go." },
      { title: "Built to run all day", body: "The Sentinel is a backend agent that consumes events around the clock, not a request handler, and a graph with saved state suits that shape." },
      { title: "It works with local models", body: "The graph calls our own model router, so sovereign mode applies to every node and nothing needs a cloud provider." },
    ],
    coreTitle: "Why only langchain-core",
    core: "LangGraph needs the model and tool interfaces from langchain-core, and that is all we use. We do not use chains, memory, retrievers or prebuilt agents: each one hides control flow that we want to be written down, tested and reviewed.",
    invTitle: "Why the Investigator is not LangGraph",
    inv: "The Investigator judges one input in seconds. It is a bounded state machine of plan, act, observe and decide, with at most six typed tool calls. That keeps a check fast, resists injection because the model emits one typed action and never free text that something acts on, and keeps results reproducible because the arbiter sets the score. A graph with saved state would add weight it does not need.",
  },
  whyDspy: {
    title: "Why DSPy",
    intro: "The owner chose DSPy to optimise the prompt of every AI function and agent systematically, instead of tuning prompts by hand and hoping.",
    items: [
      { title: "Prompts are measured, not guessed", body: "Hand-tuned prompts improve by feel and regress silently. DSPy optimisers search instructions and examples against labelled cases, and the score that decides is computed by our own validators." },
      { title: "Typed Signatures are contracts", body: "Each role declares typed inputs and outputs. That is the contract we already validate: schema, evidence ids that exist, tool arguments that pass the registry." },
      { title: "The same pipeline on both routes", body: "The optimiser runs with the cloud model and with the local model (Inkling or Qwen through Ollama). The sovereign route gets prompts optimised for the model it really runs, not borrowed from the cloud." },
      { title: "Reproducible and versioned", body: "A compiled prompt is a frozen file with a checksum, stored per role and per route. It can be reviewed in a pull request, rolled back, and re-run from the recorded seed and data." },
      { title: "A gate against self-deception", body: "A candidate is adopted only when its gain is outside noise on held-out validation cases. This is what keeps an optimiser from shipping a lucky result." },
    ],
    resultTitle: "The honest result",
    result: "The optimiser ran for every role below, on synthetic data. No optimised prompt was adopted, because adoption requires a gain outside noise, and none showed one. The shipped prompts are the hand-written ones. This is the adoption gate working as designed, and we report it as it is.",
    none: "No published optimiser result is on this build.",
    tableCaption: "Optimiser results per role (synthetic data), from the published evaluation files",
    cols: ["Role", "Before", "After", "Paired 95% interval", "Gain outside noise"],
    yes: "yes",
    no: "no",
    synthetic: "Synthetic data. Source: the published files in evals/results/published/dspy. Small sets give wide intervals, and local-model runs are not fully repeatable.",
    gateTitle: "What would change this",
    gate: "A larger labelled set, or a role where the hand-written prompt is weaker. The pipeline, the loader and the gate are already in place, so an adopted prompt would ship the day it passes.",
  },
  notUsed: {
    title: "What we deliberately did not use",
    intro: "Each of these would have been quicker to start with. Each one trades away something a security tool cannot give up.",
    items: [
      { title: "Prebuilt agents and autonomous tool loops", body: "A model that decides its own next step, with no fixed bound, is hard to audit and easy to steer with injected text. The Investigator is capped at six typed calls, and the Sentinel's steps are fixed in the graph." },
      { title: "A model that sets the score", body: "Scores come from the arbiter, from evidence and weights that can be inspected and re-run. A model may explain a verdict; it never produces one." },
      { title: "Chains, memory and retrievers", body: "They add hidden state and hidden prompts. We keep state in the graph and in Postgres, where it can be read and audited." },
      { title: "DSPy at run time", body: "Importing an optimiser into production would widen the attack surface and the start-up cost. Production only loads a frozen file." },
      { title: "Automatic external actions", body: "Nothing is sent outside the system without a person. This build prepares drafts only." },
    ],
  },
  back: "Back to the agent patterns",
};

const ar: BuildingAgentsCopy = {
  lead: "كيف بنينا الوكيلين، ولماذا اخترنا أداتين لتشغيلهما: LangGraph لـ«درع» وDSPy لتحسين كل مطالبة، وماذا حقّقت كل أداة وما لم تحقّقه.",
  legend: { code: "شيفرة عادية", llm: "خطوة نموذج", gate: "بوابة بشرية أو قاعدة", store: "حالة محفوظة" },
  process: {
    title: "كيف بنينا وكيلينا",
    intro: "حكمت ست عادات بناء الوكيلين معاً. وكل واحدة منها قاعدة مكتوبة في المستودع، لا شعار.",
    items: [
      { title: "العقود أولاً", body: "سجلّ أدوات مكتوب الأنواع واحد يشترك فيه «بصير» و«درع» وخادم MCP. لا يطلب النموذج أداة إلا بإخراج إجراء مكتوب يتحقق منه السجلّ، ولا استدعاءات حرة. وكُتبت مخططات الأحكام والأدلة والأحداث والحوادث قبل الخدمات التي تستعملها.", path: "contracts/tools.schema.json" },
      { title: "المحكّم هو من يحدّد كل درجة", body: "تُعيد الإشارات أدلة ولا تُعيد حكماً. ويحوّل محكّم حتمي الأدلة إلى الدرجة والنطاق. ولا يضع النموذج درجة ولا يغيّرها، ولا يمسّ قاعدة ولا عتبة.", path: "packages/falcon_core/src/falcon_core/scoring/arbiter.py" },
      { title: "التقييم قبل الادعاء", body: "كل رقم يعرضه الموقع يُقرأ من ملف تقييم مُولَّد. وتُقسَّم البيانات إلى تدريب وتحقق واختبار مجمَّد، ولا يُدمج تغيير إلا إذا صمد في حالات محجوزة.", path: "evals/" },
      { title: "الفريق الأحمر بوابةً للدمج", body: "تُشغَّل مجموعة حالات حقن تعليمات وتمويه وSSRF على الشيفرة المُسلَّمة. ويُحاط النص غير الموثوق بفواصل وعلامات قبل أن يراه أي نموذج، ولا يرى الوكيلان إلا أدلة منظَّمة.", path: "evals/redteam/" },
      { title: "إنسان قبل أي إجراء خارجي", body: "تُنفَّذ الخطوات الداخلية القابلة للتراجع فوراً. أما ما يخرج من المنظومة فيُجهَّز مسودة وينتظر موافقة شخص. ويفعل «درع» ذلك بإيقاف مدمج في رسمه البياني، وهذا الإصدار يُجهّز المسودات فقط.", path: "services/sentinel/src/falcon_sentinel/graph.py" },
      { title: "مسار سيادي", body: "مفتاح واحد يوجّه كل استدعاءات النماذج إلى النموذج المحلي. وتعمل الأدوار والمدقّقات وبنية المطالبات نفسها على المسارين، فلا يعتمد شيء على توفّر مزوّد سحابي.", path: "packages/falcon_core/src/falcon_core/llm/" },
    ],
  },
  sentinel: {
    title: "البنية الأولى: «درع» على LangGraph",
    intro: "الأحداث والقواعد هي التي تقرر ما هي الحادثة. ولا يفعل الرسم البياني سوى الإثراء والشرح، ويتوقف عند شخص قبل أي إجراء خارجي.",
    label: "بنية درع: الأحداث والربط الحتمي والقواعد، ثم رسم LangGraph بتوقف للموافقة البشرية، وتحته خدمات المنصة.",
    lanes: [
      { title: "الاستماع والقرار (شيفرة عادية)", nodes: [
        { id: "fl:events", name: "تدفقات Redis", note: "أحداث بتسليم مرة على الأقل، والمعالجات تتحمّل التكرار.", kind: "store" },
        { id: "correlate", name: "ربط حتمي", note: "يجمع الفحوص بحسب بصمة الأداة والعلامة والشبكة والزمن.", kind: "code" },
        { id: "rules.yaml", name: "مشغّلات القواعد", note: "حملة، وإعادة استخدام أداة، وموجة بلاغات، وانقلاب سمعة، وجودة.", kind: "code" },
      ] },
      { title: "رسم الفرز (مسار لكل حادثة)", nodes: [
        { id: "enrich", name: "إثراء", note: "بحث للقراءة فقط.", kind: "code" },
        { id: "compare", name: "مقارنة", note: "بنية مشتركة وحوادث سابقة.", kind: "code" },
        { id: "assess", name: "تقييم", note: "سبب هذه الخطورة.", kind: "llm" },
        { id: "summarise", name: "تلخيص", note: "ملخص ثنائي اللغة.", kind: "llm" },
        { id: "propose", name: "اقتراح", note: "إجراءات مكتوبة من قائمة ثابتة.", kind: "llm" },
        { id: "act", name: "تنفيذ", note: "الداخلي فوراً، والخارجي مسودات.", kind: "code" },
      ] },
      { title: "البوابة البشرية", nodes: [
        { id: "interrupt()", name: "توقف للموافقة", note: "يقف الرسم حتى يوافق المشغّل أو يرفض.", kind: "gate" },
        { id: "external", name: "إجراء خارجي", note: "بعد الموافقة فقط. مسودات فقط في هذا الإصدار.", kind: "code" },
      ] },
      { title: "تحت كل عقدة", nodes: [
        { id: "Postgres checkpointer", name: "حالة محفوظة", note: "المسار هو الحادثة، ويُستأنف بعد إعادة التشغيل.", kind: "store" },
        { id: "RetryPolicy", name: "إعادة محاولة لكل عقدة", note: "للأخطاء العابرة فقط.", kind: "code" },
        { id: "budget", name: "ميزانية", note: "ثماني خطوات، وعشرون ألف رمز، ومئة وعشرون ثانية لكل حادثة.", kind: "gate" },
        { id: "audit_log", name: "سجل التدقيق", note: "للإضافة فقط، ويذكر معرّفات الأدلة.", kind: "store", cap: "audit_log" },
        { id: "Phoenix", name: "التتبّع", note: "تُتتبَّع استدعاءات النموذج عبر OpenTelemetry.", kind: "store", cap: "llm_tracing" },
      ] },
    ],
    notes: [
      { title: "النموذج عامل لا مدير", body: "إذا تجاوزنا الميزانية يُتخطّى النموذج ويُستعمل قالب. ولا يُبقي المدقّق ادعاءً إلا إذا ذكر معرّف دليل موجوداً، وتتحقق من الإجراءات المقترحة السجلّ نفسه الذي يستعمله «بصير»." },
      { title: "مصمَّم ليصمد عند إعادة التشغيل", body: "تُحفظ الحالة في Postgres تحت معرّف الحادثة. وبعد إعادة التشغيل تواصل الخدمة كل حادثة كانت متوقفة أو مقطوعة." },
    ],
  },
  dspy: {
    title: "البنية الثانية: DSPy في مسارنا",
    intro: "يعمل DSPy خارج التشغيل. يقترح مطالبات أفضل، ولا تستورده الخدمات الإنتاجية بل تحمّل ملفاً مجمَّداً، وبعد أن تقرّ البوابة أن المكسب حقيقي.",
    label: "مسار DSPy: توقيع مكتوب لكل دور، ومُحسِّن خارج التشغيل لكل مسار، واختيار على التحقق، وبوابة الاعتماد، ثم مطالبات مُصرَّفة مجمَّدة أو المطالبة المكتوبة يدوياً.",
    lanes: [
      { title: "التعريف (عقود مكتوبة)", nodes: [
        { id: "extractor", name: "المستخلِص", note: "يقرأ الرسالة إلى حقول مكتوبة.", kind: "llm" },
        { id: "investigator", name: "المحقّق", note: "يختار استدعاء الأداة التالي.", kind: "llm" },
        { id: "sentinel_assess", name: "تقييم درع", note: "سبب الخطورة.", kind: "llm" },
        { id: "sentinel_summarise", name: "تلخيص درع", note: "ملخص ثنائي اللغة.", kind: "llm" },
        { id: "sentinel_propose", name: "اقتراح درع", note: "إجراءات مكتوبة.", kind: "llm" },
      ] },
      { title: "التحسين خارج التشغيل لكل مسار", nodes: [
        { id: "train split", name: "المُحسِّن", note: "يجرّب BootstrapFewShot وMIPROv2 تعليمات وأمثلة على قسم التدريب.", kind: "code" },
        { id: "validation", name: "الاختيار", note: "يُختار أفضل مرشّح على التحقق بمدقّقات الإنتاج نفسها.", kind: "code" },
        { id: "route", name: "نموذج سحابي أو محلي", note: "لكل مسار نتيجته، ولا يحمّل أحدهما نتيجة الآخر.", kind: "code" },
      ] },
      { title: "بوابة الاعتماد", nodes: [
        { id: "paired interval", name: "مكسب خارج الضجيج؟", note: "لا يُعتمد إلا إذا استبعد المجال المزدوج للفرق (بعد ناقص قبل) الصفر.", kind: "gate" },
        { id: "compiled/", name: "مطالبة مُصرَّفة مجمَّدة", note: "ملف JSON بمجموع اختباري، يُحمَّل دون استيراد DSPy.", kind: "store", cap: "dspy_compiled_prompts" },
        { id: "hand-written", name: "تبقى المطالبة اليدوية", note: "الاحتياط عند بقاء المكسب ضمن الضجيج أو فقد الملف أو تعديله.", kind: "store" },
      ] },
      { title: "التسليم", nodes: [
        { id: "role", name: "الدور المُسلَّم", note: "يعمل بالمطالبة التي اجتازت البوابة.", kind: "llm" },
        { id: "verifier", name: "المدقّق", note: "يفحص كل ردّ: المخطط ومعرّفات الأدلة ووسائط الأدوات.", kind: "gate" },
      ] },
    ],
    notes: [
      { title: "ما المقياس", body: "المقياس هو مدقّقات الإنتاج نفسها لا درجة منفصلة. فالمطالبة التي تبدو أفضل لكنها تكسر المخطط أو تذكر معرّف دليل غير موجود تنال درجة سيئة.", path: "evals/dspy/roles.py" },
      { title: "ما لا يقرؤه أبداً", body: "لا يقرأ المُحسِّن قسم الاختبار المجمَّد أبداً. ويحتفظ النص غير الموثوق بفواصله وعلاماته داخل طلبات التحسين.", path: "evals/dspy/optimize.py" },
    ],
  },
  whyLg: {
    title: "لماذا LangGraph",
    intro: "اخترنا LangGraph لـ«درع» لأن عمله طويل المدى، ويجب شرحه لاحقاً، ويجب أن يتوقف عند شخص.",
    items: [
      { title: "خريطة صريحة قابلة للتدقيق", body: "الرسم قائمة مرئية بالخطوات والحواف، ولكل خطوة مجموعة أدوات محددة يجوز لها استدعاؤها. يقرأ المراجع الخريطة بدل أن يستنتج السلوك من مطالبة." },
      { title: "يصمد عند إعادة التشغيل ويستأنف", body: "يحفظ مُدقِّق حالة Postgres الحالة بعد كل عقدة، بمفتاح الحادثة. فلا يضيع تحقيق بسبب انقطاع أو نشر جديد، بل يستمر من آخر خطوة محفوظة." },
      { title: "توقف مدمج قبل أي إجراء خارجي", body: "يوقف استدعاء interrupt الرسم داخل عقدة التنفيذ، ولا يستأنف إلا بقرار موافقة أو رفض. والتوقف جزء من البنية، فلا تستطيع تعليمة داخل رسالة أن تتجاوزه. وهذه أهم خاصية لسير عمل الشرطة." },
      { title: "إعادة محاولة وميزانية وتتبّع لكل عقدة", body: "لكل عقدة سياسة إعادة محاولة، ولكل حادثة ميزانية من الخطوات والرموز والزمن. وتُظهر المقاييس والتتبّع لكل عقدة أين يذهب الوقت والرموز." },
      { title: "مصمَّم للعمل على مدار الساعة", body: "«درع» وكيل خلفي يستهلك الأحداث دون توقف، لا معالج طلبات، والرسم ذو الحالة المحفوظة يناسب هذا الشكل." },
      { title: "يعمل مع النماذج المحلية", body: "يستدعي الرسم موجّه النماذج لدينا، فيسري المسار السيادي على كل عقدة ولا يحتاج شيء إلى مزوّد سحابي." },
    ],
    coreTitle: "لماذا langchain-core فقط",
    core: "يحتاج LangGraph إلى واجهات النموذج والأداة من langchain-core، وهذا كل ما نستعمله. لا نستعمل السلاسل ولا الذاكرة ولا المُسترجِعات ولا الوكلاء الجاهزين، فكل منها يخفي مسار تحكم نريده مكتوباً ومختبَراً ومراجَعاً.",
    invTitle: "لماذا «بصير» ليس على LangGraph",
    inv: "يحكم «بصير» على مُدخل واحد في ثوانٍ. وهو آلة حالات محدودة: خطّط ونفّذ وراقب وقرّر، بما لا يزيد على ست استدعاءات أدوات مكتوبة. هذا يُبقي الفحص سريعاً، ويقاوم الحقن لأن النموذج يُخرج إجراءً واحداً مكتوباً ولا يُخرج نصاً حراً يتصرف به شيء، ويُبقي النتائج قابلة للإعادة لأن المحكّم يحدّد الدرجة. ورسم بحالة محفوظة سيضيف ثقلاً لا حاجة إليه.",
  },
  whyDspy: {
    title: "لماذا DSPy",
    intro: "اختار المالك DSPy لتحسين مطالبة كل وظيفة ذكاء اصطناعي وكل وكيل تحسيناً منهجياً، بدل ضبط المطالبات يدوياً ثم الأمل.",
    items: [
      { title: "المطالبات تُقاس ولا تُخمَّن", body: "المطالبات المضبوطة يدوياً تتحسن بالإحساس وتتراجع بصمت. أما مُحسِّنات DSPy فتبحث في التعليمات والأمثلة على حالات موسومة، والدرجة الحاسمة تحسبها مدقّقاتنا نحن." },
      { title: "التواقيع المكتوبة عقود", body: "يعلن كل دور مدخلاته ومخرجاته بأنواعها. وهذا العقد الذي نتحقق منه أصلاً: المخطط، ومعرّفات أدلة موجودة، ووسائط أدوات تجتاز السجلّ." },
      { title: "المسار نفسه على الطريقين", body: "يعمل المُحسِّن بالنموذج السحابي وبالنموذج المحلي (Inkling أو Qwen عبر Ollama). فينال المسار السيادي مطالبات محسَّنة للنموذج الذي يعمل عليه فعلاً، لا مستعارة من السحابة." },
      { title: "قابل للإعادة ومُرقَّم الإصدار", body: "المطالبة المُصرَّفة ملف مجمَّد بمجموع اختباري، لكل دور ولكل مسار. يمكن مراجعتها في طلب دمج، والتراجع عنها، وإعادة تشغيلها من البذرة والبيانات المسجّلة." },
      { title: "بوابة ضد خداع النفس", body: "لا يُعتمد مرشّح إلا إذا كان مكسبه خارج الضجيج في حالات تحقق محجوزة. وهذا ما يمنع المُحسِّن من تسليم نتيجة محظوظة." },
    ],
    resultTitle: "النتيجة بصدق",
    result: "شُغِّل المُحسِّن لكل دور في الجدول أدناه على بيانات اصطناعية. ولم تُعتمد أي مطالبة محسَّنة، لأن الاعتماد يشترط مكسباً خارج الضجيج ولم يظهر مكسب كهذا. والمطالبات المُسلَّمة هي المكتوبة يدوياً. هذه بوابة الاعتماد تعمل كما صُمِّمت، ونعرض النتيجة كما هي.",
    none: "لا توجد نتيجة منشورة للمُحسِّن في هذا الإصدار.",
    tableCaption: "نتائج المُحسِّن لكل دور (بيانات اصطناعية)، من ملفات التقييم المنشورة",
    cols: ["الدور", "قبل", "بعد", "المجال المزدوج 95٪", "مكسب خارج الضجيج"],
    yes: "نعم",
    no: "لا",
    synthetic: "بيانات اصطناعية. المصدر: الملفات المنشورة في evals/results/published/dspy. المجموعات الصغيرة تعطي مجالات واسعة، ولا تتكرر تشغيلات النموذج المحلي تماماً.",
    gateTitle: "ما الذي يغيّر هذا",
    gate: "مجموعة موسومة أكبر، أو دور تكون مطالبته اليدوية أضعف. فالمسار والمحمِّل والبوابة جاهزة، وأي مطالبة معتمدة ستُسلَّم في اليوم الذي تجتاز فيه البوابة.",
  },
  notUsed: {
    title: "ما تركناه عمداً",
    intro: "كان كل ما يلي أسرع في البداية. لكن كلاً منه يتنازل عن شيء لا تتنازل عنه أداة أمنية.",
    items: [
      { title: "الوكلاء الجاهزون وحلقات الأدوات المستقلة", body: "نموذج يقرر خطوته التالية بلا حدّ ثابت يصعب تدقيقه ويسهل توجيهه بنص محقون. «بصير» محدود بست استدعاءات مكتوبة، وخطوات «درع» ثابتة في الرسم." },
      { title: "نموذج يضع الدرجة", body: "تأتي الدرجات من المحكّم، من أدلة وأوزان يمكن فحصها وإعادة تشغيلها. قد يشرح النموذج حكماً، لكنه لا يصدره." },
      { title: "السلاسل والذاكرة والمُسترجِعات", body: "تضيف حالة مخفية ومطالبات مخفية. ونحن نحفظ الحالة في الرسم وفي Postgres حيث تُقرأ وتُدقَّق." },
      { title: "DSPy وقت التشغيل", body: "استيراد مُحسِّن في الإنتاج يوسّع سطح الهجوم وكلفة البدء. والإنتاج لا يحمّل إلا ملفاً مجمَّداً." },
      { title: "إجراءات خارجية تلقائية", body: "لا يخرج شيء من المنظومة دون شخص. وهذا الإصدار يُجهّز المسودات فقط." },
    ],
  },
  back: "العودة إلى أنماط الوكلاء",
};

export const BUILDING_AGENTS: Record<Lang, BuildingAgentsCopy> = { en, ar };
