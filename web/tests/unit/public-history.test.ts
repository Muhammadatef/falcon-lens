import { describe, expect, it } from "vitest";
import { filterFrameWith, scrub, toPublicCheck, toPublicCheckPage, toPublicCheckSummary, toPublicIncident, toPublicIncidentPage, toPublicTrace } from "@/lib/public-history";

const VID = "vd_01HZX3K9Q2M4N5P6R7S8T9V0WX";
const IID = "inc_01HZX3K9Q2M4N5P6R7S8T9V0WX";

const PHONE = "+971 50 123 4567";
const PHONE_LOCAL = "0501234567";
const EMAIL = "victim.name@example-mail.com";
const URL_PII = "https://login.evil-example.com/verify/path?email=victim.name@example-mail.com&phone=0501234567&token=SECRET123";
const MESSAGE = `Dear customer call ${PHONE} or ${PHONE_LOCAL}, mail ${EMAIL} or open ${URL_PII}`;

const LEAKS = [PHONE, "50 123 4567", PHONE_LOCAL, "1234567", EMAIL, "victim.name", "example-mail", "SECRET123", "/verify/path", "?email", "token="];
const expectNoLeak = (value: unknown) => {
  const text = JSON.stringify(value);
  for (const leak of LEAKS) expect(text, `leaked: ${leak}`).not.toContain(leak);
};

const verdictDoc = () => ({
  schema_version: "1.0",
  verdict_id: VID,
  input_type: "message",
  input_text: MESSAGE,
  raw_text: MESSAGE,
  input_fingerprint: "sha256:abc",
  canonical_url: URL_PII,
  verdict: "dangerous",
  risk_score: 91,
  calibrated_probability: 0.93,
  impersonated_brand: { brand_id: "falcon_demo_bank", name_ar: "بنك الصقر التجريبي", name_en: "Falcon Demo Bank", official_domains: ["falcon-demo-bank.example"] },
  evidence: [
    {
      id: "ev_001",
      signal: "lexical.urgency",
      family: "lexical",
      observed: { quote: MESSAGE, phone: PHONE },
      display: { ar: `يطلب الاتصال بالرقم ${PHONE} أو ${EMAIL}`, en: `Asks you to call ${PHONE} and open ${URL_PII}` },
      weight: 12,
      polarity: "risk",
      hard_rule: null,
      source: "rule:lexical",
      tier: "T0",
      latency_ms: 4,
      error: null,
    },
    { id: "ev_002", signal: "llm.extract", family: "llm", observed: EMAIL, display: { en: `Sender ${EMAIL}` }, weight: 8, polarity: "risk", source: "llm:extractor", tier: "T2", error: `failed for ${EMAIL}` },
  ],
  reasons: [{ ar: `رابط مشبوه ${URL_PII}`, en: `Link ${URL_PII} and number ${PHONE}`, evidence_ids: ["ev_001", "ev_missing"] }],
  actions: { now: { ar: ["x"], en: [`Call ${PHONE}`] }, if_already_acted: { ar: [], en: [] }, report: { ar: "", en: "", channels: [{ value: PHONE }] } },
  tier_reached: "T2",
  model_route: "local",
  degraded: false,
  degraded_reasons: ["t3_unavailable", `bad ${EMAIL}`],
  final: true,
  trace: [
    { step: 1, kind: "tier", name: "t0", summary: `Read ${MESSAGE}`, ms: 5, evidence_added: ["ev_001"] },
    { step: 2, kind: "tool", name: "whois_lookup", summary: `Looked up ${URL_PII}`, ms: 120 },
  ],
  screenshot_url: "https://shots.example/x.png",
  email_headers: { from: EMAIL, "reply-to": EMAIL },
  source: "live",
  latency_ms: 800,
  created_at: "2026-11-24T10:00:00Z",
});

describe("scrub", () => {
  it("removes phone numbers, emails and everything after a link host", () => {
    const out = scrub(MESSAGE);
    expectNoLeak(out);
    expect(out).toContain("hxxps://login[.]evil-example[.]com");
    expect(out).toContain("[email]");
    expect(out).toContain("[number]");
  });

  it("handles Arabic-Indic digits and bare domains with paths", () => {
    const out = scrub("اتصل على ٠٥٠١٢٣٤٥٦٧ أو زر evil-example.com/pay?card=1");
    expect(out).not.toMatch(/٠٥٠١٢٣٤٥٦٧|0501234567/);
    expect(out).not.toContain("pay");
    expect(out).toContain("evil-example[.]com");
  });

  it("leaves ordinary sentences and versions alone", () => {
    expect(scrub("Domain registered 3 days ago, v1.2 rule")).toBe("Domain registered 3 days ago, v1.2 rule");
  });

  it("is idempotent", () => {
    const once = scrub(MESSAGE);
    expect(scrub(once)).toBe(once);
  });
});

