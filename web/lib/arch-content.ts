/**
 * Copy for /architecture/agents. Every statement mirrors the code it names:
 * packages/falcon_core/agent/{investigator,extractor,responder}.py, tools/registry.py,
 * contracts/tools.schema.json, services/sentinel/src/falcon_sentinel/graph.py, ADR-001, ADR-002.
 * Plain text only; no numbers other than code-level budgets that appear as constants in the source.
 */
import type { Lang } from "./contracts";

export interface Layer {
  /** Capability flag whose status badge this layer carries. */
  cap?: "investigator" | "injection_defence";
  tag: string;
  title: string;
  body: string;
  kind?: "llm" | "code" | "gate";
}

export interface AgentBlock {
  name: string;
  pattern: string;
  patternNote: string;
  whyTitle: string;
  why: string[];
  flowTitle: string;
  layers: Layer[];
  guardTitle: string;
  guards: string[];
  rejectedTitle: string;
  rejected: { name: string; reason: string }[];
}

export interface ArchContent {
  title: string;
  lead: string;
  legend: { llm: string; code: string; gate: string };
  loopLabel: string;
  loopDone: string;
  loopBudget: string;
  toolsTitle: string;
  tools: string[];
  investigator: AgentBlock;
  sentinel: AgentBlock;
  back: string;
}

const TOOLS = ["rdap_lookup", "cert_lookup", "render_page", "compare_brand", "search_similar_scripts", "check_reputation", "expand_redirects"];

