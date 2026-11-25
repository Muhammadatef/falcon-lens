/**
 * Copy for the technical Docs area (/docs/*). Each page restates a repository document and adds no
 * claim of its own. Sources: docs/ARCHITECTURE.md, ADR-001, ADR-002, docs/SCORING.md,
 * docs/THREAT_MODEL.md, docs/EVALS.md, docs/INTEGRATION.md, docs/PRIVACY.md, docs/DESIGN.md section 9.
 * Plain text only (rendered as React text nodes). Numbers are written in words on purpose: a vitest
 * case fails if a digit appears here other than protocol versions and identifiers (tests/unit/docs-content.test.ts).
 * Measured numbers come only from the published artifact (lib/docs-data.ts, lib/results.ts).
 * The agent-pattern page (/docs/agents) renders lib/arch-content.ts.
 */
import type { Lang } from "./contracts";

export const DOC_SLUGS = ["architecture", "agents", "building-agents", "cascade", "arbiter", "security", "evals", "integration", "privacy"] as const;
export type DocSlug = (typeof DOC_SLUGS)[number];
export const isDocSlug = (s: string): s is DocSlug => (DOC_SLUGS as readonly string[]).includes(s);

export interface DocCard {
  tag: string;
  title: string;
  body: string;
  /** Capability flag whose badge this card carries. */
  cap?: string;
}

export interface DocSection {
  id: string;
  title: string;
  body?: string[];
  list?: string[];
  cards?: DocCard[];
  table?: { cols: string[]; rows: string[][]; rowCaps?: (string | null)[] };
  /** Marks where the artifact-driven block (thresholds / provenance) is inserted. */
  data?: "thresholds" | "provenance";
  cap?: string;
}

export interface DocPage {
  lead: string;
  /** Repository documents this page restates. */
  sources: string[];
  sections: DocSection[];
  figure?: { src: string; alt: string; width: number; height: number };
  callout?: string;
}

type Pages = Record<Exclude<DocSlug, "agents" | "building-agents">, DocPage>;