describe("toPublicCheck (detail)", () => {
  const out = toPublicCheck(verdictDoc())!;

  it("keeps verdict, score, tiers, evidence codes, reasons and tool names", () => {
    expect(out.verdict).toBe("dangerous");
    expect(out.risk_score).toBe(91);
    expect(out.tier_reached).toBe("T2");
    const ev = out.evidence as { id: string; signal: string; display: { en: string } }[];
    expect(ev.map((e) => e.signal)).toEqual(["lexical.urgency", "llm.extract"]);
    expect(ev[0]!.display.en).toContain("Asks you to call");
    expect((out.trace as { name?: string; ms?: number }[])[1]).toMatchObject({ name: "whois_lookup", ms: 120 });
    expect((out.reasons as { evidence_ids: string[] }[])[0]!.evidence_ids).toEqual(["ev_001"]);
  });

  it("leaks no phone, email, URL path, query or userinfo anywhere", () => {
    expectNoLeak(out);
  });

  it("drops every field outside the allow-list", () => {
    for (const key of ["input_text", "raw_text", "input_fingerprint", "email_headers", "screenshot_url"]) expect(out).not.toHaveProperty(key);
    expect(JSON.stringify(out)).not.toContain("shots.example");
    expect(JSON.stringify(out)).not.toContain("falcon-demo-bank.example");
    expect((out.evidence as { observed: unknown }[]).every((e) => e.observed === null)).toBe(true);
    expect((out.trace as { summary: string }[]).every((s) => s.summary === "")).toBe(true);
    expect((out.actions as { report: { channels?: unknown } }).report.channels).toBeUndefined();
    expect(out.canonical_url).toBeNull();
    expect(out.degraded_reasons).toEqual(["t3_unavailable"]);
  });

  it("keeps only a defanged host for a link and downgrades degraded no-warning verdicts", () => {
    const link = toPublicCheck({ ...verdictDoc(), input_type: "url", verdict: "no_warning_signs", degraded: true })!;
    expect(link.canonical_url).toBe("hxxps://login[.]evil-example[.]com");
    expect(link.verdict).toBe("suspicious");
    expectNoLeak(link.canonical_url);
  });

  it("rejects an unusable document", () => {
    expect(toPublicCheck({ verdict_id: "nope" })).toBeNull();
    expect(toPublicCheck(null)).toBeNull();
  });
});

describe("toPublicCheckSummary / page", () => {
  const row = { verdict_id: VID, created_at: "2026-11-24T10:00:00Z", input_type: "message", display: URL_PII, verdict: "suspicious", risk_score: 55, degraded: false, degraded_reasons: [], tier_reached: "T1", model_route: "none", source: "replay", agent: { tiers_run: ["T0", "T1"], extractor_ran: false, investigator_ran: false, tool_calls: 0, llm_calls: 0 }, input_text: MESSAGE };

  it("shows nothing for messages, emails and images even if display is sent", () => {
    for (const type of ["message", "email", "image"]) expect(toPublicCheckSummary({ ...row, input_type: type })!.display).toBeNull();
  });

  it("reduces a link display to the defanged host", () => {
    const s = toPublicCheckSummary({ ...row, input_type: "url" })!;
    expect(s.display).toBe("hxxps://login[.]evil-example[.]com");
    expectNoLeak(s);
  });

  it("returns exactly the summary fields", () => {
    expect(Object.keys(toPublicCheckSummary(row)!).sort()).toEqual(["agent", "created_at", "degraded", "degraded_reasons", "display", "input_type", "model_route", "risk_score", "source", "tier_reached", "verdict", "verdict_id"]);
  });

  it("drops bad rows and bad cursors from a page", () => {
    const page = toPublicCheckPage({ items: [row, { verdict_id: "x" }, "str"], next_cursor: "1-2; drop" });
    expect(page.items).toHaveLength(1);
    expect(page.next_cursor).toBeNull();
    expect(toPublicCheckPage({ items: [row], next_cursor: "1700000000000-0" }).next_cursor).toBe("1700000000000-0");
  });
});

