#!/usr/bin/env node
/**
 * Test stand-in for the Caddy gateway + API (TEST ONLY, never shipped).
 *   /v1/*      mocked REST v1 with real, delayed SSE (so progressive rendering is exercised)
 *   /__mock/*  control plane used by the Playwright tests to register scenarios
 *   the rest   proxied to the Next.js standalone server
 *
 * The /v1/check and /v1/verdicts behaviour mirrors services/api/src/falcon_api/app.py
 * (PR #4) and contracts/openapi.yaml: JSON for url/message, multipart field `file` for
 * email (.eml, RFC 5322) and image (PNG/JPEG/WebP by magic bytes), Content-Length
 * required (411), byte limits (413), 415/422 validation, 202 Accepted or 200 Verdict on
 * a cache hit, GET verdict 200 final / 202 partial / 404, RFC 9457 problem+json with
 * urn:falcon-lens:problem:<slug>, and SSE with comments, `retry`, ids and `event: verdict`.
 *
 * Scenarios are registered per test and matched by a unique string inside the request
 * body, so tests can run in parallel against one mock.
 */
import { randomBytes } from "node:crypto";
import http from "node:http";

const PORT = Number(process.env.MOCK_PORT ?? 43110);
const APP_PORT = Number(process.env.APP_PORT ?? 43111);
/** Two extra app instances whose FL_API_INTERNAL_URL points at /__caps/<mode>: every capability flag forced false / true. */
const CAP_APPS = { false: Number(process.env.APP_PORT_CAPS_FALSE ?? 43112), true: Number(process.env.APP_PORT_CAPS_TRUE ?? 43113) };
const CAP_IDS = ["message_check", "email_check", "image_check", "injection_defence", "investigator", "sentinel_agent", "rest_api", "mcp", "stix", "t1_measured_model", "url_check", "brand_check", "pipeline", "audit_log", "sentinel_rules", "observability", "sovereign", "pwa", "dspy_compiled_prompts", "llm_tracing", "voice_assistant"];
const LIMITS = { url: 4096, message: 8 * 1024, email: 2 * 1024 * 1024, image: 5 * 1024 * 1024 };
const BODY_LIMITS = { url: 32 * 1024, message: 64 * 1024, email: LIMITS.email + 64 * 1024, image: LIMITS.image + 64 * 1024 };

/** @type {Map<string, any>} */ const scenarios = new Map();
/** @type {Map<string, any>} */ const byId = new Map();
/** @type {Map<string, any>} */ const boards = new Map();

const readBody = (req) =>
  new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks)));
  });

