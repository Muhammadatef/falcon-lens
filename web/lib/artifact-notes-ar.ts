/**
 * Formal Arabic for every caveat / provenance / separation note published inside the bundled eval artifacts
 * (web/lib/*.generated.json). Keyed by the exact English text the artifact carries. Numbers are kept exactly.
 * tests/unit/artifact-notes.test.ts fails when a bundled note has no entry here.
 */
export const AR_NOTES: Record<string, string> = {
  // results-extra: realSynthetic, messageText, redteam, extractor
  "real (manifest items) and synthetic (Falcon Demo Bank fixtures), reported side by side":
    "عناصر حقيقية (من قائمة المجموعة المجمدة) وعناصر اصطناعية (نماذج «بنك الصقر التجريبي»)، تُعرض جنباً إلى جنب.",
  "real and synthetic numbers are never pooled; no model or threshold was fitted or tuned on any of these items":
    "لا تُجمع الأرقام الحقيقية مع الاصطناعية، ولم يُدرَّب أي نموذج ولم تُضبط أي عتبة على أي من هذه العناصر.",
  "The .test top-level domain itself raises the URL-only prior, so benign .test fixtures are flagged more often than benign real sites; read this FPR as an upper-bound artifact of reserved hosts, not as a field FPR.":
    "امتداد النطاق .test نفسه يرفع التقدير المبدئي المبني على العنوان وحده، فتُوسَم نماذج الاختبار غير الاحتيالية بامتداد .test أكثر من المواقع الحقيقية غير الاحتيالية. تُقرأ نسبة الإنذار الخاطئ هنا على أنها حدّ أعلى ناتج عن النطاقات المحجوزة، لا نسبة ميدانية.",
  "synthetic, single-author, supervisor-audited 2026-11-23 (reviews/PR-88.md)":
    "اصطناعية، كتبها مؤلف واحد ودقّقها المشرف بتاريخ 2026-11-23 (reviews/PR-88.md).",
  "synthetic fixtures (Falcon Demo Bank, reserved hosts); not real phishing":
    "نماذج اختبار اصطناعية («بنك الصقر التجريبي»، نطاقات محجوزة)، وليست احتيالاً حقيقياً.",
  "synthetic fixtures (Falcon Demo Bank, .test hosts); offline sandbox and network substitutes":
    "نماذج اختبار اصطناعية («بنك الصقر التجريبي»، نطاقات .test)، مع بدائل دون اتصال لبيئة العزل والشبكة.",
  // eval-areas
  "real (val/test URL items, offline) + synthetic (fixture verdicts, replayed incidents), reported apart":
    "عناصر حقيقية (روابط التحقق والاختبار، دون اتصال) وعناصر اصطناعية (أحكام نماذج الاختبار وحوادث أُعيد تشغيلها)، تُعرض منفصلة.",
  "synthetic fixtures (Falcon Demo Bank, .test hosts), offline substitutes for sandbox and network":
    "نماذج اختبار اصطناعية («بنك الصقر التجريبي»، نطاقات .test)، ببدائل دون اتصال لبيئة العزل والشبكة.",
  "fixture-backed renderer, stub DNS, no network signals; the local model shares the GPU with other jobs, so timeouts are possible and are counted, not hidden.":
    "عارض مستند إلى نماذج اختبار، وخدمة أسماء نطاقات بديلة، ودون إشارات شبكية. يتشارك النموذج المحلي وحدة المعالجة الرسومية مع مهام أخرى، فقد تحدث مهلات تُحتسب ولا تُخفى.",
  "synthetic fixtures; cost depends on prompt sizes of this corpus (short pages and messages)":
    "نماذج اختبار اصطناعية؛ تعتمد الكلفة على أحجام المطالبات في هذه المجموعة (صفحات ورسائل قصيرة).",
  "real (held-out legit domains, recorded fp_regress runs) and synthetic (fixtures), kept apart":
    "عناصر حقيقية (نطاقات مشروعة محجوزة وتشغيلات fp_regress المسجّلة) وعناصر اصطناعية (نماذج اختبار)، تُعرض منفصلة.",
  "synthetic (invented Falcon Demo Bank lookalikes on .test hosts generated 2026-11-23); fixture-backed renderer":
    "اصطناعية (صفحات «بنك الصقر التجريبي» المخترَعة على نطاقات .test، وُلّدت بتاريخ 2026-11-23)، مع عارض مستند إلى نماذج اختبار.",
  ".test hosts raise the URL-only prior (every .test page, including benign ones, is warned at T1); read warning rates together with the benign-control row, and treat 'dangerous' (H1) as the discriminating figure":
    "نطاقات .test ترفع التقدير المبدئي المبني على العنوان وحده (كل صفحة .test، حتى غير الاحتيالية، يُنبَّه عليها في الطبقة T1). تُقرأ نسب التنبيه مع صف الضبط غير الاحتيالي، ويُعدّ «خطِر» (H1) هو الرقم المميِّز.",
  "synthetic fixtures (Falcon Demo Bank / invented club pages, .test hosts); offline tool backends":
    "نماذج اختبار اصطناعية («بنك الصقر التجريبي» وصفحات نوادٍ مخترَعة، نطاقات .test)، مع أدوات تعمل دون اتصال.",
  "Synthetic, link-free messages (Falcon Demo Bank and generic roles). Recall/FPR with Wilson 95% intervals; small n means wide intervals. Test is evaluated once per build; report-only (not in evals/baseline.json).":
    "رسائل اصطناعية خالية من الروابط («بنك الصقر التجريبي» وأدوار عامة). الاستدعاء ونسبة الإنذار الخاطئ بنطاقات ثقة 95% بطريقة ويلسون؛ قلة الأمثلة تعني نطاقات واسعة. يُقيَّم الاختبار مرة واحدة لكل إصدار، وهو للإبلاغ فقط (ليس في evals/baseline.json).",
  "0/113 harmful at extended local-model deadlines (model answered 91/113; 0 failed calls). At production deadlines the model answered 89/113 (27 failed calls) with 0 harmful. Never quote the harmful count without the answered count.":
    "0 من 113 ضارّة عند المهل الممتدة للنموذج المحلي (أجاب النموذج عن 91 من 113؛ 0 نداءات فاشلة). وعند المهل الإنتاجية أجاب عن 89 من 113 (27 نداءً فاشلاً) مع 0 ضارّة. لا يُذكر عدد الضارّة دون عدد الحالات المُجاب عنها.",
  "shipped Arabic catalog templates (not model output)": "قوالب الكتالوج العربي المُشحونة (وليست مخرجات نموذج).",
  "fitted on validation only": "ضُبط على مجموعة التحقق وحدها.",
};