export const ARCH: Record<Lang, ArchContent> = {
  en: {
    title: "Technical architecture of the two agents",
    lead: "Each agent uses the smallest pattern that does its job. The Investigator (Baseer | بصير) is a bounded state machine because a check is a short, bounded task that must survive hostile input. The Sentinel is a LangGraph workflow because incident triage is long-running, must survive restarts, and must stop for a human before anything leaves the system. In both, code decides and the model only assists.",
    legend: { llm: "Model step", code: "Deterministic code", gate: "Human gate" },
    loopLabel: "Investigator · بصير loop",
    loopDone: "stop: hand evidence to the arbiter",
    loopBudget: "at most 6 tool calls",
    toolsTitle: "The typed tool registry",
    tools: TOOLS,
    back: "Back to How it works",
    investigator: {
      name: "Investigator · بصير (T3)",
      pattern: "Bounded plan → act → observe → decide state machine",
      patternNote: "ReAct-style tool use, but not a free-running ReAct agent.",
      whyTitle: "Why this pattern",
      why: [
        "Bounded cost: it runs only for the uncertain band, with a fixed ceiling on calls and time, so a check cannot run open-ended.",
        "Injection resistance: the model emits one typed JSON action per step, never free text that something acts on, and an attacker-controlled page cannot talk it into other tools or arguments.",
        "Reproducibility: the arbiter, not the model, sets the score, so results can be re-run and evaluated. The same loop works on cloud and local models because native tool calling is not required.",
      ],
      flowTitle: "Layer by layer",
      layers: [
        { tag: "T0 – T2", title: "Deterministic cascade", body: "Canonicalise the input, consult the cache and the verified-official registry, run URL, domain and reputation signals and the calibrated model, visit the page in the sandbox. Most checks finish here without any language model.", kind: "code" },
        { cap: "injection_defence", tag: "T2", title: "Quarantined extractor", body: "The only model that ever reads untrusted text. It has no tools, receives redacted and spotlighted input, and must return a strict schema; invalid output is repaired once, then dropped. Its output can only add evidence.", kind: "llm" },
        { cap: "investigator", tag: "T3 · in", title: "Structured evidence view", body: "The Investigator receives structured evidence records only, never raw page or message text. Targets are given as short references (u0, d1) that code resolves to the exact value.", kind: "code" },
        { cap: "investigator", tag: "PLAN", title: "Propose one action", body: "The model emits a single JSON action: a tool name, typed arguments and the evidence ids that justify it, or stop.", kind: "llm" },
        { cap: "investigator", tag: "ACT", title: "Validate, then run", body: "The action is validated against the tool registry: typed arguments, extra keys rejected, and a provenance rule that every URL or domain must come from the case itself. Only then does the tool run.", kind: "code" },
        { cap: "investigator", tag: "OBSERVE", title: "Record the observation", body: "A tool returns evidence records only, never raw HTML. A sanitised step is added to the investigation trail shown to the user.", kind: "code" },
        { cap: "investigator", tag: "DECIDE", title: "Loop or stop", body: "Stop when the model says stop, or when a budget is reached: 6 tool calls, 15 seconds or 8,000 output tokens. The stop reason is recorded.", kind: "code" },
        { tag: "ARBITER", title: "Deterministic arbiter sets the score", body: "New T3 evidence enters with weight 0 and the arbiter re-scores everything by fixed, evaluated rules. The Investigator has no way to set or change a score, so by design an injection can at most add evidence (evaluation status: see Results).", kind: "code" },
        { cap: "investigator", tag: "RESPONDER", title: "Explain with a verifier", body: "A model writes at most three bilingual reasons from structured evidence. A verifier rejects any reason that cites no valid evidence, contradicts the verdict or breaks product rules, and falls back to template reasons.", kind: "llm" },
      ],
      guardTitle: "Guardrails",
      guards: [
        "Dual-model separation: the model that reads untrusted text has no tools; the model that uses tools never reads untrusted text.",
        "No tool can submit a form or enter data into a page.",
        "Every step is traced with its tier, tool and evidence ids.",
      ],
      rejectedTitle: "Alternatives we rejected",
      rejected: [
        { name: "A single free-running agent", reason: "slow, costly, nondeterministic and injectable: a page could talk it out of the evidence." },
        { name: "A multi-agent chat framework", reason: "adds latency and unpredictability for no benefit inside the tight time budget of a check." },
        { name: "A pure classifier", reason: "gives no grounded explanation and is weak on new attack styles and brands." },
      ],
    },
    sentinel: {
      name: "Sentinel · درع",
      pattern: "LangGraph StateGraph workflow with a human interrupt",
      patternNote: "A fixed graph, not an open-ended agent loop. Deterministic rules decide what an incident is.",
      whyTitle: "Why this pattern",
      why: [
        "Long-running: triage spans several steps and external lookups, so progress must be persisted between them.",
        "Resumable after a restart: a Postgres checkpointer keyed by the incident resumes at the last completed node after a crash or redeploy.",
        "Auditable: the graph is explicit, every action is written to an append-only log with its evidence ids, and the interrupt makes the approval point a structural fact, not a prompt instruction.",
      ],
      flowTitle: "Layer by layer",
      layers: [
        { tag: "LISTEN", title: "Event stream", body: "Consumes verdict events from a Redis stream with a consumer group. Delivery is at least once and handlers are idempotent on the event id; after three failed attempts an event goes to a dead-letter stream.", kind: "code" },
        { tag: "CORRELATE", title: "Plain-Python correlation", body: "Buckets events by page fingerprint distance, brand, domain pattern, network, registrar, certificate issuer, script cluster and time window.", kind: "code" },
        { tag: "TRIGGER", title: "Rules decide the incident", body: "Unit-tested rules (campaign, kit reuse, report burst, reputation flip, quality) open an incident. Counts are reproducible with the model stubbed out.", kind: "code" },
        { tag: "enrich", title: "Gather context", body: "Read-only tools fetch related verdicts, related domains, past incidents and feed status.", kind: "code" },
        { tag: "compare", title: "Compare", body: "Deterministic: what do the indicators share, and has this been seen before?", kind: "code" },
        { tag: "assess", title: "Assess severity", body: "A model writes the reason for the severity within its budget; past the budget a template is used.", kind: "llm" },
        { tag: "summarise", title: "Summarise", body: "A bilingual incident summary from structured evidence only.", kind: "llm" },
        { tag: "propose", title: "Propose actions", body: "The model proposes typed actions; code then validates them against the same tool registry and enforces caps on blocks and on total actions per incident.", kind: "llm" },
        { tag: "act", title: "Act, then wait for a person", body: "Internal, reversible actions run (time-limited block, alert, board update, STIX export, re-check). External actions are built as drafts and the graph calls interrupt(): it resumes only when an operator approves or rejects. Nothing is sent outside automatically.", kind: "gate" },
      ],
      guardTitle: "Guardrails",
      guards: [
        "Postgres checkpointer, thread id = incident id, so a restart resumes at the last completed node.",
        "Per-node retry policy: up to 3 attempts on transient errors.",
        "Budget per incident: 8 steps, 20,000 tokens, 60 seconds of active time; beyond that templates replace the model.",
        "The agent cannot edit rules, thresholds or scoring, and sees structured evidence only.",
        "Every block expires on a timer and can be reverted; every action is in the append-only audit log.",
      ],
      rejectedTitle: "Alternatives we rejected",
      rejected: [
        { name: "A free-running single agent", reason: "cannot guarantee a stop before external actions, and is hard to resume or audit." },
        { name: "A multi-agent chat framework", reason: "nondeterministic hand-offs and no durable state for a process that runs around the clock." },
        { name: "A pure classifier or rules alone", reason: "decides well but cannot write the summary, the severity reason or the takedown and report drafts." },
      ],
    },
  },
  ar: {
    title: "البنية التقنية للوكيلين",
    lead: "يستخدم كل وكيل أبسط نمط يؤدي مهمته. «بصير»، المحقّق، آلة حالات محدودة، لأن الفحص مهمة قصيرة محدودة يجب أن تصمد أمام مدخلات معادية. و«درع»، الحارس، مسار عمل بإطار LangGraph، لأن فرز الحوادث طويل الأمد ويجب أن يتحمل إعادة التشغيل وأن يتوقف عند إنسان قبل أن يخرج أي شيء من النظام. وفي الحالتين، الشيفرة هي التي تقرر، والنموذج يساعد فقط.",
    legend: { llm: "خطوة نموذج", code: "شيفرة حتمية", gate: "بوابة بشرية" },
    loopLabel: "حلقة بصير، المحقّق",
    loopDone: "إيقاف: تسليم الأدلة إلى المحكّم",
    loopBudget: "حدّ أقصى 6 استدعاءات أدوات",
    toolsTitle: "سجل الأدوات المصنّفة",
    tools: TOOLS,
    back: "العودة إلى آلية العمل",
    investigator: {
      name: "بصير، المحقّق (T3)",
      pattern: "آلة حالات محدودة: خطّط ← نفّذ ← لاحظ ← قرّر",
      patternNote: "استخدام أدوات على نمط ReAct، لكنه ليس وكيل ReAct حرّ التشغيل.",
      whyTitle: "لماذا هذا النمط",
      why: [
        "كلفة محدودة: لا يعمل إلا في النطاق الغامض، وبسقف ثابت للاستدعاءات والوقت، فلا يبقى الفحص مفتوحاً بلا نهاية.",
        "مقاومة الحقن: يُخرج النموذج إجراءً واحداً بصيغة JSON مصنّفة في كل خطوة، لا نصاً حراً يُنفَّذ، ولا تستطيع صفحة يتحكم بها مهاجم أن تدفعه إلى أدوات أو معطيات أخرى.",
        "إمكانية الإعادة: المحكّم، لا النموذج، يحدد الدرجة، فيمكن إعادة التشغيل والتقييم. وتعمل الحلقة نفسها مع النماذج السحابية والمحلية لأن الاستدعاء الأصلي للأدوات غير مطلوب.",
      ],
      flowTitle: "طبقة بعد طبقة",
      layers: [
        { tag: "T0 – T2", title: "الشلال الحتمي", body: "توحيد صيغة المدخل، وفحص الذاكرة المؤقتة وسجل المواقع الرسمية الموثّقة، وإشارات العنوان والنطاق والسمعة والنموذج المعايَر، وزيارة الصفحة في البيئة المعزولة. تنتهي معظم الفحوص هنا دون أي نموذج لغوي.", kind: "code" },
        { cap: "injection_defence", tag: "T2", title: "المستخرِج المعزول", body: "النموذج الوحيد الذي يقرأ نصاً غير موثوق. لا أدوات لديه، ويستلم مدخلاً محجوب الحقول الحساسة ومعلَّماً، ويجب أن يعيد مخططاً صارماً. المخرجات غير الصالحة تُصلَح مرة واحدة ثم تُهمَل. ولا يمكن لمخرجاته إلا إضافة أدلة.", kind: "llm" },
        { cap: "investigator", tag: "T3 · دخل", title: "عرض الأدلة المهيكل", body: "يستلم بصير سجلات أدلة مهيكلة فقط، ولا يرى نص الصفحة أو الرسالة الخام. تُعطى الأهداف كمراجع قصيرة (u0، d1) تحوّلها الشيفرة إلى القيمة الدقيقة.", kind: "code" },
        { cap: "investigator", tag: "PLAN", title: "اقتراح إجراء واحد", body: "يُخرج النموذج إجراءً واحداً بصيغة JSON: اسم الأداة ومعطيات مصنّفة ومعرّفات الأدلة التي تبرره، أو إيقاف.", kind: "llm" },
        { cap: "investigator", tag: "ACT", title: "تحقّق ثم نفّذ", body: "يُتحقَّق من الإجراء بمقابلة سجل الأدوات: معطيات مصنّفة، ومفاتيح زائدة مرفوضة، وقاعدة منشأ تشترط أن يأتي كل رابط أو نطاق من الحالة نفسها. وعندها فقط تُشغَّل الأداة.", kind: "code" },
        { cap: "investigator", tag: "OBSERVE", title: "تسجيل الملاحظة", body: "تعيد الأداة سجلات أدلة فقط، ولا تعيد HTML خاماً. وتُضاف خطوة منقّحة إلى مسار التحقيق المعروض للمستخدم.", kind: "code" },
        { cap: "investigator", tag: "DECIDE", title: "كرّر أو توقّف", body: "يتوقف عندما يقرر النموذج الإيقاف أو عند بلوغ ميزانية: 6 استدعاءات أدوات أو 15 ثانية أو 8000 رمز ناتج. ويُسجَّل سبب التوقف.", kind: "code" },
        { tag: "ARBITER", title: "المحكّم الحتمي يحدد الدرجة", body: "تدخل أدلة T3 الجديدة بوزن 0 ويعيد المحكّم تقدير كل شيء بقواعد ثابتة مقيَّمة. لا يستطيع بصير تحديد الدرجة أو تغييرها، فأقصى ما يفعله الحقن بحسب التصميم هو إضافة دليل (حالة التقييم: انظر صفحة النتائج).", kind: "code" },
        { cap: "investigator", tag: "RESPONDER", title: "الشرح مع مدقّق", body: "يكتب نموذج ما لا يزيد على ثلاثة أسباب ثنائية اللغة من أدلة مهيكلة. ويرفض المدقّق أي سبب لا يستشهد بدليل صالح أو يناقض الحكم أو يخالف قواعد المنتج، ويعود إلى أسباب القوالب.", kind: "llm" },
      ],
      guardTitle: "ضوابط الحماية",
      guards: [
        "فصل النموذجين: الذي يقرأ نصاً غير موثوق لا أدوات لديه، والذي يستخدم الأدوات لا يقرأ نصاً غير موثوق.",
        "لا تستطيع أي أداة إرسال نموذج أو إدخال بيانات في صفحة.",
        "كل خطوة تُسجَّل بطبقتها وأداتها ومعرّفات أدلتها.",
      ],
      rejectedTitle: "بدائل استبعدناها",
      rejected: [
        { name: "وكيل واحد حرّ التشغيل", reason: "بطيء ومكلف وغير حتمي وقابل للحقن: قد تقنعه صفحة بتجاهل الأدلة." },
        { name: "إطار محادثة متعدد الوكلاء", reason: "يضيف زمن استجابة وعدم قابلية للتنبؤ دون فائدة ضمن الميزانية الزمنية الضيقة للفحص." },
        { name: "مصنّف فقط", reason: "لا يقدّم تفسيراً مستنداً إلى الأدلة، وضعيف أمام أساليب الهجوم والعلامات الجديدة." },
      ],
    },
    sentinel: {
      name: "درع، الحارس",
      pattern: "مسار عمل LangGraph StateGraph مع مقاطعة بشرية",
      patternNote: "رسم ثابت وليس حلقة وكيل مفتوحة. القواعد الحتمية تحدد ما هو الحادث.",
      whyTitle: "لماذا هذا النمط",
      why: [
        "طويل الأمد: يمتد الفرز عبر خطوات وعمليات بحث خارجية عدة، فيجب حفظ التقدم بينها.",
        "يتحمل إعادة التشغيل: نقطة حفظ في Postgres مرتبطة بالحادث تستأنف من آخر عقدة مكتملة بعد عطل أو إعادة نشر.",
        "قابل للتدقيق: الرسم صريح، وكل إجراء يُكتب في سجل للإضافة فقط مع معرّفات أدلته، والمقاطعة تجعل نقطة الموافقة حقيقة بنيوية لا تعليمة في نص.",
      ],
      flowTitle: "طبقة بعد طبقة",
      layers: [
        { tag: "LISTEN", title: "تدفق الأحداث", body: "يستهلك أحداث الأحكام من تدفق Redis بمجموعة مستهلكين. التسليم مرة واحدة على الأقل، والمعالجات لا تتأثر بالتكرار على معرّف الحدث، وبعد ثلاث محاولات فاشلة ينتقل الحدث إلى تدفق الرسائل المرفوضة.", kind: "code" },
        { tag: "CORRELATE", title: "ربط بلغة Python عادية", body: "يجمّع الأحداث بحسب بُعد بصمة الصفحة والعلامة ونمط النطاق والشبكة والمسجِّل وجهة إصدار الشهادة وعنقود السكربت والنافذة الزمنية.", kind: "code" },
        { tag: "TRIGGER", title: "القواعد تحدد الحادث", body: "قواعد مختبرة آلياً (حملة، إعادة استخدام عُدّة، موجة بلاغات، تغيّر سمعة، جودة) تفتح الحادث. وتتكرر الأعداد نفسها عند استبدال النموذج بنسخة وهمية.", kind: "code" },
        { tag: "enrich", title: "جمع السياق", body: "أدوات قراءة فقط تجلب الأحكام والنطاقات المرتبطة والحوادث السابقة وحالة المصادر.", kind: "code" },
        { tag: "compare", title: "المقارنة", body: "حتمية: ما الذي تشترك فيه المؤشرات، وهل سبق أن رأينا هذا؟", kind: "code" },
        { tag: "assess", title: "تقدير الشدة", body: "يكتب نموذج سبب الشدة ضمن ميزانيته، وبعد تجاوزها يُستخدم قالب.", kind: "llm" },
        { tag: "summarise", title: "التلخيص", body: "ملخص ثنائي اللغة للحادث من أدلة مهيكلة فقط.", kind: "llm" },
        { tag: "propose", title: "اقتراح الإجراءات", body: "يقترح النموذج إجراءات مصنّفة، ثم تتحقق الشيفرة منها بمقابلة سجل الأدوات نفسه وتفرض سقفاً لعدد الحظر ولمجموع الإجراءات في الحادث.", kind: "llm" },
        { tag: "act", title: "نفّذ ثم انتظر إنساناً", body: "تُنفَّذ الإجراءات الداخلية القابلة للتراجع (حظر مؤقت، تنبيه، تحديث اللوحة، تصدير STIX، إعادة فحص). أما الإجراءات الخارجية فتُبنى كمسودات ويستدعي الرسم interrupt(): لا يستأنف إلا عندما يوافق مشغّل أو يرفض. ولا يُرسل شيء إلى الخارج تلقائياً.", kind: "gate" },
      ],
      guardTitle: "ضوابط الحماية",
      guards: [
        "نقطة حفظ في Postgres بمعرّف المسار = معرّف الحادث، فيستأنف بعد إعادة التشغيل من آخر عقدة مكتملة.",
        "سياسة إعادة محاولة لكل عقدة: حتى 3 محاولات عند الأخطاء العابرة.",
        "ميزانية الحادث: 8 خطوات و20000 رمز و60 ثانية من العمل الفعلي، وبعدها تحلّ القوالب محل النموذج.",
        "لا يستطيع الوكيل تعديل القواعد أو العتبات أو التقدير، ولا يرى سوى أدلة مهيكلة.",
        "كل حظر ينتهي بمؤقت ويمكن التراجع عنه، وكل إجراء مسجّل في سجل التدقيق للإضافة فقط.",
      ],
      rejectedTitle: "بدائل استبعدناها",
      rejected: [
        { name: "وكيل واحد حرّ التشغيل", reason: "لا يضمن التوقف قبل الإجراءات الخارجية، ويصعب استئنافه وتدقيقه." },
        { name: "إطار محادثة متعدد الوكلاء", reason: "تسليمات غير حتمية ولا حالة دائمة لعملية تعمل على مدار الساعة." },
        { name: "مصنّف أو قواعد فقط", reason: "يقرر جيداً لكنه لا يكتب الملخص ولا سبب الشدة ولا مسودات الإزالة والبلاغ." },
      ],
    },
  },
};
