/**
 * Structure of the interactive architecture diagram (data only; the words live in lib/i18n-arch.ts).
 * Every node names the file in this repo that implements it (`repo`, checked to exist by tests/unit/arch-graph.test.ts)
 * and the capability flag whose Live / In progress badge it carries (lib/capabilities.ts). Content mirrors
 * packages/falcon_core/src/falcon_core/{cascade,agent,llm,tools,scoring}, services/*, contracts/ and ADR-001/002.
 */
import type { CapId } from "./capabilities";
import type { DocSlug } from "./docs-content";

export type NodeKind = "llm" | "code" | "gate" | "store" | "io";
export type GroupId = "entry" | "inv" | "sen" | "tools_inv" | "tools_sen" | "llm" | "obs" | "integ" | "biz_tools" | "biz_found";

export interface NodeDef {
  id: string;
  group: GroupId;
  kind: NodeKind;
  cap: CapId;
  /** Primary implementation file or directory, relative to the repo root. */
  repo: string;
  repoMore?: readonly string[];
  doc: DocSlug;
  /** The markdown file in docs/ that describes it. */
  docFile: string;
}

const CORE = "packages/falcon_core/src/falcon_core";
const SEN = "services/sentinel/src/falcon_sentinel";

export const NODES: readonly NodeDef[] = [
  // Entry
  { id: "clients", group: "entry", kind: "io", cap: "pwa", repo: "web/app/page.tsx", repoMore: ["extension"], doc: "architecture", docFile: "docs/ARCHITECTURE.md" },
  { id: "api", group: "entry", kind: "code", cap: "rest_api", repo: "services/api/src/falcon_api/app.py", repoMore: ["contracts/openapi.yaml"], doc: "integration", docFile: "docs/INTEGRATION.md" },

  // Entry: the voice path ("Hey Falcon"): browser microphone, local speech to text, intent, then the same check API
  { id: "voice_mic", group: "entry", kind: "io", cap: "pwa", repo: "web/components/VoiceAssistant.tsx", repoMore: ["web/app/api/voice/route.ts"], doc: "agents", docFile: "docs/PRIVACY.md" },
  { id: "voice_stt", group: "entry", kind: "code", cap: "rest_api", repo: "services/voice/src/falcon_voice/app.py", repoMore: ["services/api/src/falcon_api/voice.py"], doc: "agents", docFile: "docs/PRIVACY.md" },
  { id: "voice_intent", group: "entry", kind: "code", cap: "rest_api", repo: `${CORE}/voice/intent.py`, repoMore: ["services/api/src/falcon_api/voice.py"], doc: "agents", docFile: "docs/PRIVACY.md" },

  // Investigator: the check cascade
  { id: "t0", group: "inv", kind: "code", cap: "url_check", repo: `${CORE}/signals/cache.py`, repoMore: [`${CORE}/signals/reputation/mirror.py`, "data/brands.yaml"], doc: "cascade", docFile: "docs/ARCHITECTURE.md" },
  { id: "t1", group: "inv", kind: "code", cap: "t1_measured_model", repo: `${CORE}/scoring/t1_model.py`, repoMore: [`${CORE}/signals/url/lexical.py`, `${CORE}/signals/domain/rdap.py`], doc: "cascade", docFile: "docs/SCORING.md" },
  { id: "t2", group: "inv", kind: "code", cap: "brand_check", repo: "services/sandbox/src/falcon_sandbox/browser.py", repoMore: [`${CORE}/agent/extractor.py`, `${CORE}/signals/brands/registry.py`, "services/egress/src/falcon_egress/guard.py"], doc: "cascade", docFile: "docs/ARCHITECTURE.md" },
  { id: "t3", group: "inv", kind: "llm", cap: "investigator", repo: `${CORE}/agent/investigator.py`, repoMore: [`${CORE}/tools/registry.py`], doc: "agents", docFile: "docs/adr/ADR-001-cascade-arbiter.md" },
  { id: "arbiter", group: "inv", kind: "code", cap: "url_check", repo: `${CORE}/scoring/arbiter.py`, repoMore: [`${CORE}/scoring/hard_rules.py`, `${CORE}/scoring/params.yaml`], doc: "arbiter", docFile: "docs/SCORING.md" },
  { id: "verdict", group: "inv", kind: "llm", cap: "investigator", repo: `${CORE}/agent/responder.py`, repoMore: [`${CORE}/cascade/engine.py`, "contracts/verdict.schema.json"], doc: "cascade", docFile: "docs/CONTRACTS.md" },

  // Sentinel: events, rules, LangGraph graph, approval, audit
  { id: "bus", group: "sen", kind: "io", cap: "pipeline", repo: `${SEN}/consumer.py`, repoMore: ["contracts/event.schema.json"], doc: "architecture", docFile: "docs/adr/ADR-004-tunnel-and-ADR-005-bus.md" },
  { id: "correlate", group: "sen", kind: "code", cap: "sentinel_rules", repo: "services/sentinel/sentinel_core/correlate.py", doc: "architecture", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "rules", group: "sen", kind: "code", cap: "sentinel_rules", repo: "services/sentinel/sentinel_core/rules.py", repoMore: ["services/sentinel/rules.yaml"], doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "enrich", group: "sen", kind: "code", cap: "sentinel_agent", repo: `${SEN}/graph.py`, repoMore: [`${CORE}/tools/sentinel.py`], doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "compare", group: "sen", kind: "code", cap: "sentinel_agent", repo: `${SEN}/graph.py`, doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "assess", group: "sen", kind: "llm", cap: "sentinel_agent", repo: `${SEN}/graph.py`, repoMore: [`${SEN}/llm.py`], doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "summarise", group: "sen", kind: "llm", cap: "sentinel_agent", repo: `${SEN}/graph.py`, repoMore: [`${SEN}/llm.py`], doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "propose", group: "sen", kind: "llm", cap: "sentinel_agent", repo: `${SEN}/graph.py`, repoMore: [`${CORE}/tools/sentinel.py`], doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "act", group: "sen", kind: "code", cap: "sentinel_agent", repo: `${SEN}/graph.py`, repoMore: [`${CORE}/tools/sentinel.py`], doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "approval", group: "sen", kind: "gate", cap: "sentinel_agent", repo: `${SEN}/graph.py`, repoMore: ["web/components/IncidentBoard.tsx", "services/api/src/falcon_api/app.py"], doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },
  { id: "audit", group: "sen", kind: "store", cap: "audit_log", repo: `${SEN}/db.py`, repoMore: ["services/sentinel/migrations"], doc: "security", docFile: "docs/THREAT_MODEL.md" },

  // Investigator tools (contracts/tools.schema.json: investigator_tools)
  { id: "rdap_lookup", group: "tools_inv", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: [`${CORE}/signals/domain/rdap.py`], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "cert_lookup", group: "tools_inv", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: [`${CORE}/signals/domain/crt.py`], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "render_page", group: "tools_inv", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: ["services/sandbox/src/falcon_sandbox/browser.py"], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "compare_brand", group: "tools_inv", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: [`${CORE}/signals/brands/registry.py`], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "search_similar_scripts", group: "tools_inv", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: [`${CORE}/signals/message/scripts.py`], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "check_reputation", group: "tools_inv", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: [`${CORE}/signals/reputation/external.py`], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "expand_redirects", group: "tools_inv", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: [`${CORE}/signals/url/redirect.py`], doc: "agents", docFile: "docs/CONTRACTS.md" },

  // Sentinel tools (contracts/tools.schema.json: sentinel_tools), by mode
  { id: "search_verdicts", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "find_related_domains", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "get_past_incidents", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "feed_status", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "requeue_check", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "block_indicator", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, repoMore: ["scripts/falcon_demo"], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "upsert_incident", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "raise_alert", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "update_campaign_board", group: "tools_sen", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "export_stix", group: "tools_sen", kind: "code", cap: "stix", repo: `${CORE}/tools/stix.py`, repoMore: [`${CORE}/tools/sentinel.py`], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "draft_takedown", group: "tools_sen", kind: "gate", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "draft_police_report", group: "tools_sen", kind: "gate", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, doc: "agents", docFile: "docs/CONTRACTS.md" },

  // LLM router, prompts
  { id: "router", group: "llm", kind: "code", cap: "sovereign", repo: `${CORE}/llm/router.py`, repoMore: [`${CORE}/llm/config.py`], doc: "security", docFile: "docs/ARCHITECTURE.md" },
  { id: "redact", group: "llm", kind: "code", cap: "injection_defence", repo: `${CORE}/llm/spotlight.py`, repoMore: [`${CORE}/llm/redaction.py`, `${CORE}/llm/canary.py`], doc: "security", docFile: "docs/PRIVACY.md" },
  { id: "cloud", group: "llm", kind: "llm", cap: "sovereign", repo: `${CORE}/llm/providers.py`, doc: "privacy", docFile: "docs/PRIVACY.md" },
  { id: "local", group: "llm", kind: "llm", cap: "sovereign", repo: `${CORE}/llm/providers.py`, repoMore: ["infra/ollama"], doc: "privacy", docFile: "docs/adr/ADR-003-local-model.md" },
  { id: "dspy", group: "llm", kind: "code", cap: "dspy_compiled_prompts", repo: `${CORE}/prompts/__init__.py`, doc: "agents", docFile: "docs/adr/ADR-002-sentinel-langgraph.md" },

  // Observability
  { id: "prometheus", group: "obs", kind: "store", cap: "observability", repo: "infra/prometheus", repoMore: [`${CORE}/telemetry/metrics.py`], doc: "architecture", docFile: "docs/OBSERVABILITY.md" },
  { id: "grafana", group: "obs", kind: "io", cap: "observability", repo: "infra/grafana/dashboards", doc: "architecture", docFile: "docs/OBSERVABILITY.md" },
  { id: "phoenix", group: "obs", kind: "io", cap: "llm_tracing", repo: `${CORE}/telemetry/tracing.py`, repoMore: ["infra/otel", "docker-compose.yml"], doc: "architecture", docFile: "docs/OBSERVABILITY.md" },

  // Integration
  { id: "rest", group: "integ", kind: "io", cap: "rest_api", repo: "contracts/openapi.yaml", repoMore: ["services/api/src/falcon_api/app.py"], doc: "integration", docFile: "docs/INTEGRATION.md" },
  { id: "mcp", group: "integ", kind: "io", cap: "mcp", repo: "services/mcp/src/falcon_mcp/server.py", doc: "integration", docFile: "docs/INTEGRATION.md" },
  { id: "stix", group: "integ", kind: "io", cap: "stix", repo: `${CORE}/tools/stix.py`, repoMore: ["services/api/src/falcon_api/intel.py"], doc: "integration", docFile: "docs/INTEGRATION.md" },
  { id: "webhooks", group: "integ", kind: "io", cap: "rest_api", repo: "services/api/src/falcon_api/webhooks.py", doc: "integration", docFile: "docs/INTEGRATION.md" },

  // Business view only: one box per toolbox
  { id: "toolbox_inv", group: "biz_tools", kind: "code", cap: "investigator", repo: `${CORE}/tools/registry.py`, repoMore: ["contracts/tools.schema.json"], doc: "agents", docFile: "docs/CONTRACTS.md" },
  { id: "toolbox_sen", group: "biz_tools", kind: "code", cap: "sentinel_agent", repo: `${CORE}/tools/sentinel.py`, repoMore: ["contracts/tools.schema.json"], doc: "agents", docFile: "docs/CONTRACTS.md" },
];

