import type { AgentTrace, TraceStep } from "./agent-trace";
import { DEMO_INCIDENT } from "./demo";

/* Synthetic Sentinel agent trace for DEMO_INCIDENT (?demo=1). Shape: contracts/agent_trace.schema.json. */
const demoStep = (seq: number, node: TraceStep["node"], patch: Partial<TraceStep>): TraceStep => ({
  seq, node, started_at: `2026-11-22T10:11:${String(seq * 3).padStart(2, "0")}Z`, duration_ms: 40, status: "completed",
  summary_en: "", summary_ar: "", tools: [], llm: null, budget: { steps_used: seq, tokens_used: 0, elapsed_ms: seq * 300 }, error_code: null, ...patch,
});
const demoLlm = (tokens_in: number, tokens_out: number) => ({ route: "local" as const, model: "demo-model", tokens_in, tokens_out, cost_usd: 0, repaired: false, fallback_template: false });
export const DEMO_TRACE: AgentTrace = {
  incident_id: DEMO_INCIDENT.incident_id,
  thread_id: DEMO_INCIDENT.incident_id,
  runs: [{
    run_id: "run_demo0000000000a1", started_at: "2026-11-22T10:11:03Z", finished_at: "2026-11-22T10:12:00Z", status: "interrupted",
    interrupt: { action_id: "act_takedown_001", tool: "draft_takedown", waiting_since: "2026-11-22T10:12:00Z", pending_count: 1 },
    steps: [
      demoStep(1, "enrich", { duration_ms: 212, summary_en: "Gathered context with 4 read tools: 4 indicators, 9 evidence ids.", summary_ar: "جُمع السياق بـ 4 أدوات قراءة: 4 مؤشرات و9 معرّف دليل.", tools: ["search_verdicts", "find_related_domains", "get_past_incidents", "feed_status"].map((name) => ({ name, mode: "read" as const, status: "ok" as const, evidence_ids: [], duration_ms: 40 })) }),
      demoStep(2, "compare", { summary_en: "Compared indicators: 2 related domains, 0 past incidents. Deterministic, no model.", summary_ar: "قورنت المؤشرات: 2 نطاقات مرتبطة و0 حوادث سابقة. بلا نموذج." }),
      demoStep(3, "assess", { duration_ms: 1450, summary_en: "The severity reason was written by the model and checked against the evidence.", summary_ar: "كتب النموذج سبب الخطورة وجرى التحقق منه مقابل الأدلة.", llm: demoLlm(820, 140), tools: [{ name: "upsert_incident", mode: "internal_auto", status: "ok", evidence_ids: ["rule:R1"], duration_ms: 12 }] }),
      demoStep(4, "summarise", { duration_ms: 1810, summary_en: "The summary was written from a template (model output not accepted).", summary_ar: "كُتب الملخص من قالب (لم يُقبل مخرج النموذج).", llm: { ...demoLlm(0, 0), route: "none", fallback_template: true }, tools: [{ name: "upsert_incident", mode: "internal_auto", status: "ok", evidence_ids: ["rule:R1"], duration_ms: 11 }] }),
      demoStep(5, "propose", { duration_ms: 1320, summary_en: "Proposed 5 actions; 0 model proposals were rejected by the validator.", summary_ar: "اقتُرحت 5 إجراءات، ورفض المدقق 0 من مقترحات النموذج.", llm: demoLlm(910, 220) }),
      demoStep(6, "act", { duration_ms: 305, status: "interrupted", summary_en: "Waiting for a human to decide on 1 external draft(s). Nothing is sent before approval.", summary_ar: "بانتظار قرار بشري على 1 مسودة خارجية. لا يُرسل شيء قبل الموافقة.", tools: [
        { name: "block_indicator", mode: "internal_auto", status: "ok", evidence_ids: ["ev_brand0own1"], duration_ms: 18 },
        { name: "update_campaign_board", mode: "internal_auto", status: "ok", evidence_ids: [], duration_ms: 9 },
        { name: "draft_takedown", mode: "external_draft", status: "ok", evidence_ids: ["ev_brand0own1"], duration_ms: 6 },
      ] }),
    ],
  }],
};