const json = (res, status, body, headers = {}) => {
  res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store", ...headers });
  res.end(JSON.stringify(body));
};
const problem = (req, res, status, slug, title, headers = {}) => {
  const requestId = `req_${randomBytes(8).toString("hex")}`;
  res.writeHead(status, { "content-type": "application/problem+json", "cache-control": "no-store", "x-request-id": requestId, ...headers });
  res.end(JSON.stringify({ type: `urn:falcon-lens:problem:${slug}`, title, status, instance: new URL(req.url, "http://x").pathname, request_id: requestId }));
};
const cookie = (req, name) => {
  const m = new RegExp(`(?:^|;\\s*)${name}=([^;]+)`).exec(req.headers.cookie ?? "");
  return m ? decodeURIComponent(m[1]) : null;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sseHead = (res) => {
  res.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-store", connection: "keep-alive" });
  res.write(": stream open\nretry: 3000\n\n");
};
const sseSend = (res, event, data, id) => res.write(`${id ? `id: ${id}\n` : ""}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

/** Extracts the single `file` part of a multipart body: { filename, data } or null. */
function filePart(req, raw) {
  const boundary = /boundary=("?)([^";]+)\1/.exec(req.headers["content-type"] ?? "")?.[2];
  if (!boundary) return null;
  const delimiter = Buffer.from(`--${boundary}`);
  let at = raw.indexOf(delimiter);
  while (at !== -1) {
    const next = raw.indexOf(delimiter, at + delimiter.length);
    if (next === -1) break;
    const part = raw.subarray(at + delimiter.length + 2, next - 2);
    const split = part.indexOf("\r\n\r\n");
    const head = part.subarray(0, split).toString("utf8");
    if (/name="file"/.test(head)) return { filename: /filename="([^"]*)"/.exec(head)?.[1] ?? "", data: part.subarray(split + 4) };
    at = next;
  }
  return null;
}
const looksLikeEml = (data) => {
  const head = data.subarray(0, 16384).toString("latin1");
  return !head.includes("\u0000") && /^(From [^\r\n]*|[!-9;-~]{1,64}:[^\r\n]*)\r?\n/.test(head) && /^(from|to|subject|received|date|message-id|mime-version):/im.test(head);
};
const sniffImage = (d) =>
  d.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) || (d[0] === 0xff && d[1] === 0xd8 && d[2] === 0xff) || (d.subarray(0, 4).toString() === "RIFF" && d.subarray(8, 12).toString() === "WEBP");
const checkableUrl = (value) => {
  const s = value.trim();
  if (/[\u0000- \u007f]/.test(s)) return false;
  if (!/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(s)) return !(s.includes("://") || /^(javascript|data|file|mailto):/i.test(s));
  return /^https?:\/\/[^/?#]+/i.test(s);
};

async function control(req, res, path) {
  const body = req.method === "POST" ? JSON.parse((await readBody(req)).toString("utf8") || "{}") : null;
  if (path === "/__mock/scenario" && req.method === "POST") {
    const s = { requests: [], streamOpens: 0, statusCalls: 0, ...body };
    scenarios.set(s.match, s);
    if (s.verdictId) byId.set(s.verdictId, s);
    return json(res, 200, { ok: true });
  }
  if (path === "/__mock/scenario" && req.method === "GET") {
    const s = scenarios.get(new URL(req.url, "http://x").searchParams.get("match") ?? "");
    return s ? json(res, 200, { requests: s.requests, streamOpens: s.streamOpens, statusCalls: s.statusCalls }) : problem(req, res, 404, "not-found", "no scenario");
  }
  if (path === "/__mock/boards" && req.method === "POST") {
    boards.set(body.key, { decisions: [], ...body });
    return json(res, 200, { ok: true });
  }
  if (path === "/__mock/voice" && req.method === "GET") return json(res, 200, { calls: voiceCalls });
  if (path === "/__mock/boards" && req.method === "GET") {
    const b = boards.get(new URL(req.url, "http://x").searchParams.get("key") ?? "");
    return b ? json(res, 200, { decisions: b.decisions, routePuts: b.routePuts ?? [] }) : problem(req, res, 404, "not-found", "no board");
  }
  return problem(req, res, 404, "not-found", "unknown control route");
}

async function check(req, res, kind) {
  const length = req.headers["content-length"];
  if (length === undefined) return problem(req, res, 411, "length-required", "Content-Length required");
  const raw = await readBody(req);
  if (raw.length > BODY_LIMITS[kind]) return problem(req, res, 413, "payload-too-large", "Payload too large");
  const type = req.headers["content-type"] ?? "";

  if (kind === "url" || kind === "message") {
    let body;
    try {
      body = type.includes("application/json") ? JSON.parse(raw.toString("utf8")) : null;
    } catch {
      body = null;
    }
    const value = body?.[kind === "url" ? "url" : "text"];
    if (typeof value !== "string" || value.length === 0) return problem(req, res, 422, "invalid-request", "Invalid request");
    if (Buffer.byteLength(value) > LIMITS[kind]) return problem(req, res, 413, "payload-too-large", "Payload too large");
    if (kind === "url" && !checkableUrl(value)) return problem(req, res, 422, "invalid-url", "Not a checkable http(s) URL");
  } else {
    const part = type.includes("multipart/form-data") ? filePart(req, raw) : null;
    if (!part) return problem(req, res, 422, "invalid-request", "Invalid request");
    if (part.data.length > LIMITS[kind]) return problem(req, res, 413, "payload-too-large", "File too large");
    if (part.data.length === 0) return problem(req, res, 422, "empty-file", "Empty file");
    if (kind === "email" && !(part.filename.toLowerCase().endsWith(".eml") && looksLikeEml(part.data))) return problem(req, res, 415, "unsupported-media-type", "Expected an RFC 5322 .eml file");
    if (kind === "image" && !sniffImage(part.data)) return problem(req, res, 415, "unsupported-media-type", "Expected a PNG, JPEG or WebP image");
  }

  const text = raw.toString("utf8");
  const s = [...scenarios.values()].find((x) => text.includes(x.match));
  if (!s) return problem(req, res, 503, "queue-unavailable", "Queue unavailable"); // nothing registered = backend down
  s.requests.push({ kind, contentType: type, forwardedFor: req.headers["x-forwarded-for"] ?? null });
  if (s.status === 429) return problem(req, res, 429, "rate-limited", "Rate limit exceeded", { "retry-after": String(s.retryAfter ?? 30), "x-ratelimit-limit": "30" });
  if (s.status && s.status >= 400) return problem(req, res, s.status, "mock", "error");
  const accepted = { verdict_id: s.verdictId, events_url: `/v1/verdicts/${s.verdictId}/events`, status_url: `/v1/verdicts/${s.verdictId}` };
  const headers = { location: accepted.status_url, "x-verdict-state": s.cached ? "cached" : "queued" };
  // Cache hit: 200 with the final Verdict itself, as the real API does.
  if (s.cached) return json(res, 200, s.steps[s.steps.length - 1].verdict, headers);
  return json(res, 202, accepted, headers);
}

/** Voice: the multipart body carries a marker like VOICE:check-ar; the reply is canned. */
const VOICE_REPLIES = {
  "check-ar": { transcript: "يا صقر، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر", lang: "ar", wake: true, intent: "check_clipboard", command: "شغّل عدسة الصقر" },
  "check-en": { transcript: "Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens", lang: "en", wake: true, intent: "check_clipboard", command: "run Falcon Lens" },
  "help-en": { transcript: "Hey Falcon help me", lang: "en", wake: true, intent: "help", command: "help me" },
  "help-ar": { transcript: "يا صقر ساعدني", lang: "ar", wake: true, intent: "help", command: "ساعدني" },
  "none-ar": { transcript: "يا صقر", lang: "ar", wake: true, intent: "none", command: "" },
  stop: { transcript: "Falcon stop", lang: "en", wake: true, intent: "stop", command: "stop" },
  "none-en": { transcript: "Hey Falcon", lang: "en", wake: true, intent: "none", command: "" },
  "faq-otp-ar": { transcript: "يا صقر، هل البنك يطلب مني الرمز", lang: "ar", wake: true, intent: "faq", command: "هل البنك يطلب مني الرمز", answer_id: "faq.otp" },
  "faq-clicked-en": { transcript: "Hey Falcon, I already clicked the link, what now?", lang: "en", wake: true, intent: "faq", command: "I already clicked the link, what now?", answer_id: "faq.clicked_link" },
  "faq-follow-ar": { transcript: "وش أسوي إذا ضغطت على الرابط", lang: "ar", wake: true, intent: "faq", command: "وش أسوي إذا ضغطت على الرابط", answer_id: "faq.clicked_link" },
  "offtopic-en": { transcript: "Hey Falcon, what is the weather", lang: "en", wake: true, intent: "off_topic", command: "what is the weather", answer_id: null },
  "offtopic-ar": { transcript: "يا صقر، احكي لي نكتة", lang: "ar", wake: true, intent: "off_topic", command: "احكي لي نكتة", answer_id: null },
  noise: { transcript: "what is for dinner", lang: "en", wake: false, intent: "none", command: "" },
};
const voiceCalls = [];
async function voice(req, res) {
  if (req.headers["x-api-key"] !== "test-read-key") return problem(req, res, 401, "unauthorized", "Unauthorized");
  const raw = await readBody(req);
  const text = raw.toString("latin1");
  voiceCalls.push({ bytes: raw.length, hasAudioPart: /name="audio"/.test(text), followUp: /name="follow_up"\r\n\r\n(\d)/.exec(text)?.[1] ?? null, langHint: /name="lang_hint"\r\n\r\n(\w+)/.exec(text)?.[1] ?? null, marker: /;T:([a-z0-9]+)/.exec(text)?.[1] ?? null });
  if (text.includes("VOICE:fail")) return problem(req, res, 503, "unavailable", "Unavailable");
  const reply = VOICE_REPLIES[/VOICE:([a-z-]+)/.exec(text)?.[1] ?? ""];
  if (!reply) return problem(req, res, 422, "invalid-request", "Invalid request");
  return json(res, 200, { duration_ms: 3200, model: "mock-asr", answer_id: null, ...reply });
}

async function api(req, res, path) {
  if (path === "/v1/voice/utterance" && req.method === "POST") return voice(req, res);
  const checkRoute = /^\/v1\/check\/(url|message|email|image)$/.exec(path);
  if (checkRoute && req.method === "POST") return check(req, res, checkRoute[1]);

  const events = /^\/v1\/verdicts\/([^/]+)\/events$/.exec(path);
  if (events && req.method === "GET") {
    const s = byId.get(events[1]);
    if (!s) return problem(req, res, 404, "verdict-not-found", "Verdict not found");
    s.streamOpens += 1;
    if (s.streamStatus) return problem(req, res, s.streamStatus, "queue-unavailable", "Queue unavailable");
    sseHead(res);
    let n = 0;
    for (const step of s.steps ?? []) {
      await sleep(step.delayMs ?? 0);
      if (res.destroyed) return;
      if (n === 1) res.write(": heartbeat\n\n");
      sseSend(res, "verdict", step.verdict, `${s.verdictId}.${n++}`);
    }
    if (s.drop) return void res.destroy();
    return void res.end(); // the real stream closes after `final: true`
  }

  // Operator history (GET /v1/verdicts, /v1/verdicts/stream) and operator verdict lookup, per board cookie.
  const hboard = boards.get(cookie(req, "mock_boards") ?? "");
  const hkey = req.headers["x-api-key"] ?? (/^bearer /i.test(req.headers.authorization ?? "") ? req.headers.authorization.slice(7) : undefined);
  const hAuthed = !hboard?.requireKey || hkey === hboard.requireKey;
  if (hboard?.verdicts != null && req.method === "GET") {
    if (path === "/v1/verdicts") {
      if (!hAuthed) return problem(req, res, 401, "unauthorized", "Unauthorized");
      return json(res, 200, { items: hboard.verdicts, next_cursor: hboard.nextCursor ?? null });
    }
    if (path === "/v1/verdicts/stream") {
      if (!hAuthed) return problem(req, res, 401, "unauthorized", "Unauthorized");
      sseHead(res);
      let n = 0;
      for (const v of hboard.verdictEvents ?? []) {
        await sleep(400);
        if (res.destroyed) return;
        sseSend(res, "verdict", v, `${Date.now()}-${n++}`);
      }
      return;
    }
    const pack = /^\/v1\/verdicts\/([^/]+)\/evidence-pack$/.exec(path);
    if (pack && hboard.verdictDocs?.[pack[1]]) {
      if (!hkey) return problem(req, res, 401, "unauthorized", "Unauthorized");
      if (!hAuthed) return problem(req, res, 403, "forbidden", "Forbidden");
      res.writeHead(200, { "content-type": "application/zip", "content-disposition": `attachment; filename="evidence-${pack[1]}.zip"` });
      return res.end(Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"));
    }
    const doc = /^\/v1\/verdicts\/([^/]+)$/.exec(path);
    if (doc && hboard.verdictDocs?.[doc[1]]) {
      if (!hAuthed) return problem(req, res, 401, "unauthorized", "Unauthorized");
      return json(res, 200, hboard.verdictDocs[doc[1]]);
    }
  }

  const status = /^\/v1\/verdicts\/([^/]+)$/.exec(path);
  if (status && req.method === "GET") {
    const s = byId.get(status[1]);
    if (!s) return problem(req, res, 404, "verdict-not-found", "Verdict not found");
    s.statusCalls += 1;
    if (s.statusVerdict === null) return problem(req, res, 503, "queue-unavailable", "Queue unavailable");
    const v = s.statusVerdict ?? s.steps?.[s.steps.length - 1]?.verdict;
    return v ? json(res, v.final ? 200 : 202, v) : problem(req, res, 404, "verdict-not-found", "Verdict not found");
  }

  // Boards: not in PR #4 yet; shapes are the frontend's logged assumptions (DECISIONS.md).
  const board = boards.get(cookie(req, "mock_boards") ?? "");
  const key = req.headers["x-api-key"] ?? (/^bearer /i.test(req.headers.authorization ?? "") ? req.headers.authorization.slice(7) : undefined);
  const authed = (b) => !b.requireKey || key === b.requireKey;

  // Campaigns need a read key like the real API: the web server sends X-API-Key, a browser never does.
  if (path.startsWith("/v1/campaigns") && (key !== "test-read-key" || board?.rejectKey)) return problem(req, res, 401, "unauthorized", "Unauthorized");
  if (path === "/v1/campaigns" && req.method === "GET") {
    if (!board || board.campaigns == null) return problem(req, res, 404, "not-found", "Not found");
    // operator-only extras on purpose: the public route must strip them
    return json(res, 200, { items: board.campaigns.map((c) => ({ ...c, actions: [{ id: "act_x", draft: "SECRET-DRAFT" }], approver: "SECRET-APPROVER", raw_url: "http://evil.example/x" })) });
  }
  if (path === "/v1/campaigns/stream" && req.method === "GET") {
    if (!board || board.campaigns == null) return problem(req, res, 404, "not-found", "Not found");
    sseHead(res);
    for (const c of board.campaignEvents ?? []) {
      await sleep(400);
      if (res.destroyed) return;
      sseSend(res, "campaign", c);
    }
    return; // stays open
  }
  if (path === "/v1/incidents" && req.method === "GET") {
    if (!board || board.incidents == null) return problem(req, res, 404, "not-found", "Not found");
    if (!authed(board)) return problem(req, res, 401, "unauthorized", "Unauthorized");
    return json(res, 200, { items: board.incidents });
  }
  if (path === "/v1/incidents/stream" && req.method === "GET") {
    if (!board || board.incidents == null) return problem(req, res, 404, "not-found", "Not found");
    if (!authed(board)) return problem(req, res, 401, "unauthorized", "Unauthorized");
    sseHead(res);
    for (const i of board.incidentEvents ?? []) {
      await sleep(400);
      if (res.destroyed) return;
      sseSend(res, "incident", i);
    }
    return;
  }
  const one = /^\/v1\/incidents\/([^/]+)(\/trace)?$/.exec(path);
  if (one && req.method === "GET" && one[1] !== "stream") {
    if (!board || board.incidents == null) return problem(req, res, 404, "not-found", "Not found");
    if (!authed(board)) return problem(req, res, 401, "unauthorized", "Unauthorized");
    const inc = board.incidents.find((i) => i.incident_id === one[1]);
    if (!inc) return problem(req, res, 404, "not-found", "Not found");
    if (!one[2]) return json(res, 200, inc);
    // The trace can advance per poll: `traces` is a list of snapshots, the last one repeats.
    const snaps = board.traces?.[one[1]];
    if (!snaps?.length) return json(res, 200, { incident_id: one[1], thread_id: one[1], runs: [] });
    board.traceCalls = (board.traceCalls ?? 0) + 1;
    return json(res, 200, snaps[Math.min(board.traceCalls - 1, snaps.length - 1)]);
  }
  // Operator-only model route (mirrors services/api/src/falcon_api/admin.py).
  if (path === "/v1/admin/llm-route" && (req.method === "GET" || req.method === "PUT")) {
    if (!board || !key || !authed(board)) return problem(req, res, 401, "unauthorized", "Unauthorized");
    board.route ??= { mode: "cloud_with_local_fallback", local_model: "inkling-2-mini-chat", updated_at: null, updated_by: null };
    if (req.method === "PUT") {
      const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
      const modes = ["cloud_with_local_fallback", "local", "cloud_only", "auto"];
      const models = ["inkling-2-mini-chat", "qwen3.8:27b"];
      if (!modes.includes(body.mode) || (body.local_model != null && !models.includes(body.local_model))) return problem(req, res, 422, "invalid", "Invalid");
      board.route = { mode: body.mode, local_model: body.local_model ?? board.route.local_model, updated_at: "2026-11-24T12:00:00+00:00", updated_by: "operator" };
      board.routePuts = [...(board.routePuts ?? []), { mode: body.mode, local_model: body.local_model ?? null }];
    }
    const r = board.route;
    return json(res, 200, {
      mode: r.mode, effective_mode: r.mode === "auto" ? "cloud_with_local_fallback" : r.mode, local_model: r.local_model,
      local_models: ["inkling-2-mini-chat", "qwen3.8:27b"], modes: ["cloud_with_local_fallback", "local", "cloud_only", "auto"],
      cloud_available: true, sovereign_locked: false, source: "runtime", updated_at: r.updated_at, updated_by: r.updated_by,
    });
  }
  const decide = /^\/v1\/incidents\/([^/]+)\/actions\/([^/]+)\/(approve|reject)$/.exec(path);
  if (decide && req.method === "POST") {
    if (!board) return problem(req, res, 404, "not-found", "Not found");
    if (!key || !authed(board)) return problem(req, res, 401, "unauthorized", "Unauthorized");
    board.decisions.push({ incident: decide[1], action: decide[2], decision: decide[3] });
    return json(res, 200, { status: decide[3] === "approve" ? "approved" : "rejected" });
  }
  return problem(req, res, 404, "not-found", "Not found");
}

/** Like Caddy, the gateway stamps the visitor IP; tests get one per scenario so per-visitor limits never leak across tests. */
function fakeVisitorIp(req) {
  const seed = cookie(req, "mock_boards") ?? randomBytes(4).toString("hex");
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `10.${(h >>> 16) & 255}.${(h >>> 8) & 255}.${h & 255}`;
}

function proxy(req, res) {
  const forced = cookie(req, "mock_caps");
  const port = forced === "false" || forced === "true" ? CAP_APPS[forced] : APP_PORT;
  const upstream = http.request({ host: "127.0.0.1", port, path: req.url, method: req.method, headers: { ...req.headers, "x-falcon-client-ip": fakeVisitorIp(req) } }, (up) => {
    res.writeHead(up.statusCode ?? 502, up.headers);
    up.pipe(res);
  });
  upstream.on("error", () => {
    if (!res.headersSent) res.writeHead(502);
    res.end("app not reachable");
  });
  req.pipe(upstream);
}

http
  .createServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    // Server-side GET /v1/meta from a forced-capability app instance: /__caps/<mode>/v1/meta
    const forcedMeta = /^\/__caps\/(true|false)\/v1\/meta$/.exec(path);
    if (forcedMeta) return json(res, 200, { capabilities: Object.fromEntries(CAP_IDS.map((id) => [id, forcedMeta[1] === "true"])) });
    const run = path.startsWith("/__mock/") ? control(req, res, path) : path.startsWith("/v1/") ? api(req, res, path) : null;
    if (run) run.catch(() => { if (!res.headersSent) problem(req, res, 500, "internal", "Internal error"); else res.end(); });
    else proxy(req, res);
  })
  .listen(PORT, process.env.MOCK_HOST ?? "127.0.0.1", () => console.log(`mock gateway on :${PORT} → app :${APP_PORT}`));
