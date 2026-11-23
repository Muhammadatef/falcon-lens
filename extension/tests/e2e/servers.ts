/**
 * Local servers for the extension e2e tests. Both bind to 127.0.0.1 only.
 *
 *  - Mock API (port 8765): the subset of contracts/openapi.yaml the extension calls.
 *  - Fixture site (port 8766): answers for every *.test host (Chromium is started with
 *    --host-resolver-rules so *.test resolves to 127.0.0.1). Pages carry the label
 *    "TEST FIXTURE, not a real site", use only the invented brand "Falcon Demo Bank", and contain
 *    no form that posts anywhere.
 */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

export const API_PORT = 8765;
export const SITE_PORT = 8766;

export const XSS_REASON = '<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>';

export interface ApiCall {
  method: string;
  path: string;
  headers: IncomingMessage["headers"];
  body: string;
}

const ULID = "01JD3Z8Q4T6V8X0Z2B4D6F8H0K";

function verdict(word: "dangerous" | "suspicious" | "no_warning_signs", final: boolean, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: "1.0",
    verdict_id: `vd_${ULID}`,
    input_type: "url",
    verdict: word,
    risk_score: word === "dangerous" ? 94 : word === "suspicious" ? 58 : 6,
    calibrated_probability: word === "dangerous" ? 0.97 : 0.04,
    impersonated_brand:
      word === "dangerous"
        ? { brand_id: "falcon_demo_bank", name_ar: "بنك الصقر التجريبي", name_en: "Falcon Demo Bank", official_domains: ["falcon-demo-bank.test"] }
        : null,
    evidence: [],
    reasons:
      word === "dangerous"
        ? [
            { ar: "الصفحة تطلب بيانات الدخول وليست على النطاق الرسمي للبنك.", en: "The page asks for login details and is not on the bank's official domain.", evidence_ids: ["ev_fixture0001"] },
            { ar: XSS_REASON, en: XSS_REASON, evidence_ids: ["ev_fixture0002"] },
          ]
        : [],
    actions: {
      now: { ar: ["أغلق الصفحة ولا تُدخل أي بيانات."], en: ["Close the page and do not enter any details."] },
      if_already_acted: { ar: [], en: [] },
      report: { ar: "", en: "" },
      caution: { ar: ["تأكد من العنوان قبل إدخال أي بيانات."], en: ["Check the address before you enter anything."] },
    },
    tier_reached: "T2",
    model_route: "none",
    degraded: false,
    final,
    source: "fixture",
    latency_ms: 12,
    created_at: "2026-11-22T12:00:00Z",
    ...extra,
  };
}

/** The mock decides by a word in the checked host, so each test picks its scenario by URL. */
function scenario(url: string): { status: number; body: unknown } {
  const host = (() => {
    try {
      return new URL(url).hostname;
    } catch {
      return "";
    }
  })();
  if (host.includes("unreachable")) return { status: 503, body: { type: "about:blank", title: "Dependency unavailable", status: 503 } };
  if (host.includes("pending")) return { status: 202, body: { verdict_id: `vd_${ULID}`, events_url: `/v1/verdicts/vd_${ULID}/events`, status_url: `/v1/verdicts/vd_${ULID}` } };
  if (host.includes("partner")) return { status: 200, body: verdict("no_warning_signs", true) };
  const official = host === "falcon-demo-bank.test" || host.endsWith(".falcon-demo-bank.test");
  if (host.includes("falcon-demo-bank") && !official) return { status: 200, body: verdict("dangerous", true) };
  return { status: 200, body: verdict("no_warning_signs", true) };
}

export function startApi(calls: ApiCall[]): Promise<Server> {
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c: Buffer) => (body += c.toString()));
    req.on("end", () => {
      const path = req.url ?? "";
      calls.push({ method: req.method ?? "", path, headers: req.headers, body });
      const json = (status: number, data: unknown): void => {
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
      };
      if (req.method === "GET" && path === "/v1/version") return json(200, { service: "falcon-api", api: "v1", env: "test" });
      if (req.method === "POST" && path.startsWith("/v1/check/url")) {
        let url = "";
        try {
          url = String((JSON.parse(body) as { url?: unknown }).url ?? "");
        } catch {
          return json(422, { title: "Invalid request", status: 422 });
        }
        const s = scenario(url);
        return json(s.status, s.body);
      }
      // Status of an accepted job: still running, best partial so far says "no warning signs".
      if (req.method === "GET" && path.startsWith("/v1/verdicts/")) return json(202, verdict("no_warning_signs", false));
      return json(404, { title: "Not found", status: 404 });
    });
  });
  return new Promise((resolve) => server.listen(API_PORT, "127.0.0.1", () => resolve(server)));
}

const page = (title: string, body: string, csp: string): string => `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<title>${title}</title></head>
<body>
<p id="fixture-label"><strong>TEST FIXTURE, not a real site.</strong> Served on 127.0.0.1 for automated tests only.</p>
${body}
</body></html>`;

const STRICT = "default-src 'none'; style-src 'none'; script-src 'none'";

/**
 * A real remote lookalike host answers after network latency. A loopback server answers in well
 * under a millisecond, which lets the risky document commit before the extension's tabs.update
 * lands: a test-bench artefact that made "the lookalike never rendered" flaky (~7%). The delay
 * models the internet, not the guard, so the assertion stays exactly as strict.
 */
const REMOTE_LATENCY_MS = 400;
const isRemoteLookalike = (host: string): boolean => host.endsWith(".secure-verify.test");

export function startSite(hits: string[]): Promise<Server> {
  const server = createServer((req, res) => {
    const host = (req.headers.host ?? "").split(":")[0] ?? "";
    hits.push(host + (req.url ?? ""));
    if (isRemoteLookalike(host)) setTimeout(() => respond(host, res), REMOTE_LATENCY_MS);
    else respond(host, res);
  });
  return new Promise((resolve) => server.listen(SITE_PORT, "127.0.0.1", () => resolve(server)));
}

function respond(host: string, res: ServerResponse): void {
  {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
    if (host === "webmail.test") {
      // Stands in for a webmail app. Strict CSP on purpose: the hover badge must not depend on
      // the page allowing inline styles or scripts.
      res.end(
        page(
          "Mock webmail (TEST FIXTURE)",
          `<h1>Inbox (mock)</h1>
<p>From: notices@falcon-demo-bank.secure-verify.test</p>
<p>Your Falcon Demo Bank account needs attention:
<a id="bad-link" href="http://falcon-demo-bank.secure-verify.test:${SITE_PORT}/login">open the notice</a></p>
<p>Newsletter: <a id="plain-link" href="http://heron-sample-shop.test:${SITE_PORT}/news">read more</a></p>
<p>Unreachable check: <a id="offline-link" href="http://unreachable-notes.test:${SITE_PORT}/">notes</a></p>`,
          STRICT,
        ),
      );
      return;
    }
    res.end(
      page(
        "Falcon Demo Bank (TEST FIXTURE)",
        `<h1 id="fixture-title">Falcon Demo Bank demo page</h1>
<p>This input belongs to no form and is sent nowhere.</p>
<label>Demo field <input id="demo-input" type="text" autocomplete="off"></label>`,
        STRICT,
      ),
    );
  }
}
