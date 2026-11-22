# ARCHITECTURE

```
                 ┌──────────── edge net ─────────────┐
 browser/PWA ──▶ │ gateway (Caddy TLS, CSP)          │ ◀── cloudflared tunnel (host)
 extension   ──▶ │   /        → web (Next.js PWA)    │
 police app  ──▶ │   /v1,/mcp → api, mcp             │
                 └──────────────┬────────────────────┘
                     app net    │
     ┌──────────────┬───────────┴──────┬──────────────┐
     │ api (FastAPI)│ worker (cascade) │ mcp (FastMCP)│ sentinel (LangGraph)
     └──────┬───────┴──────┬───────────┴──────┬───────┘
            │ data net     │ egress via proxy │
   postgres(pgvector)  redis(cache,streams)   egress-proxy ──▶ internet (RDAP, crt.sh, feeds, LLM APIs)
                                   ▲
            sandbox net:  sandbox (Playwright) ──▶ egress-proxy only
   host:  Ollama (OLLAMA_BASE_URL)            obs net: otel-collector → prometheus/loki/tracer → grafana, alertmanager
```

## Request flow (URL)
1. `POST /v1/check/url`: the API validates, rate-limits, assigns a `verdict_id` (ULID), puts a job on the `fl:jobs` stream, and returns `202` with the SSE URL. Single-flight: if a check of the same canonical URL is already in flight, the API attaches to that job.
2. The worker runs T0, T1 and T2, and T3 if needed. After each tier it publishes a partial verdict to `fl:verdict:<id>` (pub/sub), which the API relays to SSE as `event: verdict`.
3. The arbiter produces the final verdict. It is stored in Postgres (`verdicts`, `evidence`) and a `verdict.created` event goes to `fl:events`.
4. The Sentinel consumes `fl:events`, correlates and applies rules. If an incident results, the LangGraph triage runs and the incident is published to `fl:board`, then to SSE on the incident board and to Alertmanager.

Synchronous mode: `?wait=8` blocks up to 8 s and returns the best verdict so far, for simple clients and the MCP.

## Messages, emails and images
- **message**: normalise (Arabic, Arabizi), run rule features, embed with `qwen3-embedding:4b`, run kNN over `scam_scripts` (pgvector), then the quarantined extractor. Every URL found goes through the URL pipeline as a child check (H5).
- **email**: stdlib `email` parser with a size cap and no remote fetch. Checks: auth results, header mismatches, link text vs href, QR codes in images, attachment type and hash only. The body goes through the message pipeline.
- **image**: magic-byte check, QR decode (zxing-cpp or pyzbar), then OCR via the quarantined vision extractor. Extracted URLs and text go through the respective pipelines.

## Model router (`falcon_core/llm/router.py`)
- Roles are `extractor`, `investigator`, `responder`, `vision`, `sentinel`, `judge`. Each role maps to a cloud model and a local model.
- In sovereign mode, or when no `ANTHROPIC_API_KEY` is set, every role goes local. On a cloud error or timeout, the call falls back to local and increments `fl_llm_fallback_total`.
- Before any cloud call, inputs are redacted (phone numbers, Emirates ID, card numbers, emails) and spotlighted: untrusted text sits between `<<<UNTRUSTED:{nonce}>>>` markers and each line is datamarked with `^`.
- Output is schema-validated (pydantic) with one repair retry, then falls back to templates.
- Shadow mode: `FL_SHADOW_RATE` sends a fraction of traffic to the other route in the background, to measure `fl_route_agreement_ratio`.

## Data stores
- **Postgres + pgvector**:
  - checking and campaigns: `verdicts`, `evidence`, `scam_scripts` (embedding vector), `brands`, `incidents`, `incident_actions`
  - audit and access: `audit_log` (append-only; UPDATE and DELETE revoked from the app role), `api_keys` (argon2 hash), `reports`, `feedback`, `blocklist`
  - Sentinel state: `langgraph_checkpoints`
- **Redis**:
  - caches: `vc:<sha>` (verdict cache, TTL by verdict: dangerous 24h, suspicious 1h, no_warning 6h) and signal caches (`rdap:`, `crt:`)
  - feed mirror sets: `feed:openphish`
  - rate limits and single-flight locks
  - streams

## Sandbox
- A separate service with a warm pool of Chromium contexts. Every visit gets a fresh context, with downloads blocked, a 6 s total timeout, at most 10 redirects and a 5 MB response cap. Fonts and media are blocked unless a visual match is needed.
- The page is loaded twice for cloaking detection: once with an Android/Arabic profile, once desktop/English.
- The sandbox returns **features only**: form fields, form-action origins, script-post targets, hot-linked asset origins, title, visible text (≤ 4 KB, for the extractor), favicon and screenshot hashes, `dom_simhash` and the redirect chain. The screenshot is stored in `data/private/snapshots` (local) and served only to authenticated keys.
- Its networks are `sandbox` (peers: `egress-proxy`, plus the fixtures server under the `tools` profile) and `sandbox_ctl` (peer: `worker`). Both are `internal: true`, so there is no route to the internet or to any other service, and the sandbox is NOT on the observability network.
  - Docker networks are not directional, so the sandbox can open connections to `worker` on `sandbox_ctl`. The worker therefore listens there only for `/healthz`, `/readyz` and `/metrics` (including `/metrics/sandbox`), never for a job or control API.
  - The sandbox API requires a shared bearer token (`FL_SANDBOX_TOKEN`) on everything except the health probes, so a stray peer cannot drive visits.
  - Metrics: Prometheus scrapes the worker's `/metrics/sandbox`, which relays the sandbox's metrics over `sandbox_ctl`. Logs: Alloy tails container stdout through the Docker socket. Traces: the worker opens the spans around sandbox calls.
  - Acceptance check: from inside the sandbox container only `egress-proxy:3128` and `worker:8000` accept connections.
- The proxy blocks RFC1918, loopback, link-local, metadata and internal service names, and allows only ports 80 and 443.

## Code ownership
| Path | Owner |
|---|---|
| `packages/falcon_core/{contracts,scoring,cascade,llm,agent,tools}`, `services/worker` | builder-agent-core (sentinel-only tools: builder-sentinel) |
| `packages/falcon_core/scoring/params.yaml` | written **only** by builder-evals' `make fit-thresholds` |
| `packages/falcon_core/telemetry` | builder-observability |
| `services/fixtures` content (Falcon Demo Bank) | builder-sandbox |
| `packages/falcon_core/{signals,brands}` | builder-signals |
| `packages/falcon_core/security`, `services/egress`, `evals/redteam` | builder-security |
| `services/sandbox` | builder-sandbox |
| `services/sentinel` | builder-sentinel |
| `evals/` (except redteam) | builder-evals |
| `services/{api,mcp}`, compose, CI, Makefile | builder-platform |
| `infra/` | builder-observability |
| `web/`, `extension/` | builder-frontend |
| README, `submission/` | builder-docs |
