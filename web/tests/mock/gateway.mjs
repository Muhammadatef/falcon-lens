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
const CAP_IDS = ["message_check", "email_check", "image_check", "injection_defence", "investigator", "sentinel_agent", "rest_api", "mcp", "stix", "t1_measured_model", "url_check", "brand_check", "pipeline", "audit_log", "sentinel_rules", "observability", "sovereign", "pwa", "dspy_compiled_prompts", "llm_tracing"];
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
  if (path === "/__mock/boards" && req.method === "GET") {
    const b = boards.get(new URL(req.url, "http://x").searchParams.get("key") ?? "");
    return b ? json(res, 200, { decisions: b.decisions }) : problem(req, res, 404, "not-found", "no board");
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

async function api(req, res, path) {
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

  if (path === "/v1/campaigns" && req.method === "GET") {
    if (!board || board.campaigns == null) return problem(req, res, 404, "not-found", "Not found");
    return json(res, 200, { items: board.campaigns });
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
  const decide = /^\/v1\/incidents\/([^/]+)\/actions\/([^/]+)\/(approve|reject)$/.exec(path);
  if (decide && req.method === "POST") {
    if (!board) return problem(req, res, 404, "not-found", "Not found");
    if (!key || !authed(board)) return problem(req, res, 401, "unauthorized", "Unauthorized");
    board.decisions.push({ incident: decide[1], action: decide[2], decision: decide[3] });
    return json(res, 200, { status: decide[3] === "approve" ? "approved" : "rejected" });
  }
  return problem(req, res, 404, "not-found", "Not found");
}

function proxy(req, res) {
  const forced = cookie(req, "mock_caps");
  const port = forced === "false" || forced === "true" ? CAP_APPS[forced] : APP_PORT;
  const upstream = http.request({ host: "127.0.0.1", port, path: req.url, method: req.method, headers: req.headers }, (up) => {
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