const incidentDoc = () => ({
  incident_id: IID,
  type: "campaign",
  severity: "high",
  severity_reason: { ar: `سبب ${EMAIL}`, en: `Reason ${PHONE}`, evidence_ids: ["ev_001"] },
  status: "awaiting_approval",
  brand_id: "falcon_demo_bank",
  rule_ids: ["R-CAMPAIGN-01"],
  correlation_keys: { phone: PHONE, email: EMAIL },
  indicators: [
    { kind: "domain", value_defanged: "login[.]evil-example[.]com/verify?token=SECRET123", first_seen: "2026-11-24T10:00:00Z" },
    { kind: "phone", value_defanged: PHONE, first_seen: "2026-11-24T10:00:00Z" },
    { kind: "email", value_defanged: EMAIL, first_seen: "2026-11-24T10:00:00Z" },
  ],
  linked_verdicts: [VID, "junk"],
  timeline: [{ at: "2026-11-24T10:00:00Z", what: `note ${EMAIL}` }],
  summary: { ar: "حملة تصيّد", en: "Phishing campaign", generated_by: "llm" },
  actions: [
    { action_id: "act_01", tool: "draft_takedown", mode: "external_draft", status: "awaiting_approval", draft: { recipient_kind: "registrar", subject: "Takedown", body_en: `Send to abuse@registrar-example.com ${PHONE}` }, evidence_ids: ["ev_001"], approved_by: "operator-ali" },
    { action_id: "act_02", tool: "block_indicator", mode: "internal_auto", status: "executed", evidence_ids: [] },
  ],
  source: "synthetic",
  created_at: "2026-11-24T10:00:00Z",
  updated_at: "2026-11-24T10:05:00Z",
});

describe("toPublicIncident", () => {
  const out = toPublicIncident(incidentDoc())!;
  it("keeps title, severity, counts and action types with status", () => {
    expect((out.summary as { en: string }).en).toBe("Phishing campaign");
    expect(out.severity).toBe("high");
    expect(out.linked_verdicts).toEqual([VID]);
    expect((out.actions as { tool: string; status: string }[]).map((a) => [a.tool, a.status])).toEqual([["draft_takedown", "awaiting_approval"], ["block_indicator", "executed"]]);
  });
  it("never carries draft bodies, recipients, approvers or personal data", () => {
    const text = JSON.stringify(out);
    for (const bad of ["registrar-example", "abuse@", "Takedown", "recipient_kind", "operator-ali", "SECRET123", "/verify"]) expect(text).not.toContain(bad);
    expectNoLeak(out);
    expect((out.actions as { draft: unknown }[]).every((a) => a.draft === null)).toBe(true);
    expect(out.correlation_keys).toEqual({});
    expect(out.timeline).toEqual([]);
    expect((out.indicators as { value_defanged: string }[]).map((i) => i.value_defanged)).toEqual(["login[.]evil-example[.]com"]);
  });
  it("lists only valid rows", () => {
    expect(toPublicIncidentPage({ items: [incidentDoc(), { incident_id: "bad" }] }).items).toHaveLength(1);
  });
});

describe("toPublicTrace", () => {
  const trace = {
    incident_id: IID,
    thread_id: "secret-thread",
    runs: [
      {
        run_id: "run_1",
        started_at: "2026-11-24T10:00:00Z",
        finished_at: null,
        status: "interrupted",
        steps: [
          { seq: 1, node: "enrich", started_at: "2026-11-24T10:00:01Z", duration_ms: 40, status: "completed", summary_en: `Looked at ${URL_PII}`, summary_ar: `رقم ${PHONE}`, tools: [{ name: "whois_lookup", mode: "read", status: "ok", evidence_ids: ["ev_001"], duration_ms: 30 }], llm: null, generated_by: "rule", budget: { steps_used: 1, tokens_used: 0, elapsed_ms: 40 }, error_code: null },
          { seq: 2, node: "evil_node", started_at: "x", duration_ms: 1, status: "completed" },
        ],
        interrupt: { action_id: "act_01", tool: "draft_takedown", waiting_since: "2026-11-24T10:00:05Z", pending_count: 1, decision: "approved", decided_by: "operator-ali" },
      },
    ],
  };
  const out = toPublicTrace(trace)!;
  it("keeps node names, timestamps and tool names only", () => {
    const steps = (out.runs as { steps: { node: string; summary_en: string; tools: { name: string; duration_ms: number }[] }[] }[])[0]!.steps;
    expect(steps.map((s) => s.node)).toEqual(["enrich"]);
    expect(steps[0]!.tools[0]).toMatchObject({ name: "whois_lookup", duration_ms: 30 });
    expect(steps[0]!.summary_en).toBe("");
  });
  it("drops decisions, approvers and free text", () => {
    const text = JSON.stringify(out);
    for (const bad of ["operator-ali", "decided_by", "decision", "secret-thread", "evil_node"]) expect(text).not.toContain(bad);
    expectNoLeak(out);
  });
});

describe("filterFrameWith", () => {
  it("re-projects frames and drops unknown events", () => {
    const frame = `id: 17-0\nevent: incident\ndata: ${JSON.stringify(incidentDoc())}`;
    const out = filterFrameWith(frame, "incident", toPublicIncident)!;
    expect(out).toContain("event: incident");
    expect(out).not.toContain("operator-ali");
    expect(filterFrameWith(`event: other\ndata: {}`, "incident", toPublicIncident)).toBeNull();
    expect(filterFrameWith(`event: incident\ndata: not json`, "incident", toPublicIncident)).toBeNull();
  });
});