export const NODE_BY_ID: ReadonlyMap<string, NodeDef> = new Map(NODES.map((n) => [n.id, n]));

/** A labelled run of nodes inside a group. Consecutive nodes of a `flow` group are joined by an animated connector. */
export interface Segment {
  label?: "graph" | "read" | "internal_auto" | "external_draft" | "cascade" | "events" | "loop";
  ids: readonly string[];
}
export interface GroupDef {
  id: GroupId;
  flow: boolean;
  segments: readonly Segment[];
}

/** Full technical view (/docs/agents). */
export const FULL_GROUPS: readonly GroupDef[] = [
  { id: "entry", flow: true, segments: [{ ids: ["clients", "api"] }, { ids: ["voice_mic", "voice_stt", "voice_intent"] }] },
  { id: "inv", flow: true, segments: [{ ids: ["t0", "t1", "t2", "t3", "arbiter", "verdict"] }] },
  { id: "sen", flow: true, segments: [{ label: "events", ids: ["bus", "correlate", "rules"] }, { label: "graph", ids: ["enrich", "compare", "assess", "summarise", "propose", "act"] }, { ids: ["approval", "audit"] }] },
  {
    id: "tools_inv",
    flow: false,
    segments: [{ ids: ["rdap_lookup", "cert_lookup", "render_page", "compare_brand", "search_similar_scripts", "check_reputation", "expand_redirects"] }],
  },
  {
    id: "tools_sen",
    flow: false,
    segments: [
      { label: "read", ids: ["search_verdicts", "find_related_domains", "get_past_incidents", "feed_status"] },
      { label: "internal_auto", ids: ["requeue_check", "block_indicator", "upsert_incident", "raise_alert", "update_campaign_board", "export_stix"] },
      { label: "external_draft", ids: ["draft_takedown", "draft_police_report"] },
    ],
  },
  { id: "llm", flow: false, segments: [{ ids: ["router", "redact", "cloud", "local", "dspy"] }] },
  { id: "obs", flow: false, segments: [{ ids: ["prometheus", "grafana", "phoenix"] }] },
  { id: "integ", flow: false, segments: [{ ids: ["rest", "mcp", "stix", "webhooks"] }] },
];

