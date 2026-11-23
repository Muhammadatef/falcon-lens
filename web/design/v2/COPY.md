# Web v2 copy (generated from `copy.json` by `build-mockups.mjs`; do not edit by hand)

`cap` = capability flag that must be true before the string appears without an "In progress" badge.

| Key | English | العربية | cap |
|---|---|---|---|
| `nav.check` | Check | افحص |  |
| `nav.agents` | AI agents | الوكيلان الذكيان |  |
| `nav.results` | Results | النتائج |  |
| `nav.authorities` | For authorities | للجهات المختصة |  |
| `nav.docs` | Docs | التوثيق |  |
| `nav.privacy` | Privacy | الخصوصية |  |
| `nav.menu` | Menu | القائمة |  |
| `nav.live` | Live campaigns | الحملات المباشرة |  |
| `nav.ops` | Incident board | لوحة الحوادث |  |
| `cap.live` | Live | يعمل الآن |  |
| `cap.progress` | In progress | قيد الإنجاز |  |
| `demo.badge` | DEMO DATA | بيانات تجريبية |  |
| `demo.ribbon` | DEMO DATA · not a real check | بيانات تجريبية · ليست فحصاً حقيقياً |  |
| `agent.inv.name` | The Investigator | المحقّق |  |
| `agent.sen.name` | The Sentinel | الحارس |  |
| `agent.kind` | AI agent | وكيل ذكاء اصطناعي |  |
| `agent.inv.role` | Checks what you send | يفحص ما ترسله |  |
| `agent.sen.role` | Watches around the clock | يرصد على مدار الساعة | `sentinel_agent` |
| `agent.inv.aistep` | AI second look for unclear cases | نظرة ثانية بالذكاء الاصطناعي للحالات الغامضة | `investigator` |
| `home.eyebrow` | AI agents against scams | وكيلان ذكيان في مواجهة الاحتيال |  |
| `home.title` | Two AI agents between you and the scam. | وكيلا ذكاء اصطناعي بينك وبين المحتال. |  |
| `home.sub` | Paste a suspicious link or message. The Investigator checks it in seconds and tells you plainly what it found and what to do. The Sentinel watches around the clock for the campaign behind it. | الصق الرابط أو الرسالة المشبوهة. «المحقّق» يفحصها في ثوانٍ ويبيّن لك بوضوح ما وجده وما عليك فعله. و«الحارس» يرصد على مدار الساعة الحملة التي تقف وراءها. | `sentinel_agent` |
| `home.sub.phone` | Paste it here. The Investigator tells you in seconds what it found and what to do. | الصقه هنا، ويخبرك «المحقّق» في ثوانٍ بما وجده وما عليك فعله. |  |
| `home.kind.label` | What do you want to check | نوع ما تريد فحصه |  |
| `home.kind.url` | Link | رابط |  |
| `home.kind.message` | Message | رسالة | `message_check` |
| `home.kind.email` | Email | بريد | `email_check` |
| `home.kind.image` | Image / QR | صورة / QR | `image_check` |
| `home.input.label` | Paste the suspicious link | الصق الرابط المريب |  |
| `home.input.hint` | Don't open the link. Just copy it and paste it here. | لا تفتح الرابط. انسخه والصقه هنا فقط. |  |
| `home.cta` | Check now | افحص الآن |  |
| `home.promise` | We never ask for personal, banking or ID details. | لا نطلب منك أبداً بيانات شخصية أو مصرفية أو رقم هوية. |  |
| `ticker.label` | The Sentinel is watching | «الحارس» يرصد الآن | `sentinel_agent` |
| `ticker.count` | Active campaigns: {campaigns} · Linked checks: {checks} | حملات نشطة: {campaigns} · فحوص مرتبطة: {checks} |  |
| `ticker.latest` | Latest: | الأحدث: |  |
| `ticker.empty` | No active campaigns right now. | لا حملات نشطة الآن. |  |
| `ticker.offline` | The Sentinel feed is not connected. | بثّ «الحارس» غير متصل. |  |
| `ticker.cta` | Open the live board | افتح اللوحة المباشرة |  |
| `out.title` | What you get | ما الذي تحصل عليه |  |
| `out.1.title` | A clear answer in seconds | جواب واضح في ثوانٍ |  |
| `out.1.text` | One of three verdicts: dangerous, suspicious, or no warning signs found. | حكم من ثلاثة: خطِر، أو مريب، أو لم نجد علامات تحذير. |  |
| `out.2.title` | Reasons you can understand | أسباب تفهمها |  |
| `out.2.text` | Up to three plain reasons, each backed by evidence. | ثلاثة أسباب على الأكثر، بلغة بسيطة، ولكلٍّ منها دليل. |  |
| `out.3.title` | What to do next | ما عليك فعله |  |
| `out.3.text` | Clear steps, and the official channels to report it. | خطوات واضحة، وقنوات الإبلاغ الرسمية. |  |
| `out.4.title` | Your details stay yours | بياناتك تبقى لك |  |
| `out.4.text` | No sign-up. No personal, banking or ID details. | بلا تسجيل، وبلا بيانات شخصية أو مصرفية أو رقم هوية. |  |
| `meet.title` | Meet the two AI agents | تعرّف على الوكيلين الذكيين |  |
| `meet.inv.text` | Examines the link, visits the page in isolation so you don't have to, and explains what it found in plain language. | يدقّق في الرابط، ويزور الصفحة في بيئة معزولة بدلاً منك، ويشرح لك ما وجده بلغة واضحة. |  |
| `meet.sen.text` | Links similar scams into campaigns and prepares alerts and reports. Nothing leaves the system until a person approves. | يربط عمليات الاحتيال المتشابهة في حملات، ويُعدّ التنبيهات والبلاغات. ولا يخرج شيء من النظام قبل موافقة شخص مسؤول. | `sentinel_agent` |
| `meet.principle` | AI assists. Evidence decides. People approve. | الذكاء الاصطناعي يساعد، والأدلة تحسم، والإنسان يوافق. |  |
| `meet.cta` | How the AI agents protect you | كيف يحميك الوكيلان الذكيان |  |
| `proof.title` | Measured, not claimed | أرقام مقيسة، لا ادعاءات |  |
| `proof.lead` | Every number is read automatically from our published evaluation file. | كل رقم منقول آلياً من ملف التقييم المنشور. |  |
| `proof.recall` | Scam links caught | روابط احتيالية كُشفت |  |
| `proof.fpr` | Genuine links flagged by mistake | روابط غير احتيالية نُبّه عليها خطأً |  |
| `proof.official` | Official sites wrongly called dangerous | مواقع رسمية صُنّفت خطأً بأنها خطِرة |  |
| `proof.ci` | 95% range | نطاق الثقة 95% |  |
| `proof.scope` | Offline test on real links held back from training (count: {test.n}). Address-analysis stage only. | اختبار دون اتصال على روابط حقيقية محجوبة عن التدريب (العدد: {test.n}). مرحلة تحليل العنوان فقط. |  |
| `proof.cta` | See all results | اعرض جميع النتائج |  |
| `proof.pending` | Evaluation in progress. No number is shown before it is published. | التقييم قيد الإنجاز. لا نعرض أي رقم قبل نشره. |  |
| `auth.band.title` | Ready to connect. Not connected. | جاهز للربط، وغير مربوط. |  |
| `auth.band.text` | Documented interfaces let authority systems request checks and receive campaign intelligence. No connection exists with any authority today. | واجهات موثّقة تتيح لأنظمة الجهات المختصة طلب الفحص وتلقّي معلومات الحملات. ولا يوجد اليوم أي ربط قائم مع أي جهة. |  |
| `auth.band.cta` | For authorities | للجهات المختصة |  |
| `foot.indep` | Falcon Lens is an independent entry in the ScamShield AI competition. It does not represent, is not affiliated with and is not endorsed by Abu Dhabi Police. | عدسة الصقر مشروع مستقل مشارك في مسابقة «ScamShield AI». لا يمثّل شرطة أبوظبي ولا يرتبط بها ولا يحمل تأييداً منها. |  |
| `check.title` | Check result | نتيجة الفحص |  |
| `check.new` | New check | فحص جديد |  |
| `check.url.note` | Shown disabled; it cannot be tapped. | عنوان معطَّل للعرض فقط، لا يمكن الضغط عليه. |  |
| `act.title` | The Investigator is checking your link… | «المحقّق» يفحص الرابط الآن… |  |
| `act.done` | The Investigator finished in {latency_s} s | أنهى «المحقّق» الفحص خلال {latency_s} ث |  |
| `act.step.known` | Comparing with reported scams | يقارنه ببلاغات الاحتيال المعروفة |  |
| `act.step.address` | Examining the address | يدقّق في العنوان |  |
| `act.step.visit` | Opening the page in isolation, so you don't have to | يفتح الصفحة في بيئة معزولة بدلاً منك |  |
| `act.step.ai` | AI second look (unclear cases only) | نظرة ثانية بالذكاء الاصطناعي (للحالات الغامضة فقط) | `investigator` |
| `act.st.done` | Done | اكتملت |  |
| `act.st.running` | Working… | جارية… |  |
| `act.st.pending` | Waiting | بالانتظار |  |
| `act.st.skipped` | Not needed | لم تكن لازمة |  |
| `act.prov.suspicious` | Suspicious signs so far · still checking | علامات مريبة حتى الآن · نواصل الفحص |  |
| `act.wait` | Don't tap the link until the check is complete. | لا تضغط على الرابط إلى أن يكتمل الفحص. |  |
| `act.sentinel` | The Sentinel compares this check with others to spot campaigns early. | «الحارس» يقارن هذا الفحص بغيره لكشف الحملات مبكراً. | `sentinel_agent` |
| `v.dangerous` | Dangerous | خطِر |  |
| `v.dangerous.sub` | Do not open this link or respond to it | لا تفتح هذا الرابط ولا تتجاوب معه |  |
| `v.suspicious` | Suspicious | مريب |  |
| `v.suspicious.sub` | Stop and verify before any step | توقّف وتحقق قبل أي خطوة |  |
| `v.nws` | No warning signs found | لم نجد علامات تحذير |  |
| `v.nws.sub` | This is not a guarantee. Stay careful. | هذا ليس ضماناً. ابقَ حذراً. |  |
| `res.imp` | Impersonates: | ينتحل اسم: |  |
| `res.why` | Why? | لماذا؟ |  |
| `res.now` | What to do now | ماذا تفعل الآن |  |
| `res.acted` | If you already tapped or entered details | إذا ضغطت على الرابط أو أدخلت بياناتك |  |
| `res.caution` | Stay careful | ابقَ حذراً |  |
| `res.report` | Report it | بلّغ |  |
| `res.report.lead` | Through Abu Dhabi Police official channels: | عبر القنوات الرسمية لشرطة أبوظبي: |  |
| `res.report.source` | Channels read from the official site on {retrieved_at}. Falcon Lens is independent and not affiliated with Abu Dhabi Police. | القنوات منقولة من الموقع الرسمي بتاريخ {retrieved_at}. عدسة الصقر مشروع مستقل غير تابع لشرطة أبوظبي. |  |
| `tech.toggle` | Technical details | تفاصيل تقنية |  |
| `tech.summary` | Evidence, rules, risk score and timings, for technical reviewers. | الأدلة والقواعد ودرجة الخطورة والتوقيتات، للمراجعين التقنيين. |  |
| `tech.docs` | How a verdict is reached (Docs) | كيف يصدر الحكم (التوثيق) |  |
| `agents.title` | How the AI agents protect you | كيف يحميك الوكيلان الذكيان |  |
| `agents.lead` | Two AI agents, two jobs: one answers you now, the other protects everyone after you. | وكيلان ذكيان ولكلٍّ مهمته: الأول يجيبك الآن، والثاني يحمي مَن بعدك. |  |
| `agents.inv.tag` | Answers you now | يجيبك الآن |  |
| `agents.inv.1.title` | It looks closely | ينظر بتمعّن |  |
| `agents.inv.1.text` | Compares the link with reported scams, examines the address and opens the page in an isolated browser. It types nothing and submits nothing. | يقارن الرابط ببلاغات الاحتيال، ويدقّق في العنوان، ويفتح الصفحة في متصفح معزول. لا يكتب شيئاً ولا يرسل شيئاً. |  |
| `agents.inv.2.title` | It weighs the evidence | يزن الأدلة |  |
| `agents.inv.2.text` | Every finding is a piece of evidence. Fixed rules weigh it, and an AI model takes a second look only when the case is unclear. | كل ما يجده دليل. قواعد ثابتة تزن الأدلة، ولا يُستعان بنموذج الذكاء الاصطناعي إلا في الحالات الغامضة. | `investigator` |
| `agents.inv.3.title` | It answers plainly | يجيب بوضوح |  |
| `agents.inv.3.text` | One verdict, up to three reasons and what to do now. It never gives any link a guarantee. | حكم واحد، وثلاثة أسباب على الأكثر، وما عليك فعله الآن. ولا يمنح أي رابط ضماناً. |  |
| `agents.sen.tag` | Protects everyone after you | يحمي مَن بعدك |  |
| `agents.sen.1.title` | It watches every check | يراقب كل فحص |  |
| `agents.sen.1.text` | Around the clock, without anyone asking. | على مدار الساعة، دون أن يطلب أحد. |  |
| `agents.sen.2.title` | It links the campaign | يربط خيوط الحملة |  |
| `agents.sen.2.text` | Similar scams are grouped, so a campaign is spotted early. | يجمع عمليات الاحتيال المتشابهة ليكشف الحملة في بدايتها. |  |
| `agents.sen.3.title` | It prepares, a person approves | يُعدّ، والإنسان يوافق |  |
| `agents.sen.3.text` | It drafts takedown requests and police reports. Nothing is sent outside until a responsible person approves. | يُعدّ مسودات طلبات الإزالة والبلاغات. ولا يُرسل شيء إلى الخارج قبل موافقة شخص مسؤول. |  |
| `agents.handoff` | Every check the Investigator completes becomes a signal for the Sentinel. | كل فحص يُتمّه «المحقّق» يصبح إشارة يلتقطها «الحارس». |  |
| `agents.promises.title` | Three commitments | ثلاثة التزامات |  |
| `agents.p1.title` | The AI never sets the score | الذكاء الاصطناعي لا يحدد الدرجة |  |
| `agents.p1.text` | A fixed, auditable arbiter issues the verdict from the evidence. | الحكم يصدره محكّم ثابت قابل للتدقيق، استناداً إلى الأدلة. |  |
| `agents.p2.title` | A person approves every outside action | كل إجراء خارجي بموافقة إنسان |  |
| `agents.p2.text` | The Sentinel prepares. It never sends by itself. | «الحارس» يُعدّ ولا يُرسل بنفسه. |  |
| `agents.p3.title` | Every reason traces to evidence | كل سبب يعود إلى دليل |  |
| `agents.p3.text` | Nothing is asserted without a recorded finding behind it. | لا يُذكر سبب دون دليل مسجَّل يسنده. |  |
| `agents.cta` | Try a check now | جرّب الفحص الآن |  |
| `agents.docs` | Technical architecture in Docs | البنية التقنية في التوثيق |  |
| `results.title` | What we measured | ما الذي قسناه |  |
| `results.lead` | Every number on this page is copied automatically from the published evaluation file. None is typed by hand. | كل رقم في هذه الصفحة منقول آلياً من ملف التقييم المنشور، ولا يُكتب يدوياً. |  |
| `results.recall.mean` | Of the scam links in the held-out test, this share was flagged. | نسبة الروابط الاحتيالية التي نُبّه عليها في الاختبار المحجوب. |  |
| `results.fpr.mean` | Of the genuine links in the test, this share was flagged by mistake. | نسبة الروابط غير الاحتيالية التي نُبّه عليها خطأً في الاختبار. |  |
| `results.official.mean` | Count of official sites in the test labelled dangerous. | عدد المواقع الرسمية التي صُنّفت خطِرة في الاختبار. |  |
| `results.all.title` | All measures | جميع المقاييس |  |
| `results.col.metric` | Measure | المقياس |  |
| `results.col.value` | Value | القيمة |  |
| `results.col.ci` | 95% range | نطاق الثقة 95% |  |
| `results.split.test` | Held-out test set | مجموعة الاختبار المحجوبة |  |
| `results.split.val` | Validation set | مجموعة التحقق |  |
| `results.n` | Examples: {n} | عدد الأمثلة: {n} |  |
| `results.scope.title` | What this covers | ما الذي يشمله القياس |  |
| `results.scope.text` | The address-analysis stage with the arbiter, offline, on real data only. The sample is small, so the ranges are wide. These results are not a guarantee against entirely new campaigns. | مرحلة تحليل العنوان مع المحكّم، دون اتصال بالشبكة، وعلى بيانات حقيقية فقط. العيّنة صغيرة ولذلك نطاقات الثقة عريضة. وهذه النتائج ليست ضماناً أمام حملات جديدة كلياً. |  |
| `results.ne.title` | Not measured yet | لم يُقَس بعد |  |
| `results.ne.lead` | We list what has no published measurement, rather than estimate it. | نذكر ما لم يُنشر له قياس بعد، بدلاً من تقديره. |  |
| `results.prov.title` | Where the numbers come from | مصدر الأرقام |  |
| `results.prov.artifact` | Evaluation file | ملف التقييم |  |
| `results.prov.date` | Created (UTC) | تاريخ الإنشاء (UTC) |  |
| `results.prov.dataset` | Dataset fingerprint | بصمة مجموعة البيانات |  |
| `results.docs` | Evaluation methodology in Docs | منهجية التقييم في التوثيق |  |
| `metric.precision` | Precision | الدقة (Precision) |  |
| `metric.recall` | Recall | الاستدعاء (Recall) |  |
| `metric.f1` | F1 | F1 |  |
| `metric.fpr` | False-positive rate | معدل الإنذار الخاطئ |  |
| `metric.pr_auc` | PR-AUC | PR-AUC |  |
| `metric.ece` | Calibration error (ECE) | خطأ المعايرة (ECE) |  |
| `ne.arabic_clarity` | Arabic clarity | وضوح العربية |  |
| `ne.cost_per_check_llm` | Cost per check | كلفة الفحص الواحد |  |
| `ne.faithfulness` | Faithfulness of reasons | أمانة الأسباب للأدلة |  |
| `ne.flip_rate_3_runs` | Verdict stability | ثبات الحكم |  |
| `ne.injection_attack_success_rate` | Prompt-injection resistance | مقاومة حقن التعليمات |  |
| `ne.llm_tier_T3` | AI second-look stage | مرحلة النظرة الثانية بالذكاء الاصطناعي |  |
| `ne.sandbox_tier_T2` | Isolated page-visit stage | مرحلة الزيارة المعزولة |  |
| `ne.zero_day` | Brand-new campaigns | الحملات الجديدة كلياً |  |
| `ne.synthetic` | Synthetic data | البيانات الاصطناعية |  |
| `ne.cloud_route` | Cloud model route | مسار النموذج السحابي |  |
| `ne.sovereign_route` | Sovereign model route | مسار النموذج السيادي |  |
| `docs.eyebrow` | For technical reviewers | للمراجعين التقنيين |  |
| `docs.title` | Docs | التوثيق |  |
| `docs.lead` | The technical detail behind every statement on this site: how it is built, how it is secured and how it is measured. | التفاصيل التقنية وراء كل ما يذكره هذا الموقع: كيف بُني، وكيف يُؤمَّن، وكيف يُقاس. |  |
| `docs.architecture.title` | Architecture | البنية |  |
| `docs.architecture.text` | Services, data flow and network isolation. | الخدمات ومسار البيانات وعزل الشبكات. |  |
| `docs.agents.title` | Agent patterns | أنماط الوكلاء |  |
| `docs.agents.text` | The Investigator's bounded loop, the Sentinel's workflow, tools and human gates. | حلقة «المحقّق» المحدودة، ومسار عمل «الحارس»، والأدوات ونقاط الموافقة البشرية. |  |
| `docs.cascade.title` | Cascade T0–T3 | طبقات الفحص T0–T3 |  |
| `docs.cascade.text` | Four tiers, fastest first; deeper only when needed. | أربع طبقات تبدأ بالأسرع، ولا تتعمق إلا عند الحاجة. |  |
| `docs.arbiter.title` | Arbiter and scoring | المحكّم واحتساب الدرجة |  |
| `docs.arbiter.text` | Features, weights, hard rules and verdict bands. | السمات والأوزان والقواعد الحاسمة ونطاقات الحكم. |  |
| `docs.security.title` | Security | الأمن |  |
| `docs.security.text` | Threat model, sandbox, prompt-injection defence and CSP. | نموذج التهديدات، والبيئة المعزولة، والتصدي لحقن التعليمات، وسياسة أمن المحتوى. | `injection_defence` |
| `docs.evals.title` | Evaluation methodology | منهجية التقييم |  |
| `docs.evals.text` | Datasets, splits, metrics and merge gates. | مجموعات البيانات وتقسيمها، والمقاييس، وبوابات الدمج. |  |
| `docs.integration.title` | Integration: API, MCP, STIX | الربط: API و MCP و STIX |  |
| `docs.integration.text` | REST v1, an MCP server and STIX 2.1 export. Ready to connect. | واجهة REST الإصدار 1، وخادم MCP، وتصدير STIX 2.1. جاهز للربط. |  |
| `docs.privacy.title` | Privacy engineering | هندسة الخصوصية |  |
| `docs.privacy.text` | Data minimisation, redaction, cloud and sovereign routes. | تقليل البيانات، والحجب، والمسار السحابي والمسار السيادي. |  |
| `docs.read` | Read | اقرأ |  |
| `docs.back` | Not technical? Start with how the AI agents protect you. | لست متخصصاً؟ ابدأ من: كيف يحميك الوكيلان الذكيان. |  |