const en: Pages = {
  architecture: {
    lead: "Falcon Lens runs as separate services on isolated networks. This page covers the services, the path of one check, the model router, the data stores and the sandbox.",
    sources: ["docs/ARCHITECTURE.md"],
    figure: { src: "/images/architecture.svg", alt: "Falcon Lens architecture in three stacked layers. Top: the voice assistant layer, from the browser microphone through local speech to text, the wake phrase, the intent step and pre-generated narration clips. Middle: the two AI agents, Baseer the Investigator with tiers T0 to T3 and a deterministic arbiter, and Dir' the Sentinel with rules, a LangGraph triage and human approval. Bottom: the platform layer with the API, the event bus, the database, the isolated sandbox, the integrations that are ready to connect and not connected, observability and the public pages. A numbered path shows one request travelling through the layers, and each box carries the logo or the name of the tool it runs on.", width: 1200, height: 1084 },
    sections: [
      { id: "services", title: "Services", list: [
        "gateway: TLS, the content security policy, and routing of the web app, the API and MCP.",
        "api (FastAPI): validation, rate limits, keys, server-sent events.",
        "worker: the cascade, signals and the arbiter.",
        "sandbox: a separate Playwright browser service that returns features only.",
        "egress proxy: the only way out to the internet for the worker and the sandbox.",
        "mcp: a Model Context Protocol server that calls the REST API.",
        "sentinel: the event consumer, correlation, rules and the LangGraph agent.",
        "Postgres (with pgvector) and Redis hold data, caches and streams.",
      ] },
      { id: "flow", title: "The path of one link check", list: [
        "The API validates the request, rate-limits it, assigns a verdict id, queues a job on a Redis stream and answers with an accepted response and the event-stream address. A second request for the same canonical link attaches to the job already running.",
        "The worker runs the first three tiers and the fourth only when needed. After each tier it publishes a partial verdict, which the API relays as a server-sent event.",
        "The arbiter produces the final verdict. It is stored, and a verdict event goes to the event stream.",
        "The Sentinel consumes the event, correlates it and applies its rules. If an incident results, the triage graph runs and the incident reaches the incident board.",
        "A synchronous mode waits a short, bounded time and returns the best verdict so far, for simple clients and the MCP server.",
      ] },
      { id: "kinds", title: "Messages, emails and images", list: [
        "Message: normalised (Arabic and Arabizi), rule features, an embedding and a nearest-neighbour search over known scam scripts, then the quarantined extractor. Every link found goes through the link pipeline as a child check.",
        "Email: parsed with the standard library under a size cap, with no remote fetch. It checks authentication results, header mismatches, link text against target, QR codes in images, and attachment type and hash only. The body goes through the message pipeline.",
        "Image: a magic-byte check, QR decoding, then text extraction by the quarantined vision extractor. Extracted links and text go through the matching pipelines.",
      ] },
      { id: "router", title: "Model router", list: [
        "Roles: extractor, investigator, responder, vision, sentinel and judge. Each role maps to a cloud model and a local model.",
        "In sovereign mode, or when no cloud key is set, every role goes to the local model. On a cloud error or timeout the call falls back to the local model and a counter records it.",
        "Before any cloud call the input is redacted and spotlighted: untrusted text sits between random-nonce markers and each line is datamarked.",
        "Output is schema-validated with one repair retry, then falls back to templates.",
      ] },
      { id: "stores", title: "Data stores", list: [
        "Postgres: verdicts, evidence, known scam scripts, brands, incidents and their actions, the append-only audit log, hashed API keys, reports, feedback, the blocklist and the Sentinel checkpoints.",
        "Redis: the verdict cache (lifetime depends on the verdict), signal caches, the local feed mirror, rate limits, single-flight locks and the streams.",
      ] },
      { id: "sandbox", title: "Sandbox", list: [
        "Every visit gets a fresh browser context with downloads blocked, a total timeout, a redirect cap and a response-size cap. The page is loaded twice, once with a mobile Arabic profile and once as desktop English, to detect cloaking.",
        "It returns features only: form fields and their action origins, script post targets, hot-linked asset origins, title, a bounded amount of visible text, favicon and screenshot hashes, a DOM fingerprint and the redirect chain. Screenshots stay local and are served only to authenticated keys.",
        "Its networks are internal: from the sandbox container only the egress proxy and the worker health port accept connections. It is not on the observability network, and a shared bearer token guards its API.",
        "The egress proxy blocks private, loopback, link-local and metadata ranges and internal service names, and allows only the standard web ports.",
      ] },
    ],
  },

  cascade: {
    lead: "A check passes through up to four tiers, fastest first, and stops as soon as the evidence is decisive. Most checks never reach a language model.",
    sources: ["docs/adr/ADR-001-cascade-arbiter.md", "docs/SCORING.md"],
    sections: [
      { id: "tiers", title: "The four tiers", cards: [
        { tag: "T0", title: "Known indicators", body: "Canonicalise the input, then consult the verdict cache, the verified-official registry and the local mirror of reported-scam feeds. Budget: about fifty milliseconds." },
        { tag: "T1", title: "The address itself", body: "Deterministic link, domain and reputation signals run in parallel, together with a calibrated gradient-boosted model. Budget: about one second." },
        { tag: "T2", title: "Looking at the page", body: "The sandbox opens the page once, passively. Page and visual features, the reference-based brand check (hard rule H1) and the quarantined extractor add evidence. Budget: about six seconds." },
        { tag: "T3", title: "AI second look", body: "A bounded investigator takes a few typed tool calls, only for cases still uncertain after the first three tiers. Budget: about fifteen seconds.", cap: "investigator" },
      ] },
      { id: "exits", title: "Early exit", body: ["The cascade exits early so that work and cost stay bounded."], list: [
        "T1 exits when the classifier probability is below the fitted low bound or above the fitted high bound and there is no brand conflict.",
        "T2 exits when a hard rule fired or the probability is clearly outside the uncertain band. Otherwise the check escalates to T3.",
        "The fitted bounds are listed below, read from the published evaluation file.",
      ], data: "thresholds" },
      { id: "progressive", title: "Progressive verdict", list: [
        "After each tier the worker publishes a partial verdict with the same verdict id. The page shows the steps as they finish.",
        "While a verdict is not final the page may show a provisional suspicious or dangerous marker, and never a provisional no-warning-signs result.",
        "The final flag marks the arbiter's verdict. A final verdict is terminal: later events for the same id are ignored.",
      ] },
      { id: "separation", title: "Who sees what", list: [
        "Only the quarantined extractor reads untrusted text. It has no tools and must return a strict schema.",
        "The investigator and the responder see structured evidence only.",
        "No language model sets or changes a score. Evidence added by T3 enters with zero weight and the arbiter re-scores everything.",
      ] },
    ],
  },

  arbiter: {
    lead: "The arbiter is the only component that sets the risk score, the calibrated probability and the verdict. The per-signal weights are draft values documented there and are not repeated here.",
    sources: ["docs/SCORING.md"],
    sections: [
      { id: "pipeline", title: "Pipeline", list: [
        "Hard rules are evaluated first. A rule that fires sets a floor on the verdict, or, for trust rules, a cap.",
        "A gradient-boosted classifier gives a probability, calibrated on the validation split.",
        "Evidence adjusts the log-odds: each piece carries a fixed weight scaled by its confidence, and the sum is clipped to a bounded range.",
        "The risk score is the probability on a hundred-point scale, after a final calibrator fitted on validation.",
        "Bands: dangerous above the high threshold, suspicious between the two thresholds, no warning signs below the low one.",
      ], data: "thresholds" },
      { id: "rules", title: "Hard rules", table: {
        cols: ["Rule", "Condition", "Effect"],
        rows: [
          ["H1 brand mismatch", "A brand is claimed from deterministic signals (page title or text, favicon, hot-linked assets; never from a language model), the page asks for credentials or payment, and the registrable domain is not one the brand verified.", "Dangerous, with a very high probability floor."],
          ["H2 known bad", "A fresh feed hit on the exact link or host.", "Dangerous."],
          ["H3 verified official", "The registrable domain is on a brand's verified list, with no open-redirect abuse and no feed hit.", "Capped at no warning signs; never dangerous."],
          ["H4 exfiltration to a bot", "A form or script posts credentials to a messaging-bot API or a webhook relay.", "Dangerous."],
          ["H5 message with a dangerous link", "A message or email contains a link judged dangerous or suspicious.", "At least as severe as the worst child link; cites its evidence."],
          ["H6 one-time-code or remote-access request", "A message asks for a one-time code or a remote-access app and impersonates an authority or bank.", "At least suspicious."],
        ],
      } },
      { id: "precedence", title: "Precedence and caps", list: [
        "A degraded check beats H3: an official link whose check failed shows suspicious.",
        "H3 beats H1, H4 and H6 on verified-official domains. The overridden rules are recorded.",
        "The fitted classifier alone never produces dangerous: it needs page or domain risk evidence beside it. Every model-driven warning cites a classifier evidence item.",
      ] },
      { id: "degraded", title: "Degradation", list: [
        "A failed critical signal marks the verdict degraded and lists the reason. Enrichment signals from third parties stay informational and never degrade it.",
        "A degraded verdict is never shown as no warning signs: the page shows suspicious with the line that not every check completed.",
        "If the page could not be opened because of a failure only the browser-to-site leg can produce, the verdict can still be no warning signs, but only when page-independent trust evidence exists. Otherwise it is a degraded suspicious.",
      ] },
      { id: "explain", title: "Explanations", body: ["The responder picks at most three reasons, ordered by weight. Each must cite existing evidence ids. A verifier rejects anything else and falls back to the bilingual templates. User-facing reasons for model-driven warnings are evidence-grounded templates."] },
    ],
  },

  security: {
    lead: "This page summarises the threat model and the content security policy. Its status is a design statement. The measured resistance to prompt injection is listed as not yet measured on the Results page.",
    sources: ["docs/THREAT_MODEL.md", "docs/DESIGN.md"],
    sections: [
      { id: "boundaries", title: "Trust boundaries", list: [
        "Internet to gateway: anonymous public.",
        "Gateway to API and MCP: scoped integration keys and an operator key.",
        "Worker and sandbox to the internet: attacker-controlled content.",
        "Untrusted content to a language model: prompt injection.",
        "Stored attacker strings to the web boards: cross-site scripting.",
        "Containers to the host and the local model runtime.",
      ] },
      { id: "stride", title: "Threats and mitigations", table: {
        cols: ["Threat", "Mitigation"],
        rows: [
          ["Forged keys or webhooks", "Scoped keys stored only as argon2id hashes; webhooks signed with HMAC-SHA256 over a timestamp, with a replay window."],
          ["An injected page lowers its own score", "The deterministic arbiter sets scores; model output cannot touch them; the two kinds of model never share roles."],
          ["Repudiation", "An append-only audit log, with update and delete revoked for the application role, records the key and the evidence ids."],
          ["Server-side request forgery", "Own DNS resolution, blocked private and metadata ranges, the connection pinned to the checked address, every redirect re-checked, an egress proxy as a second layer and an isolated sandbox network."],
          ["Personal data leaks to a cloud model or logs", "Redaction before cloud calls and before logging; message bodies not stored; sovereign mode."],
          ["The checker used as an anonymous fetcher", "Raw content is never returned; screenshots only for authenticated keys; per-address limits."],
          ["Denial of service", "Size limits on every input, decompression caps, per-key and per-address limits, single-flight, sandbox pool limits and timeouts."],
          ["Browser exploit escapes the sandbox", "Non-root, read-only root file system, all capabilities dropped, no new privileges, the default seccomp profile and an isolated network."],
          ["Stored cross-site scripting on the boards", "React escaping only, no raw-HTML injection, a strict nonce-based content security policy, and links displayed defanged and never clickable."],
          ["Supply chain", "Locked dependency hashes, dependency and image scanners, secret scanning and a software bill of materials."],
        ],
      } },
      { id: "injection", title: "Prompt-injection defence", cap: "injection_defence", list: [
        "Untrusted text reaches only the quarantined extractor. It has no tools and returns a strict schema.",
        "Spotlighting: random-nonce delimiters plus line datamarking, and a system prompt that says the content is data.",
        "A detector adds risk evidence for instruction-like text. The text is never obeyed.",
        "Tool arguments pass a provenance check: every link or domain must come from the case itself.",
        "A tool-call, time and output budget bounds each investigator run.",
      ] },
      { id: "csp", title: "Content security policy of this site", list: [
        "Every page is served with a fresh nonce. Scripts need the nonce; there is no inline-script or eval allowance in production.",
        "Styles need the nonce too, so no inline style attribute is emitted in server HTML.",
        "Images, fonts, connections, workers and manifests come from the site's own origin only. Fonts are self-hosted. Objects, base-tag changes and framing are denied.",
        "Suspicious addresses are shown defanged, as plain text, and never as links.",
        "A browser test feeds payloads of script, image, SVG and attribute markup into every attacker-influenced string and fails on any CSP violation, dialog or script error.",
      ] },
      { id: "extension", title: "Browser extension", body: ["The extension is built for Manifest V3 with the smallest permission set that works: the active tab, storage and request rules, and host permission only for the API origin. It loads no remote code and sends only the link."] },
      { id: "residual", title: "Residual risks, stated plainly", list: [
        "Docker Desktop on macOS gives virtual-machine isolation, but there is no gVisor layer.",
        "Phishing pages may cloak against data-centre addresses, so the sandbox can see benign content. The dual-profile load and the snapshot replay used in evaluations reduce this only in part.",
      ] },
    ],
  },

  evals: {
    lead: "How the evaluation is built and gated. Every measured number on the site comes from the published evaluation file, described below, and is shown on the Results page.",
    sources: ["docs/EVALS.md"],
    sections: [
      { id: "data", title: "Datasets", body: ["Live links, snapshots and logos stay in a private, git-ignored folder. The repository holds manifests with hashes and defanged links only."], list: [
        "Phishing links from the OpenPhish community feed, with the first-seen time and a sandbox snapshot taken at collection.",
        "Legitimate links, including hard negatives: verified government and bank pages, popular sites, real login and payment pages, new legitimate domains and shortened legitimate links.",
        "Zero-day links: phishing that was on no enabled blocklist at collection, plus the invented Falcon Demo Bank fixtures.",
        "Messages in Gulf Arabic, Modern Standard Arabic, English and Arabizi, with tagged synthetic examples; fictional emails; and local injection fixtures.",
        "Real and synthetic data are reported separately, and so are the cloud and sovereign routes.",
      ] },
      { id: "splits", title: "Splits", list: [
        "A temporal cut: every test example was first seen after every training example.",
        "Grouping by registrable domain, so no domain appears in two splits.",
        "The test split is frozen and its hash is locked. All tuning happens on validation.",
      ] },
      { id: "metrics", title: "Metrics", list: [
        "Bootstrap confidence intervals for precision, recall, F1, false-positive rate and PR-AUC; a reliability curve and calibration error.",
        "False dangerous verdicts on verified-official sites; zero-day recall against a blocklist-only baseline; ablation by signal family.",
        "Latency per tier, cost per check and the share of checks that reach a language model.",
        "Faithfulness of reasons, injection attack success rate, verdict flip rate over repeated runs, and Arabic clarity judged by a model other than the generator.",
        "Sentinel: a labelled replay stream with planted campaigns, measuring incident precision and recall, time to incident, duplicate rate, false-block rate and summary faithfulness.",
        "Several of these are not measured yet. The Results page lists exactly which, rather than estimating them.",
      ] },
      { id: "gate", title: "Merge gate", body: ["On the validation split, against a stored baseline, a change fails if any of these happens: recall drops beyond its tolerance, the false-positive rate rises beyond its tolerance, any official site is called dangerous, injection success rises above zero, or faithfulness falls below full. The tolerances are documented in the repository. The test split is never used to tune."] },
      { id: "provenance", title: "The published artifact", body: ["Each evaluation run writes one file that records the dataset hash, the code revision, the model ids, the thresholds and the seeds. The newest published file is bundled into this site at build time. Its details:"], data: "provenance" },
    ],
  },

  integration: {
    lead: "Ready to connect, not connected. Falcon Lens has no existing integration with any authority and implies no endorsement. This page explains how a police mobile app or an internal agent could connect. Nothing here is wired to any agency system.",
    sources: ["docs/INTEGRATION.md", "contracts/openapi.yaml"],
    callout: "Ready to connect. Not connected. Everything below describes a possible connection.",
    sections: [
      { id: "surfaces", title: "Surfaces", table: {
        cols: ["Surface", "Entry", "Authentication"],
        rows: [
          ["REST v1", "/v1/* with a published OpenAPI contract, generated and drift-checked in CI", "X-API-Key header or Authorization: Bearer"],
          ["MCP (streamable HTTP)", "/mcp", "Bearer token"],
          ["STIX 2.1", "GET /v1/intel/stix", "A key with the intel scope"],
          ["Webhooks (outbound)", "campaign.alert, to configured targets", "HMAC-SHA256 signature"],
        ],
        rowCaps: ["rest_api", "mcp", "stix", null],
      }, body: ["STIX patterns are fully refanged (valid STIX) in this one response, for intel-scope callers only. This is a documented exception; everywhere else indicators stay defanged.", "Check endpoints also work anonymously with a per-address limit, which is how the public web app uses them. A key that is presented but wrong gets 401, never silent anonymous access."] },
      { id: "keys", title: "Keys, scopes and limits", list: [
        "Scopes: check (submit checks), read (campaigns, incidents, streams), intel (STIX) and operator (approve or reject held Sentinel actions).",
        "Keys are stored only as argon2id hashes, peppered. Each key has its own per-minute rate limit; beyond it the API answers 429 with Retry-After.",
        "Seeded keys follow least privilege: the public sandbox key can only check; the operator key can only read and approve; the MCP service key can check and read. STIX consumers get a separate intel key.",
        "Outside local development the API and MCP refuse to start while any secret still has its placeholder value.",
        "Every keyed call is written to an append-only audit table: key id, method, path, status, request id and a keyed hash of the caller address, never bodies.",
        "Errors follow RFC 9457 problem details and never echo submitted content. Lists use cursors and writes accept an idempotency key.",
        "Incident payloads for callers without the operator scope omit takedown drafts and approver names. This holds for REST, streams and MCP.",
      ] },
      { id: "endpoints", title: "Endpoints at a glance", list: [
        "POST /v1/check/{url, message, email, image}",
        "GET /v1/verdicts/{id} and its event stream",
        "POST /v1/reports and POST /v1/feedback",
        "GET /v1/campaigns and its stream; GET /v1/incidents, its stream and one incident",
        "POST /v1/incidents/{id}/actions/{action_id}/approve or reject (operator scope)",
        "GET /v1/intel/stix; GET /v1/meta",
      ] },
      { id: "mcp", title: "MCP tools", body: ["check_url, check_message, check_email, get_verdict, list_campaigns, list_incidents, get_incident and submit_report. They call the REST API with a service key limited to check and read, so MCP can never approve an action or export intelligence. Returned text is data, not instructions."], cap: "mcp" },
      { id: "webhooks", title: "Webhooks", list: [
        "For a campaign incident the API posts an event named campaign.alert with the campaign as data.",
        "Headers carry a timestamp, a v1 signature (HMAC-SHA256 over the timestamp, a dot and the raw body) and a delivery id.",
        "Receivers verify the signature in constant time and reject timestamps outside a five-minute window.",
        "Failed deliveries are retried with back-off, so a receiver may see the same delivery twice: de-duplicate on the delivery id.",
      ] },
      { id: "boundary", title: "Data crossing the boundary", list: [
        "In: a link, message text, an email file or an image for a check; a report or feedback with hashes only. Report text is stored only with explicit consent.",
        "Out: verdicts whose reasons cite evidence ids, with defanged links; campaign cards and incidents with defanged indicators and aggregate counts; STIX indicators. Never raw page or message text, never personal data of reporters. Replayed or synthetic data carries a source label.",
        "With a cloud model route, the model sees structured evidence, not raw content; see the privacy page.",
      ] },
      { id: "sovereign", title: "Sovereign mode", body: ["When sovereign mode is on, every model call goes to the local model, so no message or page content is sent to a cloud model. The API and MCP behave identically, and the meta endpoint reports the mode so a client can display it. Feeds that need external keys stay off unless configured."] },
    ],
  },

  privacy: {
    lead: "The engineering behind the Privacy page. It describes how the system handles data; it is not a claim of compliance with any legal regime.",
    sources: ["docs/PRIVACY.md", "docs/THREAT_MODEL.md"],
    sections: [
      { id: "stored", title: "What is stored", list: [
        "The SHA-256 hash of the canonical input, a defanged copy of each link checked, the evidence and the verdict.",
        "What a person pastes is not stored as such. Message and email bodies are not stored unless the user opts in to report them.",
        "Reports and feedback arrive as hashes; text is kept only with consent.",
      ] },
      { id: "redaction", title: "Redaction", list: [
        "Redaction runs on text before any cloud model call. It covers UAE phone numbers, Emirates ID numbers, card numbers (checked with the Luhn test), email addresses and IBANs.",
        "Logs are separate: they escape control characters, cap field lengths and carry no message bodies.",
      ] },
      { id: "cloud", title: "Cloud mode", body: ["Redacted, spotlighted text goes to the cloud model API for extraction, investigation and responses. Nothing else leaves the machine except lookups to RDAP, certificate-transparency logs and feeds, which carry domain names only."] },
      { id: "sovereign", title: "Sovereign mode", body: ["Every model call goes to the local model, so no message or page content is sent to a cloud model. Lookups are still domain-only, and an environment setting can disable them."] },
      { id: "retention", title: "Retention", body: ["A retention policy is planned (verdicts kept for a limited period, then aggregated) but it is not yet automated. The audit log is append-only. Snapshots are local only."] },
      { id: "never", title: "What the product never asks for", body: ["Personal, banking or ID details. It never enters data into a suspicious page and never submits a form."] },
    ],
  },
};

