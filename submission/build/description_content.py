# ruff: noqa: E501, S101
"""Content of the project description document, as renderer-neutral blocks.

Block forms (tuples):
    ("h1", text) ("h2", text) ("h3", text)        headings (real heading styles in docx, outline in PDF)
    ("p", text)                                    paragraph; **bold** and `code` inline
    ("ul", [text, ...])                            bullet list
    ("table", [header...], [[cell...], ...], [relative widths])
    ("img", key, alt text, caption, width in inches)
    ("note", title, text)                          highlighted call-out
    ("pb",)                                        page break
    ("ar_h1", text) ("ar_p", text) ("ar_ul", [..]) right-to-left Arabic blocks (formal MSA)

Every number is read from the published artifacts through `Artifacts`; prose uses number words for plain counts.
The product word for "harmless" is never used, in English or Arabic (checked by check.py).
"""

from __future__ import annotations

from typing import Any

from common import ROOT, Artifacts, evidence, fmt_pct, tools_by_category

Block = tuple[Any, ...]


def shipped(cap_id: str) -> bool:
    """True when the capability's probes hold in this checkout (a merged feature); else the text says it is planned."""
    from submission import capabilities as caps  # noqa: PLC0415  (scripts/ is on sys.path)

    cap = next(c for c in caps.CAPABILITIES if c.id == cap_id)
    return all(caps.probe(ROOT, spec) for spec in cap.probes)


def or_planned(cap_id: str, text: str) -> str:
    return text if shipped(cap_id) else f"Planned, not shipped yet: {text[0].lower()}{text[1:]}"


METRIC_PLAIN = {
    "recall": "Of the real scams in the set, the share Falcon Lens flagged. Higher is better.",
    "precision": "Of the checks flagged, the share that really were scams. Higher is better.",
    "f1": "A single figure balancing recall and precision. Higher is better.",
    "fpr": "Of the genuine items, the share flagged by mistake. Lower is better.",
    "pr_auc": "How well scams are ranked above genuine items overall. Higher is better.",
    "ece": "How far stated confidence is from what really happened. Lower is better.",
}