/** Simplified business view (/agents): the same nodes, fewer of them. */
export const BIZ_GROUPS: readonly GroupDef[] = [
  { id: "inv", flow: true, segments: [{ ids: ["t0", "t1", "t2", "t3", "arbiter", "verdict"] }] },
  { id: "sen", flow: true, segments: [{ ids: ["bus", "correlate", "rules", "assess", "propose", "approval", "audit"] }] },
  { id: "biz_tools", flow: false, segments: [{ ids: ["toolbox_inv", "toolbox_sen"] }] },
  { id: "biz_found", flow: false, segments: [{ ids: ["router", "phoenix", "rest", "mcp", "stix"] }] },
];

/**
 * Relations shown as highlights and as "connected to" links (undirected for display).
 * The flow order inside inv / sen is added automatically by `relatedOf`.
 */
const EXTRA_LINKS: readonly (readonly [string, string])[] = [
  ["clients", "api"],
  ["voice_mic", "clients"],
  ["voice_stt", "api"],
  ["voice_intent", "api"],
  ["voice_intent", "t0"],
  ["api", "t0"],
  ["verdict", "bus"],
  ["t2", "render_page"],
  ["t2", "compare_brand"],
  ["t3", "toolbox_inv"],
  ["t3", "router"],
  ["t3", "rdap_lookup"],
  ["t3", "cert_lookup"],
  ["t3", "render_page"],
  ["t3", "compare_brand"],
  ["t3", "search_similar_scripts"],
  ["t3", "check_reputation"],
  ["t3", "expand_redirects"],
  ["verdict", "router"],
  ["t2", "router"],
  ["enrich", "search_verdicts"],
  ["enrich", "find_related_domains"],
  ["enrich", "get_past_incidents"],
  ["enrich", "feed_status"],
  ["assess", "router"],
  ["summarise", "router"],
  ["propose", "router"],
  ["propose", "toolbox_sen"],
  ["act", "requeue_check"],
  ["act", "block_indicator"],
  ["act", "upsert_incident"],
  ["act", "raise_alert"],
  ["act", "update_campaign_board"],
  ["act", "export_stix"],
  ["act", "draft_takedown"],
  ["act", "draft_police_report"],
  ["draft_takedown", "approval"],
  ["draft_police_report", "approval"],
  ["act", "audit"],
  ["router", "redact"],
  ["router", "cloud"],
  ["router", "local"],
  ["router", "dspy"],
  ["router", "phoenix"],
  ["router", "prometheus"],
  ["prometheus", "grafana"],
  ["phoenix", "grafana"],
  ["api", "rest"],
  ["api", "mcp"],
  ["api", "webhooks"],
  ["export_stix", "stix"],
  ["audit", "webhooks"],
  ["rules", "toolbox_sen"],
  ["bus", "phoenix"],
  ["toolbox_inv", "toolbox_sen"],
];

const FLOW_PAIRS: readonly (readonly [string, string])[] = [
  ...pairs(["t0", "t1", "t2", "t3", "arbiter", "verdict"]),
  ...pairs(["bus", "correlate", "rules", "enrich", "compare", "assess", "summarise", "propose", "act", "approval", "audit"]),
];

function pairs(ids: readonly string[]): (readonly [string, string])[] {
  return ids.slice(1).map((id, i) => [ids[i]!, id] as const);
}

const RELATED = (() => {
  const map = new Map<string, Set<string>>();
  for (const [a, b] of [...FLOW_PAIRS, ...EXTRA_LINKS]) {
    if (!map.has(a)) map.set(a, new Set());
    if (!map.has(b)) map.set(b, new Set());
    map.get(a)!.add(b);
    map.get(b)!.add(a);
  }
  return map;
})();

/** Ids connected to `id`, in a stable order. */
export function relatedOf(id: string, visible?: ReadonlySet<string>): string[] {
  const all = [...(RELATED.get(id) ?? [])];
  return visible ? all.filter((x) => visible.has(x)) : all;
}

export const idsOf = (groups: readonly GroupDef[]): string[] => groups.flatMap((g) => g.segments.flatMap((s) => [...s.ids]));