const ar: Pages = {
  architecture: {
    lead: "تعمل عدسة الصقر خدماتٍ منفصلة على شبكات معزولة. تعرض هذه الصفحة الخدمات، ومسار الفحص الواحد، وموجِّه النماذج، ومخازن البيانات، والبيئة المعزولة.",
    sources: ["docs/ARCHITECTURE.md"],
    figure: { src: "/images/architecture.svg", alt: "بنية عدسة الصقر في ثلاث طبقات متراكبة. في الأعلى طبقة المساعد الصوتي: من ميكروفون المتصفح إلى تحويل الكلام إلى نص محلياً، ثم عبارة التنبيه وفهم الطلب والرواية بمقاطع مولَّدة مسبقاً. وفي الوسط الوكيلان الذكيان: «بصير»، المحقّق، بطبقاته من T0 إلى T3 ومحكّمه الحتمي، و«درع»، الحارس، بقواعده وفرزه بمخطط LangGraph والموافقة البشرية. وفي الأسفل طبقة المنصة: الواجهة البرمجية، وناقل الأحداث، وقاعدة البيانات، والبيئة المعزولة، ووسائل الربط الجاهزة غير المربوطة، والمراقبة، والصفحات العامة. ويبيّن مسار مرقّم مرور طلب واحد عبر الطبقات، ويحمل كل مربع شعار الأداة التي يعمل عليها أو اسمها.", width: 1200, height: 1084 },
    sections: [
      { id: "services", title: "الخدمات", list: [
        "البوابة: بروتوكول TLS وسياسة أمن المحتوى وتوجيه تطبيق الويب والواجهة البرمجية وMCP.",
        "الواجهة البرمجية (FastAPI): التحقق من الطلبات وحدود المعدّل والمفاتيح والأحداث المرسلة من الخادم.",
        "المعالج: طبقات الفحص والإشارات والمحكّم.",
        "البيئة المعزولة: خدمة متصفح Playwright مستقلة لا تعيد إلا السمات.",
        "وسيط الخروج: المنفذ الوحيد إلى الإنترنت للمعالج والبيئة المعزولة.",
        "MCP: خادم بروتوكول سياق النموذج، ويستدعي واجهة REST.",
        "درع: مستهلك الأحداث والربط والقواعد ووكيل LangGraph.",
        "قاعدة Postgres (مع pgvector) وRedis تحفظان البيانات والذاكرة المؤقتة والتدفقات.",
      ] },
      { id: "flow", title: "مسار فحص رابط واحد", list: [
        "تتحقق الواجهة البرمجية من الطلب وتطبّق حدّ المعدّل وتمنحه معرّف حكم، وتضع مهمة في تدفق Redis وتردّ بقبول الطلب وعنوان تدفق الأحداث. وإذا ورد طلب ثانٍ للرابط الموحَّد نفسه فإنه يلتحق بالمهمة الجارية.",
        "يشغّل المعالج الطبقات الثلاث الأولى، والرابعة عند الحاجة فقط. وبعد كل طبقة ينشر حكماً جزئياً تنقله الواجهة البرمجية حدثاً مرسَلاً من الخادم.",
        "يصدر المحكّم الحكم النهائي، فيُحفظ ويُرسل حدث حكم إلى تدفق الأحداث.",
        "يستهلك درع الحدث ويربطه بغيره ويطبّق قواعده. وإذا نتج حادث يعمل رسم الفرز ويصل الحادث إلى لوحة الحوادث.",
        "يوجد وضع متزامن ينتظر مدة قصيرة محدودة ثم يعيد أفضل حكم متاح، لخدمة العملاء البسطاء وخادم MCP.",
      ] },
      { id: "kinds", title: "الرسائل والبريد والصور", list: [
        "الرسالة: توحَّد صيغتها (العربية والعربيزي) وتُستخرج سمات القواعد ويُحسب تضمين ويُبحث عن أقرب نصوص احتيال معروفة، ثم يمرّ النص بالمستخرِج المعزول. وكل رابط يوجد فيه يمرّ بمسار الروابط فحصاً فرعياً.",
        "البريد: يُحلَّل بمكتبة اللغة القياسية بسقف للحجم ودون جلب عن بُعد. ويفحص نتائج التوثيق وعدم تطابق الترويسات ونص الرابط مقابل وجهته ورموز QR في الصور، ونوع المرفق وبصمته فقط. وينتقل النص إلى مسار الرسائل.",
        "الصورة: فحص البايتات السحرية وفك رمز QR، ثم استخراج النص بالمستخرِج البصري المعزول. وتمرّ الروابط والنصوص المستخرَجة بالمسارات المناسبة.",
      ] },
      { id: "router", title: "موجِّه النماذج", list: [
        "الأدوار: المستخرِج وبصير والمجيب والرؤية ودرع والحَكَم. ولكل دور نموذج سحابي ونموذج محلي.",
        "في الوضع السيادي، أو عند غياب مفتاح سحابي، تذهب كل الأدوار إلى النموذج المحلي. وعند خطأ سحابي أو انتهاء مهلة يعود الاستدعاء إلى النموذج المحلي ويسجّل عدّاد ذلك.",
        "قبل أي استدعاء سحابي يُحجب المدخل ويُعلَّم: يوضع النص غير الموثوق بين محدِّدات بقيمة عشوائية ويوسَم كل سطر.",
        "يُتحقَّق من المخرجات بمخطط صارم مع محاولة إصلاح واحدة، ثم يُعاد إلى القوالب.",
      ] },
      { id: "stores", title: "مخازن البيانات", list: [
        "Postgres: الأحكام والأدلة ونصوص الاحتيال المعروفة والعلامات والحوادث وإجراءاتها وسجل التدقيق للإضافة فقط ومفاتيح الواجهة المجزّأة والبلاغات والملاحظات وقائمة الحظر ونقاط حفظ درع.",
        "Redis: ذاكرة الأحكام المؤقتة (تختلف مدتها بحسب الحكم) وذاكرة الإشارات ونسخة المصادر المحلية وحدود المعدّل وأقفال الطلب الواحد والتدفقات.",
      ] },
      { id: "sandbox", title: "البيئة المعزولة", list: [
        "تحصل كل زيارة على سياق متصفح جديد، مع منع التنزيلات ومهلة كلية وسقف لعدد التحويلات وسقف لحجم الاستجابة. وتُحمَّل الصفحة مرتين، بملف جوال عربي ثم بملف حاسوب إنجليزي، لكشف التمويه.",
        "لا تعيد إلا السمات: حقول النماذج وأصول وجهاتها، ووجهات إرسال السكربتات، وأصول الموارد المرتبطة، والعنوان، وقدراً محدوداً من النص الظاهر، وبصمتي الأيقونة ولقطة الشاشة، وبصمة بنية الصفحة، وسلسلة التحويلات. وتبقى اللقطات محلية ولا تُقدَّم إلا لمفاتيح موثَّقة.",
        "شبكاتها داخلية: لا يقبل اتصالاً من حاوية البيئة المعزولة إلا وسيط الخروج ومنفذ فحص صحة المعالج. وهي ليست على شبكة المراقبة، ويحمي واجهتها رمز حامل مشترك.",
        "يحظر وسيط الخروج النطاقات الخاصة وحلقة الرجوع والارتباط المحلي والبيانات الوصفية وأسماء الخدمات الداخلية، ولا يسمح إلا بمنفذي الويب القياسيين.",
      ] },
    ],
  },

  cascade: {
    lead: "يمرّ الفحص بما يصل إلى أربع طبقات، يبدأ بأسرعها ويتوقف حين تحسم الأدلة. ومعظم الفحوص لا تصل إلى نموذج لغوي.",
    sources: ["docs/adr/ADR-001-cascade-arbiter.md", "docs/SCORING.md"],
    sections: [
      { id: "tiers", title: "الطبقات الأربع", cards: [
        { tag: "T0", title: "المؤشرات المعروفة", body: "توحيد صيغة المدخل، ثم الرجوع إلى ذاكرة الأحكام وسجل المواقع الرسمية الموثّقة والنسخة المحلية من مصادر الاحتيال المبلَّغ عنه. الميزانية: نحو خمسين جزءاً من الألف من الثانية." },
        { tag: "T1", title: "العنوان نفسه", body: "إشارات حتمية للرابط والنطاق والسمعة تعمل بالتوازي مع نموذج معزَّز بالأشجار معايَر. الميزانية: نحو ثانية واحدة." },
        { tag: "T2", title: "النظر في الصفحة", body: "تفتح البيئة المعزولة الصفحة مرة واحدة وبصورة سلبية. وتضيف سمات الصفحة والمظهر والتحقق من العلامة بالمرجع (القاعدة الحاسمة H1) والمستخرِج المعزول أدلة جديدة. الميزانية: نحو ست ثوانٍ." },
        { tag: "T3", title: "نظرة ثانية بالذكاء الاصطناعي", body: "محقّق محدود يستخدم بضعة استدعاءات أدوات مصنّفة، وللحالات التي ما زالت غامضة بعد الطبقات الثلاث الأولى فقط. الميزانية: نحو خمس عشرة ثانية.", cap: "investigator" },
      ] },
      { id: "exits", title: "الخروج المبكر", body: ["يخرج الفحص مبكراً ليبقى العمل والكلفة ضمن حدود."], list: [
        "تخرج T1 حين تقلّ احتمالية المصنِّف عن الحد الأدنى المضبوط أو تزيد على الحد الأعلى المضبوط ولا يوجد تعارض في العلامة.",
        "تخرج T2 حين تنطبق قاعدة حاسمة أو تقع الاحتمالية بوضوح خارج النطاق الغامض. وإلا فينتقل الفحص إلى T3.",
        "الحدود المضبوطة مدرجة أدناه، منقولة من ملف التقييم المنشور.",
      ], data: "thresholds" },
      { id: "progressive", title: "حكم يتكوّن تدريجياً", list: [
        "بعد كل طبقة ينشر المعالج حكماً جزئياً بمعرّف الحكم نفسه. وتعرض الصفحة الخطوات عند اكتمالها.",
        "ما دام الحكم غير نهائي فقد تعرض الصفحة علامة مؤقتة «مريب» أو «خطِر»، ولا تعرض أبداً نتيجة مؤقتة «لم نجد علامات تحذير».",
        "تدلّ علامة النهائي على حكم المحكّم. والحكم النهائي قطعي: تُتجاهل الأحداث اللاحقة للمعرّف نفسه.",
      ] },
      { id: "separation", title: "من يرى ماذا", list: [
        "المستخرِج المعزول وحده يقرأ نصاً غير موثوق. لا أدوات لديه ويجب أن يعيد مخططاً صارماً.",
        "بصير والمجيب لا يريان إلا أدلة مهيكلة.",
        "لا يحدد أي نموذج لغوي الدرجة ولا يغيّرها. وتدخل أدلة T3 بوزن صفر ويعيد المحكّم تقدير كل شيء.",
      ] },
    ],
  },

  arbiter: {
    lead: "المحكّم هو المكوّن الوحيد الذي يحدد درجة الخطورة والاحتمالية المعايَرة والحكم. أما أوزان الإشارات فهي قيم أولية موثّقة هناك ولا تتكرر هنا.",
    sources: ["docs/SCORING.md"],
    sections: [
      { id: "pipeline", title: "مسار الاحتساب", list: [
        "تُقيَّم القواعد الحاسمة أولاً. والقاعدة التي تنطبق تضع حداً أدنى للحكم، أو حداً أعلى في قواعد الثقة.",
        "يعطي مصنِّف معزَّز بالأشجار احتمالية معايَرة على مجموعة التحقق.",
        "تعدّل الأدلة لوغاريتم الأرجحية: لكل دليل وزن ثابت يُضرب في ثقته، ويُقصّ المجموع ضمن نطاق محدود.",
        "درجة الخطورة هي الاحتمالية على مقياس من مئة، بعد معايِر نهائي مضبوط على مجموعة التحقق.",
        "النطاقات: خطِر فوق العتبة العليا، ومريب بين العتبتين، ولم نجد علامات تحذير دون العتبة الدنيا.",
      ], data: "thresholds" },
      { id: "rules", title: "القواعد الحاسمة", table: {
        cols: ["القاعدة", "الشرط", "الأثر"],
        rows: [
          ["H1 عدم تطابق العلامة", "تُدّعى علامة من إشارات حتمية (عنوان الصفحة أو نصها والأيقونة والموارد المرتبطة، ولا تُستمد أبداً من نموذج لغوي)، وتطلب الصفحة بيانات دخول أو دفعاً، والنطاق المسجَّل ليس من النطاقات التي وثّقتها العلامة.", "خطِر، بحدّ أدنى مرتفع جداً للاحتمالية."],
          ["H2 معروف بالسوء", "ورد الرابط نفسه أو مضيفه حديثاً في أحد مصادر الاحتيال.", "خطِر."],
          ["H3 رسمي موثَّق", "النطاق المسجَّل في قائمة موثَّقة لعلامة، دون إساءة استخدام لتحويل مفتوح ودون ورود في مصدر احتيال.", "يُقصر الحكم على «لم نجد علامات تحذير»، ولا يكون خطِراً أبداً."],
          ["H4 تسريب إلى بوت", "نموذج أو سكربت يرسل بيانات الدخول إلى واجهة بوت مراسلة أو مرحِّل خطّاف ويب.", "خطِر."],
          ["H5 رسالة برابط خطِر", "تحتوي الرسالة أو البريد على رابط حُكم بأنه خطِر أو مريب.", "حكم لا يقل شدة عن أسوأ رابط فرعي، ويستشهد بأدلته."],
          ["H6 طلب رمز تحقق أو وصول عن بُعد", "تطلب الرسالة رمز تحقق أو تثبيت تطبيق وصول عن بُعد، وتنتحل جهة رسمية أو مصرفاً.", "مريب على الأقل."],
        ],
      } },
      { id: "precedence", title: "الأسبقية والسقوف", list: [
        "الفحص المنقوص يتغلب على H3: الرابط الرسمي الذي فشل فحصه يظهر «مريب».",
        "تتغلب H3 على H1 وH4 وH6 في النطاقات الرسمية الموثَّقة، وتُسجَّل القواعد التي أُبطلت.",
        "المصنِّف المضبوط وحده لا ينتج «خطِر»: يحتاج إلى دليل خطورة من الصفحة أو النطاق بجانبه. وكل تحذير يقوده النموذج يستشهد بدليل من المصنِّف.",
      ] },
      { id: "degraded", title: "الفحص المنقوص", list: [
        "إخفاق إشارة حرجة يجعل الحكم منقوصاً ويذكر السبب. أما إشارات الإثراء من أطراف ثالثة فتبقى معلوماتية ولا تُنقص الحكم.",
        "لا يظهر الحكم المنقوص أبداً «لم نجد علامات تحذير»: تعرض الصفحة «مريب» مع سطر يبيّن أن الفحوص لم تكتمل كلها.",
        "إذا تعذّر فتح الصفحة بسبب إخفاق لا ينتجه إلا الطرف بين المتصفح والموقع، فقد يبقى الحكم «لم نجد علامات تحذير»، لكن بشرط وجود دليل ثقة مستقل عن الصفحة. وإلا فهو «مريب» منقوص.",
      ] },
      { id: "explain", title: "الشرح", body: ["يختار المجيب ثلاثة أسباب على الأكثر مرتبة بحسب الوزن، ويجب أن يستشهد كل سبب بمعرّفات أدلة قائمة. ويرفض المدقّق ما عدا ذلك ويعود إلى القوالب ثنائية اللغة. وأسباب التحذيرات التي يقودها النموذج قوالب مستندة إلى الأدلة."] },
    ],
  },

  security: {
    lead: "تلخّص هذه الصفحة نموذج التهديدات وسياسة أمن المحتوى. وحالتها بيان تصميم. أما مقاومة حقن التعليمات فمدرجة في صفحة النتائج ضمن «لم يُقَس بعد».",
    sources: ["docs/THREAT_MODEL.md", "docs/DESIGN.md"],
    sections: [
      { id: "boundaries", title: "حدود الثقة", list: [
        "من الإنترنت إلى البوابة: جمهور مجهول.",
        "من البوابة إلى الواجهة البرمجية وMCP: مفاتيح تكامل محددة الصلاحيات ومفتاح المشغّل.",
        "من المعالج والبيئة المعزولة إلى الإنترنت: محتوى يتحكم به مهاجم.",
        "من المحتوى غير الموثوق إلى نموذج لغوي: حقن التعليمات.",
        "من نصوص المهاجم المخزّنة إلى لوحات الويب: البرمجة عبر المواقع.",
        "من الحاويات إلى المضيف وبيئة تشغيل النموذج المحلي.",
      ] },
      { id: "stride", title: "التهديدات وإجراءات الحدّ منها", table: {
        cols: ["التهديد", "الإجراء"],
        rows: [
          ["انتحال مفاتيح أو خطّافات", "مفاتيح محددة الصلاحيات لا تُحفظ إلا بصمات argon2id، وخطّافات موقَّعة بـHMAC-SHA256 على الطابع الزمني مع نافذة لمنع إعادة التشغيل."],
          ["صفحة محقونة تخفّض درجتها", "المحكّم الحتمي يحدد الدرجات، ومخرجات النموذج لا تمسّها، ونوعا النماذج لا يتشاركان الأدوار."],
          ["إنكار الفعل", "سجل تدقيق للإضافة فقط، سُحبت منه صلاحيتا التعديل والحذف عن دور التطبيق، ويسجّل المفتاح ومعرّفات الأدلة."],
          ["تزوير الطلبات من جهة الخادم", "تحليل DNS ذاتي، وحظر النطاقات الخاصة والبيانات الوصفية، وتثبيت الاتصال على العنوان المفحوص، وإعادة فحص كل تحويل، ووسيط خروج طبقةً ثانية، وشبكة معزولة للبيئة المعزولة."],
          ["تسرّب بيانات شخصية إلى نموذج سحابي أو السجلات", "حجب قبل الاستدعاءات السحابية وقبل التسجيل، وعدم حفظ نصوص الرسائل، والوضع السيادي."],
          ["استخدام الفاحص جالباً مجهولاً", "لا يُعاد محتوى خام أبداً، ولا لقطات إلا لمفاتيح موثَّقة، وحدود لكل عنوان."],
          ["حجب الخدمة", "حدود لحجم كل مدخل وسقوف لفك الضغط وحدود لكل مفتاح ولكل عنوان وطلب واحد لكل رابط وحدود لمجمّع البيئة المعزولة ومهل."],
          ["استغلال المتصفح للهروب من البيئة المعزولة", "تشغيل بلا صلاحيات الجذر، ونظام ملفات جذر للقراءة فقط، وإسقاط كل القدرات، ومنع اكتساب صلاحيات جديدة، وملف seccomp الافتراضي، وشبكة معزولة."],
          ["برمجة عبر المواقع مخزّنة في اللوحات", "هروب React فقط، ولا حقن لشيفرة HTML خام، وسياسة أمن محتوى صارمة بقيمة nonce، وعرض الروابط معطَّلة وغير قابلة للضغط."],
          ["سلسلة التوريد", "تجزئات تبعيات مقفلة، وماسحات للتبعيات والصور، وفحص الأسرار، وقائمة مكوّنات برمجية."],
        ],
      } },
      { id: "injection", title: "التصدي لحقن التعليمات", cap: "injection_defence", list: [
        "لا يصل النص غير الموثوق إلا إلى المستخرِج المعزول، ولا أدوات لديه ويعيد مخططاً صارماً.",
        "التمييز: محدِّدات بقيمة عشوائية مع وسم كل سطر، وتعليمة نظام تنص على أن المحتوى بيانات.",
        "يضيف كاشف دليل خطورة للنص الشبيه بالتعليمات، ولا يُطاع النص أبداً.",
        "تمرّ معطيات الأدوات بفحص المنشأ: يجب أن يأتي كل رابط أو نطاق من الحالة نفسها.",
        "تحدّ ميزانية من استدعاءات الأدوات والوقت والمخرجات كل تشغيل لبصير.",
      ] },
      { id: "csp", title: "سياسة أمن المحتوى في هذا الموقع", list: [
        "تُقدَّم كل صفحة بقيمة nonce جديدة. والسكربتات تحتاج إلى القيمة، ولا يُسمح في الإنتاج بسكربت مضمَّن ولا بـeval.",
        "الأنماط تحتاج إلى القيمة نفسها، فلا تصدر سمة نمط مضمَّنة في HTML الخادم.",
        "الصور والخطوط والاتصالات والعمّال والمانيفست من أصل الموقع نفسه فقط. والخطوط مستضافة ذاتياً. وتُمنع الكائنات وتغيير وسم القاعدة والتأطير.",
        "تُعرض العناوين المريبة معطَّلة، نصاً عادياً، ولا تُعرض روابط أبداً.",
        "يغذّي اختبار متصفح كل نص يتحكم به المهاجم بحمولات من وسوم السكربت والصورة وSVG والسمات، ويفشل عند أي انتهاك للسياسة أو نافذة حوار أو خطأ سكربت.",
      ] },
      { id: "extension", title: "إضافة المتصفح", body: ["بُنيت الإضافة على Manifest V3 بأقل مجموعة أذونات تعمل: التبويب النشط والتخزين وقواعد الطلبات، وإذن مضيف لأصل الواجهة البرمجية فقط. ولا تحمّل شيفرة عن بُعد ولا ترسل إلا الرابط."] },
      { id: "residual", title: "مخاطر متبقية نذكرها بصراحة", list: [
        "يوفّر Docker Desktop على macOS عزل الآلة الافتراضية، لكن لا توجد طبقة gVisor.",
        "قد تموّه صفحات الاحتيال أمام عناوين مراكز البيانات، فقد ترى البيئة المعزولة محتوى بريئاً. ويخفف من ذلك جزئياً التحميل بملفين وإعادة تشغيل اللقطات في التقييمات.",
      ] },
    ],
  },

  evals: {
    lead: "كيف يُبنى التقييم وكيف تُحرس بوابته. كل رقم مقيس في الموقع يأتي من ملف التقييم المنشور الموصوف أدناه، ويظهر في صفحة النتائج.",
    sources: ["docs/EVALS.md"],
    sections: [
      { id: "data", title: "مجموعات البيانات", body: ["تبقى الروابط الحية واللقطات والشعارات في مجلد خاص مستبعد من git. ولا يحمل المستودع إلا بيانات وصفية ببصمات وروابط معطَّلة."], list: [
        "روابط احتيال من مصدر OpenPhish المجتمعي، مع وقت أول ظهور ولقطة للبيئة المعزولة أُخذت عند الجمع.",
        "روابط مشروعة، منها السلبيات الصعبة: صفحات حكومية ومصرفية موثّقة ومواقع شائعة وصفحات دخول ودفع حقيقية ونطاقات مشروعة جديدة وروابط مشروعة مختصرة.",
        "روابط اليوم الصفري: احتيال لم يكن في أي قائمة حظر مفعّلة عند الجمع، مع مواد «بنك الصقر التجريبي» المخترعة.",
        "رسائل بالعربية الخليجية والفصحى والإنجليزية والعربيزي مع أمثلة اصطناعية موسومة، ورسائل بريد خيالية، ومواد حقن محلية.",
        "تُعرض البيانات الحقيقية والاصطناعية منفصلة، وكذلك المسار السحابي والمسار السيادي.",
      ] },
      { id: "splits", title: "التقسيم", list: [
        "قطع زمني: كل مثال اختبار ظهر أولَ مرة بعد كل مثال تدريب.",
        "تجميع بحسب النطاق المسجَّل، فلا يظهر نطاق في تقسيمين.",
        "مجموعة الاختبار مجمَّدة وبصمتها مقفلة، ويجري كل الضبط على مجموعة التحقق.",
      ] },
      { id: "metrics", title: "المقاييس", list: [
        "فترات ثقة بالمعاينة الذاتية للدقة والاستدعاء وF1 ومعدل الإنذار الخاطئ وPR-AUC، ومنحنى موثوقية وخطأ المعايرة.",
        "أحكام «خطِر» الخاطئة على المواقع الرسمية الموثّقة، واستدعاء اليوم الصفري مقابل خط أساس يعتمد قوائم الحظر فقط، وتحليل الاستئصال بحسب عائلة الإشارة.",
        "الزمن لكل طبقة، وكلفة الفحص الواحد، ونسبة الفحوص التي تصل إلى نموذج لغوي.",
        "أمانة الأسباب للأدلة، ونسبة نجاح هجمات الحقن، ومعدل تقلّب الحكم عبر تشغيلات متكررة، ووضوح العربية بتقدير نموذج غير المولِّد.",
        "درع: تدفق إعادة تشغيل موسوم بحملات مزروعة، يقيس دقة الحوادث واستدعاءها وزمن الوصول إلى الحادث ونسبة التكرار ونسبة الحظر الخاطئ وأمانة الملخص.",
        "كثير من هذه المقاييس لم يُقَس بعد. وتذكر صفحة النتائج أيها بالتحديد بدلاً من تقديره.",
      ] },
      { id: "gate", title: "بوابة الدمج", body: ["على مجموعة التحقق ومقابل خط أساس محفوظ، يفشل أي تغيير إذا حدث أي مما يلي: انخفض الاستدعاء عن حدّ التسامح، أو ارتفع معدل الإنذار الخاطئ عن حدّ التسامح، أو صُنّف موقع رسمي خطِراً، أو ارتفعت نسبة نجاح الحقن فوق الصفر، أو قلّت الأمانة عن الكاملة. وحدود التسامح موثّقة في المستودع. ولا تُستخدم مجموعة الاختبار في الضبط أبداً."] },
      { id: "provenance", title: "الملف المنشور", body: ["يكتب كل تشغيل للتقييم ملفاً واحداً يسجّل بصمة مجموعة البيانات ونسخة الشيفرة ومعرّفات النماذج والعتبات والبذور. وتُضمَّن أحدث نسخة منشورة في هذا الموقع عند البناء. وهذه تفاصيلها:"], data: "provenance" },
    ],
  },

  integration: {
    lead: "جاهز للربط، وغير مربوط. لا يوجد لعدسة الصقر أي ربط قائم مع أي جهة، ولا تدّعي تأييداً. تشرح هذه الصفحة كيف يمكن لتطبيق جوال شرطي أو وكيل داخلي أن يرتبط بها. ولا شيء هنا موصول بأي نظام جهة.",
    sources: ["docs/INTEGRATION.md", "contracts/openapi.yaml"],
    callout: "جاهز للربط، وغير مربوط. كل ما يلي وصف لإمكانية ربط.",
    sections: [
      { id: "surfaces", title: "الواجهات", table: {
        cols: ["الواجهة", "نقطة الدخول", "التوثيق"],
        rows: [
          ["REST الإصدار 1", "/v1/* مع عقد OpenAPI منشور، يُولَّد ويُفحص انحرافه في التكامل المستمر", "ترويسة X-API-Key أو Authorization: Bearer"],
          ["MCP (HTTP قابل للبث)", "/mcp", "رمز حامل"],
          ["STIX 2.1", "GET /v1/intel/stix", "مفتاح بصلاحية intel"],
          ["الخطافات الخارجية (Webhooks)", "campaign.alert إلى الوجهات المضبوطة", "توقيع HMAC-SHA256"],
        ],
        rowCaps: ["rest_api", "mcp", "stix", null],
      }, body: ["تُعاد أنماط STIX غير معطَّلة كلياً (STIX صالح) في هذه الاستجابة وحدها ولأصحاب صلاحية intel فقط. وهذا استثناء موثّق، وتبقى المؤشرات معطَّلة في كل مكان آخر.", "تعمل نقاط الفحص أيضاً دون مفتاح بحدّ لكل عنوان، وبهذا يستخدمها تطبيق الويب العام. أما المفتاح المقدَّم الخاطئ فيُرفض بالرمز 401، ولا يُعامل أبداً بصمت معاملة المجهول."] },
      { id: "keys", title: "المفاتيح والصلاحيات والحدود", list: [
        "الصلاحيات: check لإرسال الفحوص، وread للحملات والحوادث والتدفقات، وintel لـSTIX، وoperator للموافقة على إجراءات درع المعلّقة أو رفضها.",
        "لا تُحفظ المفاتيح إلا بصمات argon2id مع ملح سري. ولكل مفتاح حد خاص بالطلبات في الدقيقة، وعند تجاوزه تردّ الواجهة بالرمز 429 مع Retry-After.",
        "المفاتيح المبذورة تتبع أقل الصلاحيات: مفتاح البيئة العامة يفحص فقط، ومفتاح المشغّل يقرأ ويوافق فقط، ومفتاح خدمة MCP يفحص ويقرأ. ويُمنح مستهلكو STIX مفتاح intel منفصلاً.",
        "خارج بيئة التطوير المحلية ترفض الواجهة البرمجية وMCP العمل ما دام أي سر بقيمته المؤقتة.",
        "كل نداء بمفتاح يُسجَّل في جدول تدقيق للإضافة فقط: معرّف المفتاح والطريقة والمسار والحالة ومعرّف الطلب وبصمة مفتاحية لعنوان المتصل، ولا تُسجَّل المحتويات أبداً.",
        "الأخطاء بصيغة RFC 9457 ولا تعيد محتوى المُرسَل. والقوائم بمؤشرات تصفح، والكتابات تقبل مفتاح عدم التكرار.",
        "حمولات الحوادث لمن لا يملك صلاحية operator تحذف مسودات الإزالة وأسماء الموافقين، في REST والتدفقات وMCP.",
      ] },
      { id: "endpoints", title: "نظرة على نقاط الدخول", list: [
        "POST /v1/check/{url, message, email, image}",
        "GET /v1/verdicts/{id} وتدفق أحداثه",
        "POST /v1/reports وPOST /v1/feedback",
        "GET /v1/campaigns وتدفقها؛ وGET /v1/incidents وتدفقها وحادث واحد",
        "POST /v1/incidents/{id}/actions/{action_id}/approve أو reject (صلاحية operator)",
        "GET /v1/intel/stix؛ وGET /v1/meta",
      ] },
      { id: "mcp", title: "أدوات MCP", body: ["check_url وcheck_message وcheck_email وget_verdict وlist_campaigns وlist_incidents وget_incident وsubmit_report. وهي تستدعي واجهة REST بمفتاح خدمة مقصور على check وread، فلا يستطيع MCP أبداً الموافقة على إجراء أو تصدير معلومات التهديد. والنص المعاد بيانات لا تعليمات."], cap: "mcp" },
      { id: "webhooks", title: "الخطافات الخارجية", list: [
        "لحادث حملة ترسل الواجهة حدثاً اسمه campaign.alert وبيانات الحملة.",
        "تحمل الترويسات طابعاً زمنياً وتوقيع v1 (HMAC-SHA256 على الطابع الزمني ثم نقطة ثم الجسم الخام) ومعرّف تسليم.",
        "يتحقق المستقبِل من التوقيع بزمن ثابت ويرفض الطوابع الزمنية خارج نافذة من خمس دقائق.",
        "تُعاد محاولة التسليمات الفاشلة مع تأخير تصاعدي، فقد يرى المستقبِل التسليم نفسه مرتين: يزيل التكرار بمعرّف التسليم.",
      ] },
      { id: "boundary", title: "البيانات التي تعبر الحدود", list: [
        "يدخل: رابط أو نص رسالة أو ملف بريد أو صورة للفحص؛ وبلاغ أو ملاحظة ببصمات فقط. ولا يُخزَّن نص البلاغ إلا بموافقة صريحة.",
        "يخرج: أحكام تستشهد أسبابها بمعرّفات أدلة وروابطها معطَّلة؛ وبطاقات حملات وحوادث بمؤشرات معطَّلة وأعداد مجمّعة؛ ومؤشرات STIX. ولا يخرج نص الصفحات أو الرسائل الخام ولا بيانات شخصية للمُبلِّغين. والبيانات المُعاد تشغيلها أو الاصطناعية تحمل وسماً لمصدرها.",
        "مع المسار السحابي يرى النموذج أدلة مهيكلة لا محتوى خاماً؛ انظر صفحة الخصوصية.",
      ] },
      { id: "sovereign", title: "الوضع السيادي", body: ["عند تفعيل الوضع السيادي تذهب كل نداءات النموذج إلى النموذج المحلي، فلا يُرسَل محتوى الرسائل أو الصفحات إلى نموذج سحابي. وتتصرف الواجهة البرمجية وMCP بالطريقة نفسها، وتُبلغ نقطة meta بالوضع ليعرضه العميل. وتبقى المصادر التي تحتاج مفاتيح خارجية مطفأة ما لم تُضبط."] },
    ],
  },

  privacy: {
    lead: "الهندسة التي تقف وراء صفحة الخصوصية. وهي وصف لكيفية تعامل النظام مع البيانات، وليست ادعاءً بالامتثال لأي نظام قانوني.",
    sources: ["docs/PRIVACY.md", "docs/THREAT_MODEL.md"],
    sections: [
      { id: "stored", title: "ما الذي يُخزَّن", list: [
        "بصمة SHA-256 للمدخل بعد توحيد صيغته، ونسخة معطَّلة من كل رابط يُفحص، والأدلة والحكم.",
        "لا يُخزَّن ما يلصقه الشخص بصورته الأصلية. ولا تُخزَّن نصوص الرسائل والبريد ما لم يختر المستخدم الإبلاغ عنها.",
        "تصل البلاغات والملاحظات ببصمات، ولا يُحفظ النص إلا بموافقة.",
      ] },
      { id: "redaction", title: "الحجب", list: [
        "يُطبَّق الحجب على النص قبل أي استدعاء لنموذج سحابي. ويشمل أرقام الهاتف الإماراتية وأرقام الهوية الإماراتية وأرقام البطاقات (بفحص Luhn) وعناوين البريد الإلكتروني وأرقام الآيبان.",
        "السجلات منفصلة: تهرّب محارف التحكم وتقيّد أطوال الحقول ولا تحمل نصوص الرسائل.",
      ] },
      { id: "cloud", title: "الوضع السحابي", body: ["يذهب نص محجوب ومعلَّم إلى واجهة النموذج السحابي للاستخراج والتحقيق والإجابة. ولا يغادر الجهاز غير ذلك سوى عمليات بحث في RDAP وسجلات شفافية الشهادات ومصادر الاحتيال، وهذه تحمل أسماء النطاقات فقط."] },
      { id: "sovereign", title: "الوضع السيادي", body: ["تذهب كل نداءات النموذج إلى النموذج المحلي، فلا يُرسَل محتوى الرسائل أو الصفحات إلى نموذج سحابي. وتبقى عمليات البحث بأسماء النطاقات فقط، ويمكن لإعداد في البيئة تعطيلها."] },
      { id: "retention", title: "الاحتفاظ", body: ["سياسة الاحتفاظ مخطَّطة (حفظ الأحكام مدة محدودة ثم تجميعها إحصائياً) لكنها لم تُؤتمت بعد. وسجل التدقيق للإضافة فقط. واللقطات محلية فقط."] },
      { id: "never", title: "ما لا يطلبه المنتج أبداً", body: ["بيانات شخصية أو مصرفية أو رقم هوية. ولا يُدخل بيانات في صفحة مشبوهة ولا يرسل أي نموذج."] },
    ],
  },
};

export const DOCS: Record<Lang, Pages> = { en, ar };