def build(a: Artifacts) -> list[Block]:
    b: list[Block] = []
    add = b.append

    # ── Arabic summary (formal MSA) ────────────────────────────────────────────────────────────
    add(("ar_h1", "ملخص بالعربية"))
    add(
        (
            "ar_p",
            "**عدسة الصقر** مساعد يعمل بالذكاء الاصطناعي، يضع العربية أولاً، ويحمي المقيمين في دولة الإمارات من الروابط والمواقع والرسائل والبريد الإلكتروني الاحتيالية. يفحص المستخدم الرابط أو الرسالة أو البريد أو الصورة المشبوهة، فيحصل خلال ثوانٍ على نتيجة مدعومة بالأدلة وتوضيح لما ينبغي فعله.",
        )
    )
    add(
        (
            "ar_p",
            "**المشكلة.** تصل إلى السكان رسائل عن مخالفات مرورية ورسوم توصيل ورموز تحقق مصرفية وخدمات الهوية الرقمية، وتقود إلى صفحات تبدو رسمية وتعيش ساعات قليلة، فتتأخر قوائم الحجب في اكتشافها. ويتضرر كبار السن وغير المتخصصين أكثر من غيرهم حين يكون التحذير بالإنجليزية وبمصطلحات تقنية.",
        )
    )
    add(
        (
            "ar_p",
            "**كيف يعمل الفحص.** يمر كل فحص عبر طبقات متتالية يمكن أن تنتهي عند أي منها: ذاكرة وقوائم معروفة (T0)، ثم تحليل العنوان ومصنِّف مدرَّب (T1)، ثم متصفح معزول يفتح الصفحة مرة واحدة دون أن يكتب فيها شيئاً ويقارن ما تدّعيه بمن يملك العنوان فعلاً (T2)، ثم «بصير» الذكي للحالات الملتبسة فقط (T3). وفي النهاية يحدد **حَكَم برمجي ثابت** الدرجة والنتيجة، ولا يستطيع أي نموذج ذكاء اصطناعي تغييرها.",
        )
    )
    add(
        (
            "ar_p",
            "**النتائج الثلاث.** «خطِر»، أو «مشبوه»، أو «لم نجد علامات تحذير». ولا يمنح النظام أي رابط شهادة سلامة مطلقة، لأن أحداً لا يستطيع ضمان ذلك، ويذكّر دائماً بالحذر. ويرافق كل نتيجة أسبابها المرتبطة بأدلة محددة، وما يجب فعله الآن، وما يجب فعله إن كان المستخدم قد ضغط الرابط.",
        )
    )
    add(
        (
            "ar_p",
            "**الوكيلان.** «بصير» يدرس حالة واحدة عبر آلة حالات محدودة وأدوات مفحوصة. و«درع» يعمل على مدار الساعة، فيربط الفحوص المتشابهة في حملة واحدة، ويحظر المؤشرات السيئة داخل النظام بحظر مؤقت قابل للتراجع، ويكتب مسودات بلاغات وطلبات إزالة تنتظر موافقة موظف بشري قبل أن يخرج أي شيء من النظام.",
        )
    )
    add(
        (
            "ar_p",
            "**الخصوصية والسيادة.** لا يطلب النظام بيانات شخصية أو مصرفية أو هوية، ويحتفظ ببصمة المدخل ونتيجته فقط، ويخفي الأرقام الحساسة قبل أي استدعاء لنموذج سحابي. وفي «الوضع السيادي» تعمل جميع النماذج محلياً فلا يغادر أي محتوى الجهاز.",
        )
    )
    add(
        (
            "ar_p",
            f"**النتائج المقاسة.** على مجموعة الاختبار المحجوزة (عدد العناصر {a.raw('test.n')}) التي لم تُستعمل في الضبط، بلغ الاستدعاء {a.pct('test.recall')} ومعدل الإنذار الخاطئ {a.pct('test.fpr')} (نطاق ثقة تقريبي من {a.ci('test.fpr').replace(' to ', ' إلى ')}). والمقياس يخص مرحلة تحليل العنوان فقط. أما في تشغيل حيّ على النظام كاملاً لعدد {a.fp_n()} موقعاً مشروعاً محجوزاً فقد نُبِّه خطأً إلى {a.fp_pct()} منها، وهو أعلى بكثير من هدفنا، ونذكر ذلك صراحة. ولم تُقَس بعدُ طبقة المتصفح المعزول ولا بصير الذكي ولا مقاومة حقن التعليمات ولا الوضع السيادي، ولذلك لا نذكر أي رقم عنها.",
        )
    )
    add(
        (
            "ar_p",
            "**الربط مع الجهات المختصة.** تتوفر واجهة REST ومخدّم MCP وتصدير STIX وخطافات ويب موقَّعة. المشروع **جاهز للربط وغير مرتبط** بأي نظام، وهو مشروع مستقل لا يتبع شرطة أبوظبي ولا يحمل تأييداً منها ولا يستخدم شعاراتها.",
        )
    )
    add(("pb",))

    # ── 1 Executive summary ────────────────────────────────────────────────────────────────────
    add(("h1", "1. Executive summary"))
    add(
        (
            "p",
            "**Falcon Lens (عدسة الصقر)** is an Arabic-first AI agent that protects people in the UAE from scam links, fake websites, scam messages and phishing emails. A resident pastes or shares anything suspicious and, within seconds, gets a clear answer in Arabic or English: what we found, why, and what to do now, including what to do if they already clicked.",
        )
    )
    add(("p", "It is built around two AI agents and one rule: **models read and explain, fixed code decides.**"))
    add(
        (
            "ul",
            [
                "**The Investigator (Baseer | بصير)** judges one input. It is a tiered cascade of checks (T0 to T3). Fixed code settles clear cases early. An AI model is used only for the unclear band, and it can never set or change the score.",
                "**The Sentinel (Dir' | درع)** runs around the clock as a backend agent. It links single checks into incidents and campaigns, blocks known-bad indicators inside our own system (every block expires and can be undone), and drafts takedown requests and police reports that wait for a human to approve. It sends nothing itself.",
            ],
        )
    )
    add(
        (
            "p",
            '**Hey Falcon.** Say "Hey Falcon" (يا صقر) on the voice page and the assistant checks what you copied and narrates the live steps of both agents in English or Arabic. Speech is recognised on our own machine, and audio and transcripts are not stored or logged. The Arabic clips use a stock voice; a cloned Emirati voice is pending an owner-consented recording.',
        )
    )
    add(
        (
            "p",
            "**On-premise deployment.** If an authority adopts it, the same stack runs inside its own network. In sovereign mode every model role runs on a local model on its own servers, speech recognition is local, and integration is through REST, SSE, MCP, STIX export and signed webhooks: ready to connect, not connected. A production deployment would still need the authority's own sign-on and roles, scaling and high availability (proven on one machine only), closed-network feeds for link lookups, and its own security review and penetration test.",
        )
    )
    add(("h3", "What makes it different"))
    add(
        (
            "ul",
            [
                "**It targets brand-new fake pages.** A page that claims to be a known organisation, asks for credentials, and sits on an address that organisation does not own is flagged by a rule, even if no blocklist has heard of it yet.",
                "**Code decides, not AI.** The score comes from a deterministic arbiter. A scam page cannot talk its way out, because the model that reads page text has no tools and cannot touch the score.",
                "**A person approves anything that leaves the system.**",
                "**It can run fully on local models** (sovereign mode), so no message or page content leaves the machine.",
                "**Every number is traceable.** Each figure in this document is copied by a script from a saved evaluation result. Where something has not been measured, we say so.",
            ],
        )
    )
    add(("h3", "Where it stands today (honest summary)"))
    add(
        (
            "p",
            f"The whole path works end to end on a laptop: web app, API, extension, MCP server, both agents, dashboards. Judged by address alone on a held-out test set, the classifier and arbiter reach recall {a.pct('test.recall')} with a false-alarm rate of {a.pct('test.fpr')} (small sets; ranges are given in section 8). Run live through the full stack on {a.fp_n()} legitimate sites, the false-alarm rate was {a.fp_pct()}, well above our target. We show it rather than hide it, and explain why in section 8. Red-team, brand-new-page, link-less message, cost, stability and model-route results are published too (section 8), and the one thing still missing is a native reader's rating of the Arabic text.",
        )
    )
    add(
        (
            "note",
            "Independence",
            "Falcon Lens is an independent entry for the Abu Dhabi Police x 42 ScamShield AI challenge. It is **not affiliated with or endorsed by Abu Dhabi Police**, uses no police logos or branding, and is **ready to connect, not connected** to any police or government system.",
        )
    )
    add(("h3", "How it maps to the judging criteria"))
    add(
        (
            "table",
            ["Criterion", "What we built", "Evidence in this document"],
            [
                [
                    "Detection accuracy",
                    "A cascade T0 to T3 with a fixed arbiter, a verified-official rule, redirects followed in the sealed browser, and a cloaking check.",
                    "See the results chapter: frozen test split, fresh two-hundred-site test, red-team.",
                ],
                [
                    "Early detection and coverage",
                    "A brand check that flags look-alike pages no list knows, scam-script recognition for messages with no link. "
                    + or_planned(
                        "hunter", "A proactive hunter that finds new look-alike domains from certificate logs."
                    )
                    + " "
                    + or_planned("helpline_registry", "An official-number registry that flags fake helplines.")
                    + " Search, ads and Maps coverage: ready, needs a key.",
                    "See the chapters on the sealed browser, results, and limitations.",
                ],
                [
                    "Explainability and actionability",
                    "Reasons in Arabic tied to evidence, a trace for every check, STIX export, takedown drafts held for a human. "
                    + or_planned(
                        "evidence_pack",
                        "A police evidence pack with a screenshot, WHOIS and RDAP, hosting, UTC timestamps, a SHA-256 manifest and a takedown draft.",
                    ),
                    "See the chapters on police features, the verdict and its reasons, and integration.",
                ],
                [
                    "UAE relevance and innovation",
                    "Arabic first, a registry of UAE brands including banks, TAMM and UAE PASS, a voice assistant in Arabic and English, a perceptual-hash page comparison, campaign linking, a bounded AI Investigator.",
                    "See the chapters on residents, and the two agents.",
                ],
                [
                    "Feasibility and presentation",
                    "A live demo on one machine, sovereign mode on local models, an operator route selector, an on-premise pilot path.",
                    "See the chapters on privacy, results, and integration.",
                ],
            ],
            [1.4, 3.7, 1.5],
        )
    )
    add(("pb",))

    # ── 2 Problem ──────────────────────────────────────────────────────────────────────────────
    add(("h1", "2. The problem in the UAE"))
    add(
        (
            "p",
            "Residents receive fake fine notices, delivery-fee requests, bank one-time-code (OTP) requests and UAE Pass look-alike links by SMS, WhatsApp and email. The pages look official and often exist for only hours. A blocklist usually learns about a page after people have already opened it.",
        )
    )
    add(
        (
            "p",
            "The people hit hardest are older and non-technical residents. A warning written in English and in security jargon does little for them. They need a short, calm answer in Arabic that says what to do next.",
        )
    )
    add(
        (
            "p",
            "This document deliberately prints **no statistics about the scale of scams**. We would only quote a figure with a public source link, and none is quoted here. Every number that does appear describes our own measured results.",
        )
    )
    add(("h3", "What a good answer has to be"))
    add(
        (
            "ul",
            [
                "**Fast**, because the page may disappear within hours and people decide in seconds.",
                "**Understandable**: Arabic first, short, no jargon, with next steps.",
                "**Evidence-backed**: each reason points to something concrete that was found.",
                "**Honest**: never gives a clean bill of health, and says when a check could not be completed.",
                "**Proactive**: connects many reports into one campaign so the rest of the public can be warned early.",
            ],
        )
    )

    # ── 3 Features ─────────────────────────────────────────────────────────────────────────────
    add(("h1", "3. What Falcon Lens does for residents and for police"))
    add(
        (
            "p",
            'Each feature below has one plain sentence and says who benefits. "In the repository" means the code and its tests are merged on the main branch of the public repository. It does not mean any outside organisation uses it.',
        )
    )
    add(("h2", "3.1 For residents"))
    add(
        (
            "table",
            ["Feature", "In one plain sentence", "Who benefits"],
            [
                ["Link check", "Paste a link and get a verdict that updates as each layer finishes.", "Any resident"],
                [
                    "Message check",
                    "Paste an SMS or WhatsApp text (Arabic, Gulf Arabic, Arabizi or English); every link inside is checked too.",
                    "Residents, especially older people",
                ],
                [
                    "Email check",
                    "Upload a saved email file; we read it locally and never open remote content.",
                    "Residents, small businesses",
                ],
                [
                    "Picture and QR check",
                    "Share a screenshot or QR code; we read the code and any text, then check what we find.",
                    "Anyone who gets QR scams",
                ],
                [
                    "Clear Arabic verdicts",
                    "Three possible answers, each with reasons, what to do now and what to do if you already clicked.",
                    "Everyone, above all non-technical users",
                ],
                [
                    "Official reporting channels",
                    "The answer shows the official police reporting channels, taken from the official site with its source and date; if unverified, only a generic line.",
                    "Residents who want to report",
                ],
                [
                    "Web app (PWA)",
                    "An Arabic-first, right-to-left site that can sit on the phone home screen and appear in the Android share menu.",
                    "Phone users",
                ],
                [
                    "Chrome extension",
                    "Warns before you type on a risky page and can check links in webmail and chat web apps; it sends only the address.",
                    "Desktop users",
                ],
            ],
            [1.2, 3.4, 1.6],
        )
    )
    add(("h2", "3.2 For police and security operators"))
    add(
        (
            "table",
            ["Feature", "In one plain sentence", "Who benefits"],
            [
                [
                    "Campaign detection",
                    "Many fake pages copying one organisation are grouped into one campaign, automatically.",
                    "Analysts, response teams",
                ],
                [
                    "Brand-new fake page rule",
                    "A page claiming a brand it does not own and asking for credentials is flagged even if no list knows it.",
                    "Everyone downstream",
                ],
                [
                    "Incident board",
                    "A screen of incidents with evidence, and approve or reject for each drafted action.",
                    "Operators",
                ],
                [
                    "Human-approved actions",
                    "Takedown and police-report drafts are written in Arabic and English and wait for an officer; nothing is sent automatically.",
                    "Officers, legal teams",
                ],
                [
                    "Internal blocking",
                    "Known-bad indicators are blocked inside our own system, with an expiry and an undo.",
                    "Operations",
                ],
                [
                    "Intelligence export",
                    "Incidents leave as standard STIX 2.1 bundles or as signed webhooks.",
                    "SOC and threat-intelligence teams",
                ],
                [
                    "REST API and MCP server",
                    "Other apps, and AI assistants, can request checks and read results with scoped keys.",
                    "Developers of police apps",
                ],
                [
                    "Dashboards and alerts",
                    "Live health, quality and security dashboards, with a runbook entry for every alert.",
                    "Operations, auditors",
                ],
                [
                    "Sovereign mode",
                    "Every model call can run on local machines, so no message or page content leaves.",
                    "Data-protection and procurement teams",
                ],
                [
                    "Audit log",
                    "Every action is stored with the evidence behind it, and cannot be edited by the application.",
                    "Auditors",
                ],
            ],
            [1.2, 3.4, 1.6],
        )
    )
    add(
        (
            "img",
            "screenshot-dangerous-en",
            "Screenshot of the check result page for a test page of the invented Falcon Demo Bank. A red Dangerous banner, a list of reasons each with evidence identifiers, a timeline of the check layers, what to do now, and official reporting channels.",
            "Figure 2. The result page for a fictional test fixture (invented brand Falcon Demo Bank, reserved .test address). Demo data. Any score or timing inside the picture comes from that test run and is not a published metric.",
            6.2,
        )
    )
    add(
        (
            "img",
            "screenshot-mobile-ar",
            "Screenshot of the Arabic phone layout of the result page for a test page of the invented Falcon Demo Bank: a red banner reading Dangerous in Arabic, the claimed brand, and a risk bar.",
            "Figure 1. The Arabic phone layout, right to left. Fictional test fixture, demo data.",
            2.3,
        )
    )
    add(
        (
            "img",
            "screenshot-campaigns-ar",
            "Screenshot of the Arabic campaign board showing three campaign cards with severity, number of linked checks and advice, next to a similarity radar. All entries are replayed demo data about the invented Falcon Demo Bank.",
            "Figure 8. The campaign board, Arabic view. Replayed demo data from the invented brand Falcon Demo Bank, not real campaigns.",
            5.6,
        )
    )
    add(("h2", "3.3 The voice assistant: Hey Falcon (يا صقر)"))
    add(
        (
            "ul",
            [
                '**Wake word and listening.** Say "Hey Falcon" or «يا صقر». Speech is turned into text on our own machine with a local Whisper model; audio and transcripts are not stored or logged.',
                "**Language per sentence.** Each sentence is answered in the language it was asked in, Arabic or English, so a mixed conversation works.",
                "**Voices.** The Arabic answers use a pre-generated Emirati-accent Amazon Polly voice (Zayd), produced offline and shipped as clips; the English answers use a local Kokoro voice (am_fenrir). No speech is generated by a cloud service while a user is talking.",
                "**Captions are the spoken words.** What is written on screen is exactly what is said, and the live steps of both agents are numbered as they happen.",
                "**Unique findings.** Each check reads out its own findings, taken from that check's evidence, never one fixed sentence for every result. A short sound marks each verdict.",
                "**No generative answers.** The assistant answers from twenty-two fixed scam-awareness answers written and reviewed by the team, and politely redirects off-topic questions. It does not invent replies.",
                "**Measured on synthetic clips only.** See the voice benchmark in section 8.4; it uses synthetic speech and noise, not real speakers, so it is an upper bound.",
            ],
        )
    )
    add(("h2", "3.4 Per-check findings, traces and the police evidence pack"))
    add(
        (
            "ul",
            [
                "**Findings on the Check page and in traces.** Every check lists what was actually found for that input, in the same wording on the page, in the trace and in the voice assistant.",
                "**Police evidence pack.** One download per check: a screenshot of the sealed browser visit; WHOIS and RDAP data with the registrar and its abuse contact; the hosting address, network (ASN) and the registry country; the TLS certificate details; UTC timestamps; a SHA-256 manifest of every file in the pack so tampering is visible; a bilingual (Arabic and English) takedown request draft; and a STIX 2.1 bundle. The draft is held for a human. Nothing is sent.",
                "**Batch tool.** `make batch` checks a list of URLs from a file and writes a CSV, so a committee can run its own hidden test set. A page at `/ops/batch` does the same in the browser with a key that has the check scope.",
            ],
        )
    )
    add(("h2", "3.5 The proactive hunter and the official-number registry"))
    add(
        (
            "ul",
            [
                "**Hunter (Dir' | درع).** It generates look-alike permutations of registered brand domains and looks them up over DNS-over-HTTPS. It is **off by default**, has a kill switch and daily quotas, and only observes: it registers nothing and visits nothing by itself. Certificate-log search (crt.sh) is switched off. Search, ads and Maps coverage is ready, but needs a key that is not configured.",
                "**Official-number registry.** Fifty-one official helpline numbers for fourteen brands let the message check recognise a scam text that gives a different number for a known organisation. A number match is context only and carries weight zero in the score; it can never raise or lower a verdict on its own.",
            ],
        )
    )
    add(("h2", "3.6 Operators: History, route selector and sovereign proof"))
    add(
        (
            "ul",
            [
                "**Read-only History.** A public read-only History lists checks and incidents (restricted by sign-in in a real deployment). Operator links open Phoenix traces and Grafana dashboards.",
                "**AI route selector.** An operator chooses the route for the model roles: a cloud model with a local fallback, or a local-only route using Inkling or Qwen. The arbiter, not the model, still decides every score on every route.",
                "**Sovereign proof.** The local-only route was run against the scenario set with a network audit that counts calls to a cloud model; results are in section 8.4.",
                "**Phones and the web.** The web app works on phones, including iPhone, as an installable app, and the project is served at falconlens.app for the demonstration.",
            ],
        )
    )
    add(("pb",))

    # ── 4 How a check works ────────────────────────────────────────────────────────────────────
    add(("h1", "4. How a check works, layer by layer"))
    add(
        (
            "p",
            "A check is a **cascade**: a series of layers, each more expensive than the last. Cheap layers settle clear cases quickly, so the costly ones only see what is left. After each layer the verdict is refreshed, so the user sees progress instead of waiting. Time budgets for each layer are design limits, not measurements, and we publish no speed figure.",
        )
    )
    add(
        (
            "img",
            "check-layers",
            "Flow diagram of a check: input, T0 memory and lists, T1 address analysis, T2 sealed browser, T3 AI Investigator for unclear cases only, then the arbiter and verdict. Colours show fixed code, AI model and data.",
            "Figure 3. A check from input to verdict. Teal boxes are fixed code; the blue box is an AI model used only for unclear cases.",
            6.4,
        )
    )
    add(("h2", "4.1 T0: memory and known lists"))
    add(
        (
            "p",
            "**What it does.** Cleans the address into one canonical form, looks for a recent verdict on the same address, checks a registry of verified official domains, and checks a local mirror of an open phishing feed.",
        )
    )
    add(
        (
            "p",
            "**Why it matters.** Repeats and known cases cost almost nothing. Official sites are recognised so that genuine pages are not flagged.",
        )
    )
    add(
        (
            "p",
            '**What it never does.** It never contacts the page itself. A past result is never trusted for long: cached results expire, and cached "no warning signs" results expire sooner than cached warnings. Feeds that need a key stay disabled until a key is configured, and the dashboards show them as disabled.',
        )
    )
    add(("h2", "4.2 T1: address analysis and classifier"))
    add(
        (
            "p",
            "**What it does.** Reads the address like a detective. Is a letter swapped for a look-alike (homograph or typo-squat)? Is a brand name glued to extra words (combo-squat)? Is the real host hidden after an @ sign, a raw IP address, hidden characters, a free hosting or tunnel service, or an open redirect? How old is the domain and its certificate? These run in parallel, then a small trained classifier (gradient-boosted trees, calibrated) gives a probability.",
        )
    )
    add(
        (
            "p",
            "**Why it matters.** Many scams give themselves away in the address alone, and this layer needs no page visit.",
        )
    )
    add(
        (
            "p",
            '**What it never does.** It never loads the page and never sends message text anywhere; look-ups for domain age and certificates carry domain names only. The classifier alone can never produce "dangerous": a warning at the top level needs additional page or domain evidence, so a pure model guess cannot raise the loudest alarm.',
        )
    )
    add(("h2", "4.3 T2: the sealed browser and the brand check"))
    add(
        (
            "p",
            "**What it does.** Opens the page once, passively, in an isolated Chromium service whose only network peer is a filtering egress proxy. It loads the page twice, once like an Arabic phone and once like an English desktop, to catch pages that show different content to different visitors (cloaking). It returns **features only**: form fields, where forms post their data, where images and scripts are loaded from, the title, and fingerprints. Then the **brand check** compares what the page claims to be with who owns the address.",
        )
    )
    add(
        (
            "p",
            "**Why it matters.** This catches zero-day pages. A page showing a bank's name, asking for a password or card number, but not on that bank's verified domain is flagged by a fixed rule (H1), whether or not any list knows it. A page that sends form data to a messaging bot or webhook is flagged by another (H4).",
        )
    )
    add(
        (
            "p",
            '**What it never does.** It never types, never logs in, never submits a form, never clicks, never visits more than one normal visit, never downloads files. It never keeps page content: only features go on, and the screenshot stays on the local machine, served only to authenticated keys. A page that cannot be opened is never silently cleared: a degraded check is shown as "suspicious, we could not complete every check", unless strong page-independent trust evidence exists.',
        )
    )
    add(("h2", "4.4 T3: the AI Investigator"))
    add(
        (
            "p",
            "**What it does.** Runs only for the uncertain band. A bounded loop of plan, act, observe and decide may call a short list of approved tools (domain registration look-up, certificate look-up, page render, brand comparison, similar-scam-script search, reputation check, redirect expansion), at most six calls per run, within a time and token budget. Each request is a structured action that code validates.",
        )
    )
    add(
        (
            "p",
            "**Why it matters.** The hardest cases need extra facts, and a model is good at deciding which fact to fetch next.",
        )
    )
    add(
        (
            "p",
            "**What it never does.** It never sees raw page or message text, only structured evidence. It never sets or lowers a score. It cannot be given orders by a page: a provenance rule rejects any address or domain argument that is not the input, a hop in its redirect chain, or derived from those, and the attempt itself is recorded as risk evidence. Its measured behaviour (tool calls, forbidden calls, label changes) is in section 8.",
        )
    )
    add(("h2", "4.5 The deterministic arbiter"))
    add(
        (
            "p",
            "**What it does.** Applies hard rules first, then computes a score: it starts from the classifier probability and adds or subtracts fixed, weighted pieces of evidence. The result falls into one of three bands. Thresholds are fitted on the validation split only, never on the test split.",
        )
    )
    add(
        (
            "table",
            ["Rule", "In plain words", "Effect"],
            [
                [
                    "H1",
                    "Claims a known brand, asks for credentials or payment, not on that brand's verified domain (judged from page signals, never from an AI claim)",
                    "Dangerous",
                ],
                ["H2", "Fresh hit on a known-bad feed", "Dangerous"],
                [
                    "H3",
                    "Domain is on a brand's verified official list and nothing abuses it",
                    'Never worse than "no warning signs"',
                ],
                ["H4", "Page sends typed credentials to a messaging bot or webhook relay", "Dangerous"],
                [
                    "H5",
                    "A message or email contains a link that is dangerous or suspicious",
                    "At least as severe as its worst link",
                ],
                [
                    "H6",
                    "Message asks for an OTP or a remote-access app while impersonating an authority or bank",
                    "At least suspicious",
                ],
            ],
            [0.7, 4.3, 1.7],
        )
    )
    add(
        (
            "p",
            "**Why it matters.** The same input gives the same result, every reason can be traced to evidence, and a manipulated model cannot change the outcome.",
        )
    )
    add(
        (
            "p",
            '**What it never does.** It never takes a score from a language model. An incomplete check is never presented as "no warning signs".',
        )
    )
    add(("h2", "4.6 The verdict and its reasons"))
    add(
        (
            "table",
            ["Verdict", "In Arabic", "What it means"],
            [
                ["Dangerous", "خطِر", "Strong signs of a scam. Do not open it."],
                ["Suspicious", "مشبوه", "Something does not add up, or we could not finish every check. Take care."],
                [
                    "No warning signs found",
                    "لم نجد علامات تحذير",
                    "We looked and found nothing wrong. This is not a guarantee; stay careful.",
                ],
            ],
            [1.8, 1.6, 3.3],
        )
    )
    add(
        (
            "p",
            "Reasons are fixed, natively written templates in Arabic and English. Each reason cites evidence identifiers, so there is no free-written AI text in the user-facing verdict. Each answer also says what to do now and what to do if the user already clicked or entered details. **The lowest verdict never certifies a link as harmless, because nobody can promise that.** The product never asks for personal, banking or ID details.",
        )
    )
    add(("h2", "4.7 Other inputs: messages, emails and pictures"))
    add(
        (
            "ul",
            [
                "**Message:** text is normalised (Arabic and Arabizi), rule features are read (urgency, secrecy, OTP request, payment, authority, prize, delivery fee, fine and others), and it is compared with known scam scripts using embeddings. A quarantined extractor pulls out links, and each one goes through the full link pipeline as a child check. A message with no link is judged on its wording: an intent classifier fitted on training data, with rule floors, reads the scam script itself (section 8 gives its recall and its false-alarm rate on a small synthetic set).",
                "**Email:** parsed locally with a size cap and no remote fetch. Checks include sender authentication results, header mismatches, link text against the real target, QR codes in images, and attachment type and hash only.",
                "**Picture or QR poster:** the file type is verified by its first bytes, a QR code is decoded, and text is read by a quarantined vision model. Extracted links and text go through the link and message pipelines.",
                "**Where you can see the work:** the campaign board has an explainer of what a campaign is; the public read-only History (until SSO) lists every check and every incident with its step-by-step trace; the results page shows each measured figure with a REAL or SYNTHETIC badge; a Grafana model-quality dashboard and Arize Phoenix traces (metadata only) show the models at work. Approving or rejecting a draft action stays with the operator. Verdicts read «خطِر», «مريب» and «لم نجد علامات تحذير», and a claimed brand is shown by its display name.",
            ],
        )
    )
    add(("pb",))

    # ── 5 Agents ───────────────────────────────────────────────────────────────────────────────
    add(("h1", "5. The two AI agents"))
    add(
        ("p", "Colour key in the diagrams: **teal** is fixed code, **blue** is an AI model, **amber** is a human gate.")
    )
    add(("h2", "5.1 The Investigator: a bounded state machine with checked tools"))
    add(
        (
            "p",
            "The Investigator is an explicit state machine, not a free-running agent. It can only move plan, act, observe, decide, done. Each step it emits one structured action, validated against a typed schema (`contracts/tools.schema.json`). Guardrails:",
        )
    )
    add(
        (
            "ul",
            [
                "**Dual-model separation:** untrusted text reaches only a quarantined extractor that has no tools and answers in a strict schema.",
                "**Spotlighting:** untrusted text is masked for personal data, wrapped in random delimiters and marked line by line before any model sees it. Instruction-like text is never followed; it is counted as risk.",
                "**Bounded, typed tools:** at most six calls, a time budget and a token budget.",
                "**Provenance check:** a tool argument must come from the case itself, not from the page.",
                "**The arbiter is code:** the investigator adds evidence only.",
            ],
        )
    )
    add(
        (
            "img",
            "investigator-simple",
            "Flow diagram of the Investigator: input arrives, a reader with no tools reads page text, the model plans one look-up, code checks the request, the tool runs and its result is added as evidence, the model decides to stop or continue within limits, and the arbiter scores.",
            "Figure 4. The Investigator, step by step.",
            6.4,
        )
    )
    add(
        (
            "img",
            "investigator-detailed",
            "Detailed diagram of the Investigator showing quarantined text, the bounded investigator loop with typed tools, the deterministic arbiter that models cannot override, and the verified explanation.",
            "Figure 5. Detailed view (from the repository documentation). The example uses the invented brand Falcon Demo Bank and reserved example addresses. Numbers in the picture are design limits, not measurements.",
            6.4,
        )
    )
    add(("h2", "5.2 The Sentinel: a LangGraph workflow with a Postgres checkpointer and human approval"))
    add(
        (
            "p",
            "The Sentinel listens to every finished check as an event on a Redis stream, with at-least-once delivery and idempotent handlers. Plain deterministic code correlates events by page fingerprint, brand, domain pattern, hosting details, certificate issuer and time window. Five unit-tested rules (R1 campaign, R2 kit reuse, R3 report burst, R4 reputation flip, R5 quality) decide what counts as an incident, so incident counts are reproducible with the AI model switched off.",
        )
    )
    add(
        (
            "p",
            "Triage is a LangGraph state graph (enrich, compare, assess, summarise, propose, act) with a **Postgres checkpointer**, one thread per incident, retries per node and a fixed step, token and time budget. Internal actions run automatically and are reversible. External actions, such as a takedown or police report draft, stop at a LangGraph `interrupt()` and wait for an operator. The graph resumes from its checkpoint when the operator decides, even after a restart. If the AI model is unavailable, a template summary is used and the approval step is still reached.",
        )
    )
    add(
        (
            "img",
            "sentinel-simple",
            "Flow diagram of the Sentinel: listen to events, correlate, rules open an incident, triage with LangGraph, internal actions, draft external actions, then a human approves or rejects. Every action is recorded in an audit log.",
            "Figure 6. The Sentinel, step by step.",
            6.4,
        )
    )
    add(
        (
            "img",
            "sentinel-detailed",
            "Detailed diagram of the Sentinel pipeline: listen, correlate, trigger rules R1 to R5, triage nodes, internal actions that run automatically, external drafts that wait at an interrupt for an operator, and an append-only audit log.",
            "Figure 7. Detailed view (from the repository documentation). Numbers in the picture are design limits, not measurements.",
            6.4,
        )
    )
    add(
        (
            "p",
            "The Sentinel only reads the checks people send it; it does not yet scan the internet for new domains by itself. It cannot edit rules, thresholds or scoring.",
        )
    )
    add(("pb",))

    # ── 6 Security ─────────────────────────────────────────────────────────────────────────────
    add(("h1", "6. Security and protection by design"))
    add(
        (
            "p",
            "Falcon Lens opens pages made by criminals, so it is built to be attacked. The full STRIDE analysis is in `docs/THREAT_MODEL.md`.",
        )
    )
    add(
        (
            "table",
            ["Risk", "How it is handled"],
            [
                [
                    "A malicious page attacks the checker",
                    "The sandbox is a separate service on internal-only networks. Its only peers are the egress proxy and the worker control channel. Every visit uses a fresh browser context, with downloads blocked, and redirect, size and time limits. It returns features only.",
                ],
                [
                    "Server-side request forgery (SSRF): tricking the checker into reaching internal systems",
                    "Own DNS resolution; private, loopback, link-local, cloud-metadata and mapped addresses are blocked; the resolved address is pinned for the connection; every redirect is re-checked. The egress proxy applies the same guard as a second layer and allows only the standard web ports.",
                ],
                [
                    "Prompt injection: a page tells the AI what to do",
                    "Spotlighting, a quarantined extractor with no tools, structured evidence only, a provenance check on tool arguments, and a rule that the arbiter alone sets the score. Instruction-like text counts as risk evidence.",
                ],
                [
                    "Cross-site scripting (XSS) on the board",
                    "Every address is shown defanged so it cannot be tapped by accident; strict content security policy; a browser test runs hostile strings through the result page.",
                ],
                [
                    "Stolen or abused keys",
                    "API keys are stored only as argon2id hashes, scoped (check, read, intel, operator) and rate-limited per key. The public sandbox key can only submit checks. The MCP service key can never approve an action or export intelligence. Webhooks are signed with a timestamp and a replay window.",
                ],
                [
                    "Denial of an action",
                    "Every keyed call and every Sentinel action is written to an append-only audit log; the application role cannot update or delete it.",
                ],
                [
                    "Over-claiming",
                    "No link is ever declared harmless. A degraded check is never shown as clear. Every number comes from an artifact. Replayed or synthetic data is labelled.",
                ],
                ["Actions that leave the system", "Always held for a human operator's approval."],
            ],
            [2.2, 4.5],
        )
    )
    add(
        (
            "p",
            "Defensive-only rules: the project never registers look-alike domains, never hosts a page imitating a real organisation, never messages real people, never submits forms on suspicious pages, and keeps live phishing addresses, page snapshots and logos out of the public repository. Test pages use only the invented brand Falcon Demo Bank and carry a visible test-fixture label.",
        )
    )

    # ── 7 Privacy ──────────────────────────────────────────────────────────────────────────────
    add(("h1", "7. Privacy and data sovereignty"))
    add(
        (
            "ul",
            [
                "**It asks for nothing personal:** no name, bank details or ID.",
                "**It keeps very little:** a hash of what was checked, a defanged copy of each link, the evidence and the verdict. A message or email body is not stored unless the user chooses to report it.",
                "**It masks sensitive details** (UAE phone numbers, Emirates ID, card numbers checked by the Luhn rule, emails, IBANs) before any text reaches a cloud model. Logs escape control characters and carry no message bodies.",
                "**Cloud mode:** masked, delimited text goes to the Anthropic API for extraction and investigation. Nothing else leaves the machine except look-ups (domain registration, certificate logs, feeds), which carry domain names only.",
                "**Sovereign mode** (`FL_SOVEREIGN_MODE=true`): every model call goes to a local Ollama model, so no content leaves the machine. Look-ups for domain registration and certificates still go out in this mode and carry domain names only. With no cloud key set, the system behaves the same way.",
                "**Not yet automated:** a retention policy (keep verdicts for a limited time, then aggregate) is planned but is not automated. The audit log is append-only. Snapshots stay local.",
            ],
        )
    )
    add(("p", "This is a description of data handling, not a legal compliance claim."))

    # ── 8 Results ──────────────────────────────────────────────────────────────────────────────
    add(("h1", "8. Results"))
    add(
        (
            "p",
            f"Every figure comes from published evaluation artifacts: `{a.main_name}` (offline classifier and arbiter) and `{a.fp_name}` (live false-alarm run). A script copies the values; none is typed by hand. A likely range (a bootstrap confidence interval, shown as ci95) is given because the sets are small, so a wide range means the figure could move as more items are tested.",
        )
    )
    add(("h2", "8.1 What was measured: the address-level classifier and arbiter, offline"))
    add(
        (
            "p",
            f"Scope, in the artifact's own words: “{a.main.get('scope', '')}”. The **test** set was frozen and never used for tuning; the **validation** set was used to fit the thresholds, so test is the fairer measure.",
        )
    )
    rows = []
    for key, label in (
        ("recall", "Recall"),
        ("precision", "Precision"),
        ("f1", "F1"),
        ("fpr", "False-alarm rate (FPR)"),
        ("pr_auc", "PR-AUC"),
        ("ece", "Calibration error (ECE)"),
    ):
        rows.append(
            [
                label,
                f"{a.pct('test.' + key)} ({a.ci('test.' + key)})",
                f"{a.pct('val.' + key)} ({a.ci('val.' + key)})",
                METRIC_PLAIN[key],
            ]
        )
    rows.append(["Set size (items)", a.raw("test.n"), a.raw("val.n"), "Small sets; read the ranges."])
    rows.append(
        [
            "Official sites wrongly marked dangerous",
            a.raw("test.official_false_dangerous"),
            a.raw("val.official_false_dangerous"),
            "Target: zero.",
        ]
    )
    add(("table", ["Metric", "Test (held out)", "Validation", "In plain words"], rows, [1.5, 1.6, 1.6, 2.0]))
    add(("h2", "8.2 Message path (synthetic templates)"))
    add(
        (
            "p",
            f'The message path is checked with synthetic template messages, which are labelled as synthetic in the repository, so this tests the plumbing and not real scam wording. On the test split ({a.raw("test.message_path.n")} items) recall is {a.pct("test.message_path.recall")} ({a.ci("test.message_path.recall")}) and the false-alarm rate is {a.pct("test.message_path.fpr")} ({a.ci("test.message_path.fpr")}). The artifact also records a recall of {a.raw("test.message_path.dangerous_recall")} for the stricter "dangerous" verdict on this path. We show it rather than hide it: in this offline path, messages reach "suspicious" but are not rated "dangerous" on their own.',
        )
    )
    add(("h2", "8.3 Live false-alarm figure (full stack)"))
    assert a.fp is not None
    web = a.fp["by_serves_web"]["serves_web_page"]["false_positive_rate"]
    noweb = a.fp["by_serves_web"]["no_web_host"]["false_positive_rate"]
    add(
        (
            "p",
            f"{a.fp_n()} held-out legitimate sites were sent through the running stack end to end. **{a.fp_pct()}** were flagged suspicious or dangerous (ci95 {a.fp_ci()}). Our target is at most {fmt_pct(a.fp['target'], 0)}. Split by site type: sites that serve a web page {fmt_pct(web['value'])} ({fmt_pct(web['ci95'][0])} to {fmt_pct(web['ci95'][1])}); domains with no web host {fmt_pct(noweb['value'])} ({fmt_pct(noweb['ci95'][0])} to {fmt_pct(noweb['ci95'][1])}).",
        )
    )
    add(
        (
            "p",
            '**Why it is high, in plain words.** The sealed browser timed out on some sites, and some hosts did not resolve. Falcon Lens treats a page it could not open as "suspicious, we could not complete every check" instead of clearing it. That is the cautious choice, and it costs false alarms. Sandbox fixes were merged during the day and each later run is published, but the newest run is not the lowest one, so we claim no steady improvement.',
        )
    )
    ev = evidence()
    add(
        (
            "p",
            f"**History of the live run.** {ev.fp_history_line()}. Every run is kept in `evals/results/published/fp_regress/`; the newest is the figure above, whether or not it is the best.",
        )
    )
    add(("h2", "8.4 Other published results (all synthetic or fixture data, labelled as such)"))
    rt = ev.redteam_both()
    rows2 = []
    if rt:
        rows2.append(
            [
                "Red-team: injection and evasion on the shipped cascade",
                rt
                + ". Harmful means a lowered label, a dropped score, attacker text in the reasons, a forbidden tool call, a leaked canary or a pipeline error. Read the harmful count with the answered count: where the model did not answer, the deterministic layers alone were tested.",
                "synthetic fixtures",
            ]
        )
    for label, line, kind in (
        ("Scam messages that contain no link", ev.message_line(), "synthetic, single-author, supervisor-audited"),
        ("Brand-new look-alike pages", ev.brand_new_line(), "synthetic fixtures; no AI layer in this run"),
        ("Cost per check", ev.cost_line(), "fixtures"),
        ("Stability on repeat runs", ev.stability_line(), "fixtures"),
        ("Cloud versus local model route", ev.route_line(), "fixtures"),
        ("Explanation faithfulness", ev.faith_line(), "fixture verdicts"),
        ("AI Investigator layer (T3)", ev.t3_line(), "fixtures"),
        ("DSPy prompt optimisation", ev.dspy_line(), "synthetic replay data"),
        (
            "Fresh two-hundred-site live test, main set",
            ev.fresh_main_line(),
            "live sites and a feed; one run, one day; legitimate labels not hand-audited; the feed also supplied the phishing",
        ),
        (
            "Fresh test, hosts from a feed the stack does not query",
            ev.fresh_second_line(),
            "same single run; read this row for the model's own detection",
        ),
        ("Voice assistant benchmark", ev.voice_line(), "synthetic speech and noise, not real speakers; an upper bound"),
        (
            "Sovereign proof, local models only",
            ev.sovereign_line(),
            "one developer machine, invented fixtures; not a production deployment",
        ),
    ):
        if line:
            rows2.append([label, line[0].upper() + line[1:] + ".", kind])
    add(("table", ["Area", "Result", "Data"], rows2, [1.6, 3.6, 1.4]))
    add(("h2", "8.5 What is not yet evaluated"))
    names = {
        "arabic_clarity_human_rating": "A native reader's rating of the Arabic verdict text (the automated phone-fit checks ran; the human rating is pending)",
        "sandbox_phishing_page_recall": "Recall of the sealed-browser layer on labelled phishing pages (no labelled snapshots exist, and visiting live phishing pages is out of scope)",
    }
    add(("ul", [names.get(k, k) for k in a.not_evaluated]))
    add(
        (
            "p",
            "No figure is shown for these and none should be assumed. Earlier drafts listed red-team resistance, cost, stability, faithfulness, the Investigator layer, brand-new pages and the two model routes here. They are measured now and appear in the table of other published results above.",
        )
    )
    add(("pb",))

    # ── 9 Integration ──────────────────────────────────────────────────────────────────────────
    add(("h1", "9. Integration for authorities: ready to connect, not connected"))
    add(
        (
            "p",
            "Falcon Lens has **no** integration with Abu Dhabi Police or any agency, and implies no endorsement. The surfaces below show how a police app or internal agent could connect. None is wired to any agency system.",
        )
    )
    add(
        (
            "table",
            ["Surface", "What it is", "Authentication"],
            [
                [
                    "REST v1",
                    "Check endpoints for link, message, email and image; verdict stream (SSE); reports and feedback; campaigns and incidents; operator approve and reject. Contract in `contracts/openapi.yaml`.",
                    "API key, scoped",
                ],
                [
                    "MCP server",
                    "For AI assistants: `check_url`, `check_message`, `check_email`, `get_verdict`, `list_campaigns`, `list_incidents`, `get_incident`, `submit_report`. It uses a key limited to check and read, so MCP can never approve an action.",
                    "Bearer token",
                ],
                [
                    "STIX 2.1 export",
                    "Incident indicators as a standard threat-intelligence bundle, for intel-scope keys only.",
                    "Key with intel scope",
                ],
                [
                    "Signed webhooks",
                    "Campaign alerts pushed to configured targets, signed with HMAC-SHA256 and a timestamp.",
                    "Shared secret",
                ],
            ],
            [1.3, 4.0, 1.4],
        )
    )
    add(
        (
            "p",
            "Data crossing the boundary: in, a link, text, an email file or an image, and report or feedback as hashes; out, verdicts (addresses defanged), campaign cards and incidents with aggregate counts, and STIX indicators. Never raw page or message text, never reporters' personal data. Replayed or synthetic data carries a source label. Errors follow the standard problem-details format and never echo submitted content.",
        )
    )

    # ── 10 Limitations and roadmap ─────────────────────────────────────────────────────────────
    add(("h1", "10. Limitations and roadmap"))
    add(("h2", "10.1 Limitations today"))
    add(
        (
            "ul",
            [
                f"The live false-alarm rate ({a.fp_pct()}) is far above the target. Pages the sandbox cannot open are the main cause.",
                "The evaluation sets are small and from a single collection poll (no temporal cut), so the ranges are wide.",
                "The fresh two-hundred-site test is a single run on one day, its legitimate labels are not hand-audited, and its main phishing set came from a feed the stack also reads; the red-team and voice sets are synthetic.",
                "The prototype uses the OpenPhish community list, which allows research use only. A real deployment needs a licence. Other feeds are disabled until keys are available.",
                "The Sentinel reads only the checks people send; it does not scan for new look-alike domains on its own."
                if not shipped("hunter")
                else "The proactive hunter reads certificate logs and permutations only; search, ads and Maps coverage need keys that are not configured.",
                "Data retention is not automated.",
                "The Arabic strings are written natively, but a native-speaker review is still open.",
                "Nothing is connected to any police or government system.",
            ],
        )
    )
    add(("h2", "10.2 Roadmap (not shipped)"))
    add(
        (
            "ul",
            [
                "A native reader's rating of the Arabic text, sandbox recall on labelled phishing pages, and bringing the live false-alarm rate down to its target.",
                "Sign-in (SSO) to restrict the read-only History, which is public until then.",
                "Adopting DSPy-optimised prompts: the optimiser ran for every model role and none was adopted, because the gains are within noise.",
                or_planned("hunter", "Active discovery of new look-alike domains from certificate logs."),
                or_planned("evidence_pack", "A police evidence pack download."),
                or_planned("helpline_registry", "An official-number registry for fake helplines."),
                "Search, ads and Maps coverage once keys are configured.",
                "A licensed scam-list feed, and additional warning lists once keys exist.",
                "Automated data retention, and a switch to turn off external look-ups in sovereign mode.",
                "A real connection to a police or security system, which needs an agreement with that organisation.",
            ],
        )
    )

    add(("h2", "10.3 Pilot optimisation plan: more data, better accuracy (planned, not shipped)"))
    add(
        (
            "p",
            "This is what we would do with a pilot and a data-sharing agreement. Every item is planned. No figure below is a result: today's numbers are in section 8, and any change would have to pass the same adoption gate before it is switched on.",
        )
    )
    dead = ev.fresh_dead_line()
    add(
        (
            "ul",
            [
                "**Catch scam pages before they die.** "
                + (f"In the fresh live test, {dead}. " if dead else "In the fresh live test, many listed pages were already offline. ")
                + "Plan: switch on continuous look-alike hunting (the built, off-by-default hunting job, with its kill switch and quotas); watch certificate-transparency logs once a licensed feed is in place; add search, ads and Maps hunting once API keys are provided (ready, needs a key); and take the first-visit snapshot sooner.",
                "**Fully local quality.** "
                + f"Sovereign proof today: {ev.sovereign_line() or 'not published'}. "
                + "Plan: schema-constrained JSON output for local models (Ollama structured outputs) and shorter prompts per model, so the Sentinel summary is written by the local model instead of the template fallback.",
                "**Learning from real data.** With labelled History and analyst feedback (approve or reject, false-positive reports) under the agreement: retrain the link and message classifiers and recalibrate the arbiter bands on temporal splits; re-run DSPy prompt optimisation on real labelled data for each route (today it ran for five roles on synthetic data and none was adopted); fine-tune the local models (LoRA or QLoRA on Qwen and Inkling) for Emirati Arabic scam language.",
                "**The gate stays.** A change is adopted only if the paired 95% interval of the improvement excludes zero and it adds no new false alarms. Every change goes through a shadow or canary route first, and we would publish a monthly evaluation report.",
                "**More brand coverage.** Add the authorities' official lists (official domains and helplines) to the brand registry: ready to connect, not connected.",
            ],
        )
    )

    # ── 11 Criteria map ────────────────────────────────────────────────────────────────────────
    add(("h1", "11. Criteria map: what we built and where the evidence is"))
    add(
        (
            "p",
            "Each of the five judging criteria, what the project does about it, and where the evidence is. Every figure is read from a published evaluation file; limits are stated beside the claim.",
        )
    )
    add(
        (
            "table",
            ["Criterion", "What we built", "Evidence", "Honest limit"],
            [
                [
                    "Detection accuracy",
                    "Cascade T0 to T3, deterministic arbiter, verified-official rule, redirects followed in the sealed browser, cloaking check.",
                    "Held-out test split and the fresh two-hundred-site live test (see the results chapter); red-team results (see the results chapter).",
                    f"Live false-alarm rate {a.fp_pct()} is far above target; sets are small; no sandbox recall on labelled pages yet.",
                ],
                [
                    "Early detection and coverage",
                    "Brand check for look-alike pages no list knows; scam-script recognition for messages without a link; look-alike hunter; official-number registry.",
                    "Brand-new-pages and message results (see the results chapter).",
                    "Hunter is off by default; search, ads and Maps need a key; certificate-log search is off.",
                ],
                [
                    "Explainability and actionability",
                    "Arabic reasons tied to evidence, per-check findings, a trace per check, police evidence pack with SHA-256 manifest, bilingual takedown draft, STIX.",
                    "Faithfulness result (see the results chapter).",
                    "Drafts wait for a human; nothing is sent to any authority.",
                ],
                [
                    "UAE relevance and innovation",
                    "Arabic first, UAE brand registry, Hey Falcon voice assistant in Arabic and English with an Emirati voice, official-number registry, campaign linking.",
                    "Voice benchmark and Arabic clarity results (see the results chapter).",
                    "Voice measured on synthetic clips; native-speaker review of the Arabic is still open.",
                ],
                [
                    "Feasibility and presentation",
                    "Runs on one machine; sovereign mode on local models; route selector; batch tool for hidden test sets; REST, MCP, STIX and signed webhooks.",
                    "Sovereign proof and route comparison (see the results chapter).",
                    "Ready to connect, not connected to any police or government system; scaling is proven on one machine only.",
                ],
            ],
            [1.2, 2.2, 1.9, 1.6],
        )
    )
    add(
        (
            "note",
            "Not affiliated",
            "Falcon Lens is independent, uses no police branding and is not endorsed by any authority. It never tells a user that a link is harmless; the lowest result is «لم نجد علامات تحذير» (No warning signs found), with a reminder to stay careful.",
        )
    )

    # ── 12 Glossary ────────────────────────────────────────────────────────────────────────────
    add(("h1", "12. Glossary in plain words"))
    glossary = [
        (
            "Phishing",
            "A fake message or page pretending to be a bank, courier or government service to steal passwords, card numbers or one-time codes.",
        ),
        ("Zero-day (brand-new) page", "A fake page so new that no warning list knows it."),
        ("Blocklist / feed", "A list of known bad addresses, published by a security community."),
        ("Cascade (T0 to T3)", "Checks in stages, cheap first. Each stage can finish the case."),
        ("Canonical form", "One standard way of writing an address, so the same link always looks the same."),
        (
            "Homograph / typo-squat / combo-squat",
            "Look-alike tricks: a similar-looking character, a small spelling change, or a brand name plus extra words.",
        ),
        ("RDAP", "A public service that tells you when a domain was registered."),
        (
            "Certificate log",
            "A public record of website security certificates; it shows how new a site's certificate is.",
        ),
        ("Classifier", "A small trained model that turns many address features into a probability."),
        ("Calibrated", "Its stated confidence matches how often it is right."),
        (
            "Sandbox",
            "A sealed browser in a closed room that can open a suspicious page without reaching anything else.",
        ),
        ("Egress proxy", "A filter every outgoing connection from the sandbox must pass through."),
        ("SSRF", "Server-side request forgery: tricking a server into contacting internal systems."),
        ("Cloaking", "A scam page that shows different content to different visitors."),
        ("Brand check", "Comparing which organisation a page claims to be with who owns its address."),
        ("Hard rule", "A fixed condition that forces a minimum or maximum verdict, whatever the score."),
        ("Arbiter", "The fixed code that alone sets the score and the verdict."),
        ("LLM", "Large language model: an AI that reads and writes text."),
        ("Prompt injection", "Text in a page or message trying to give orders to an AI."),
        ("Spotlighting", "Marking untrusted text so a model treats it as data, not instructions."),
        (
            "Quarantined extractor",
            "The only model that reads raw text; it has no tools and gives strict structured answers.",
        ),
        (
            "Provenance check",
            "Code that makes sure a tool is only pointed at addresses that came from the case itself.",
        ),
        ("Evidence", "A recorded finding with an identifier, a weight and a source."),
        ("Defanged", "An address written so it cannot be clicked, for example hxxp and [.]."),
        ("Campaign / incident", "Many related fake pages or messages; the record the Sentinel keeps about them."),
        ("LangGraph", "A framework for long-running agent workflows that can pause and resume."),
        ("Checkpointer", "Saved workflow state in the database, so a paused workflow survives a restart."),
        ("Interrupt", "A pause in the workflow until a person decides."),
        ("Audit log", "An append-only record of who did what."),
        ("Takedown", "A request to a host to remove a fake page."),
        ("API / REST", "A doorway that lets another program ask Falcon Lens to check something."),
        ("MCP", "Model Context Protocol: a doorway made for AI assistants."),
        ("STIX", "A standard format for sharing threat information."),
        ("Webhook", "An automatic message one system sends to another when something happens."),
        ("Sovereign mode", "Every AI call runs on local machines, so no content leaves."),
        (
            "Recall / precision / FPR",
            "The share of scams caught / of flags that were right / of genuine items wrongly flagged.",
        ),
        ("Confidence interval (ci95)", "The likely range of a figure if the test were repeated."),
        ("Held-out set", "Items set aside and never used for tuning."),
        ("PWA", "A web app that can be installed on a phone home screen."),
    ]
    add(("table", ["Term", "Meaning"], [[t, m] for t, m in glossary], [2.0, 4.7]))

    # ── 12 Tools and team ──────────────────────────────────────────────────────────────────────
    add(("h1", "13. Tools used"))
    add(("p", "Generated from the lockfiles and the compose file, so it lists only what the shipped code uses."))
    add(("table", ["Category", "Tools"], [[cat, ", ".join(items)] for cat, items in tools_by_category()], [1.8, 4.9]))
    add(("h1", "14. Team"))
    add(("ul", ["Mohamed Atef (Team leader)", "Abdulrahman Alseiari", "MokhmadSalakh Salamov"]))
    add(
        (
            "p",
            "Falcon Lens is open source under the Apache licence. Repository and the technical documents referenced here are in the public repository.",
        )
    )
    return b
