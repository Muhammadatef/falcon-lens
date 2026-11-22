# DECISIONS — one line each (date GST · who · decision · why)

## Owner inputs (2026-11-22)
- 2026-11-22 · owner · Repo `Muhammadatef/falcon-lens` is **public from the start**. The owner approved this explicitly, overriding the default "ask before public". Mitigation: gitleaks in pre-commit and CI, and live URLs, snapshots and logos only in gitignored `data/private/`.
- 2026-11-22 · owner · Public demo through a Cloudflare quick tunnel (`cloudflared`), installed with brew. No cloud spend. The Mac must stay on.
- 2026-11-22 · owner · ANTHROPIC_API_KEY will be provided in `.env`, so the cloud route is enabled.
- 2026-11-22 · owner · No Google Safe Browsing key and no URLhaus key, so both feeds are disabled and labelled "disabled". The blocklist baseline covers only enabled feeds.
- 2026-11-22 · owner · No Telegram, so alerts go to Grafana, Alertmanager and logs only.
- 2026-11-22 · owner · No team names yet, so the deck gets a placeholder team slide.

## Environment and models
- 2026-11-22 · L1 · The main session runs on **Opus 5.5** (`claude-opus-5-5`), not Fable 5.2 as the prompt states, because that is the model of this session. Roles are unchanged.
- 2026-11-22 · L1 · Host: Apple M5 Max, 128 GB, arm64, Docker 29.8.2, Ollama 0.40.13. All images must be multi-arch.
- 2026-11-22 · L1 · `qwen3.8:27b` is not on this Mac. The owner says it is on host "mirai", which isn't reachable from here (no DNS, mDNS, Tailscale or SSH entry). `OLLAMA_BASE_URL` is configurable, so pointing it at mirai switches models.
- 2026-11-22 · L1 · `ollama pull inkling-2-mini` fails on Ollama 0.40.13 ("model not found, download the latest version"). brew offers 0.40.17. The upgrade is pending owner OK because it restarts a shared Ollama.
- 2026-11-22 · L1 · Interim local model is `gemma3:27b` (completion and vision; **no native tools**). L4 bulk worker is `qwen3:4b`. Embeddings use `qwen3-embedding:4b`.
- 2026-11-22 · L1 · The investigator and Sentinel choose tools through **schema-validated JSON actions**, not native tool calling, so any local model works and provider differences don't leak into the loop. See ADR-001 and ADR-003.
- 2026-11-22 · L1 · `scripts/qwen_task.py` keeps the name from the spec but reads `FL_LOCAL_WORKER_MODEL`.
- 2026-11-22 · L1 · Inkling-2-Mini weights at `~/Models/Inkling-2-Mini` (Apache-2.0) are a candidate sovereign model once Ollama is upgraded. Its README warns of reasoning loops, so cap tokens and turns.

## Architecture
- 2026-11-22 · L1 · ADR-001: tiered cascade with a deterministic arbiter. The LLM is used only for the uncertain band and never sets the score.
- 2026-11-22 · L1 · ADR-002: LangGraph only in the Sentinel, langchain-core only as the interfaces, DSPy offline only.
- 2026-11-22 · L1 · ADR-005: Redis Streams is the event bus (already needed for cache). No Kafka.
- 2026-11-22 · L1 · Monorepo with a shared `packages/falcon_core` so worker, API, MCP and Sentinel share contracts and tools.
- 2026-11-22 · L1 · Gateway is Caddy (automatic local TLS, simple CSP headers). The cloudflared tunnel points at it.

## Verified versions
(filled from `docs/research/VERIFIED_VERSIONS.md` as each library is adopted)
- 2026-11-22 · L1 · **Incident**: the owner's real ANTHROPIC key had been written into `.env.example`. GitHub push protection blocked the push, so the key was never public. Moved to the gitignored `.env` (chmod 600), commit amended, reflog and objects purged. Added `.gitleaks.toml` with an `sk-ant-*` rule, because the default gitleaks rules missed the `sk-ant-usr` prefix.
- 2026-11-22 · L1 · Verified 2026-11-22 (details in docs/research/VERIFIED_VERSIONS.md):
  - anthropic 2.12.0
  - mcp 2.3.0 (`MCPServer`; the old `FastMCP` name is gone; static bearer done as middleware)
  - langgraph 1.2.24, langgraph-checkpoint-postgres 3.2.1, langchain-core 1.8.4
  - dspy 3.5.0
  - playwright 1.65.2 (`mcr.microsoft.com/playwright/python:v1.65.2-noble`)
  - fastapi 0.165.0 (native `fastapi.sse`), pydantic 2.14.4
  - psycopg 3.3.9, pgvector 0.5.1, tldextract 5.4.0 (`include_psl_private_domains=True`), whoisit 4.1.0, scikit-learn 1.9.1 (HistGradientBoosting)
  - next 16.4.6
- 2026-11-22 · L1 · Images (multi-arch): pgvector/pgvector:0.8.7-pg18-trixie, redis:8.8.4-alpine, prom/prometheus:v3.16.0, prom/alertmanager:v0.35.0, grafana/grafana:13.2.6, grafana/loki:3.7.10, grafana/alloy:v1.22.0 (Promtail is EOL), otel/opentelemetry-collector-contrib:0.165.0, caddy:2.11.9-alpine, arizephoenix/phoenix:version-22.0.1-nonroot (LLM tracer: a single container that accepts OTLP).
- 2026-11-22 · L1 · Egress proxy: a small custom Python CONNECT proxy, because tinyproxy and squid images are stale or amd64-only. It reuses the SSRF guard code (one implementation).
- 2026-11-22 · L1 · Models: claude-sonnet-5-5 ($2/$10 per MTok) and claude-haiku-5-5 ($0.10/$0.50) confirmed. Sonnet 5.5 rejects forced tool_choice and `thinking: disabled`. This doesn't affect us, because actions are JSON (ADR-001) and we use structured output with effort set low.
- 2026-11-22 · L1 · UTS #39 skeleton: implemented in-house from Unicode `confusables.txt` (vendored, with licence noted), because `confusable-homoglyphs` has no skeleton function.
- 2026-11-22 · L1 · OpenPhish community feed: the terms allow personal or research use, with no commercial use and no redistribution. This hackathon prototype is non-commercial research. We mirror it privately, never redistribute it (only defanged aggregates are public), and a production deployment needs an OpenPhish licence (noted in the README Roadmap).
- 2026-11-22 · L1 · ADP reporting channels: only what https://www.adpolice.gov.ae/en/ showed on 2026-11-22 is stored in `config/reporting_channels.yaml`: 999 (emergency), the Aman service (aman.adpolice.gov.ae, with 8002626 shown under it) and the complaints portal (cas.adpolice.gov.ae). The SMS 2828, the e-mail address and "Ecrime" are UNVERIFIED and **not** shown.
- 2026-11-22 · L1 · iOS: no PWA share_target support (WebKit bug 194593), so iPhone uses a Shortcut (P1). Android Chrome supports share_target once the PWA is installed.
- 2026-11-22 · L1 · Chrome MV3: `webNavigation` plus redirect to an extension warning page (web_accessible_resources) for automatic checks, with host permission only for the API origin.
- 2026-11-22 · L1 · `inkling-2-mini` is in the Ollama library (vision, tools, thinking, about 20 GB) but needs a newer Ollama. Upgrade pending owner OK.

## Platform skeleton (T-001, builder-platform)
- 2026-11-22 · builder-platform · Tooling versions used: uv 0.13.7 (image `ghcr.io/astral-sh/uv:0.13.7`), Python 3.12.12 (`python:3.12.12-slim-trixie`), ruff 0.17.6, mypy + pytest + pytest-asyncio + jsonschema + referencing (resolved in uv.lock), hatchling build backend.
- 2026-11-22 · builder-platform · Runtime libs resolved in uv.lock: fastapi 0.165.x, uvicorn 0.54.x, pydantic 2.14.x, pydantic-settings, prometheus-client, redis-py (sentinel only).
- 2026-11-22 · builder-platform · Web: next 16.4.6, react 19.3.1, pnpm 12.21.0, TypeScript 5.9, image `node:24.15-alpine`.
- 2026-11-22 · builder-platform · Other images: `caddy:2.11.9-alpine`, `nginxinc/nginx-unprivileged:1.29-alpine` (fixtures, minor-pinned), `alpine:3.22` (base for the re-packaged otel-collector and Loki images), `mcr.microsoft.com/playwright/python:v1.65.2-noble` (sandbox).
- 2026-11-22 · builder-platform · Pre-commit and CI pins: ruff-pre-commit v0.17.6, gitleaks v8.30.1, pre-commit-hooks v6.0.0, trivy-action 0.33.1, actions checkout@v4, setup-uv@v6, pnpm/action-setup@v4, setup-node@v4.
- 2026-11-22 · builder-platform · The otel-collector-contrib and Loki images are scratch/distroless (no shell or wget), so no container HEALTHCHECK is possible. They are re-packaged in `infra/otel/Dockerfile` and `infra/loki/Dockerfile` (same upstream binary copied onto alpine:3.22, non-root uid 10001). Phoenix is checked with its bundled `/usr/bin/python3.13`; Alloy through bash `/dev/tcp`.
- 2026-11-22 · builder-platform · Networks: `app` is NOT internal, because the host Ollama (`host.docker.internal`) and cloud LLM calls must stay reachable. `data`, `sandbox` and `observability` are internal. Added an internal `sandbox_ctl` network (worker to sandbox) so the `sandbox` network holds only sandbox + egress-proxy (+ tools-profile fixtures). egress-proxy reaches the internet through `app`. Forcing app services through egress-proxy is left to builder-security.
- 2026-11-22 · builder-platform · The sandbox also joins the internal `observability` network so Prometheus can scrape it. That trades some isolation for metrics; builder-sandbox should revisit it (e.g. push metrics).
- 2026-11-22 · builder-platform · Gateway CSP keeps `script-src 'unsafe-inline'` because Next.js emits inline hydration scripts. Moving to nonces is later hardening.
- 2026-11-22 · builder-platform · Alloy mounts `/var/run/docker.sock` read-only and runs as root to tail container logs (obs profile only). Accepted for a local demo stack, not for a shared host.
- 2026-11-22 · builder-platform · The egress stub `guard.check` is fail-closed (ports 80/443 and `ipaddress.is_global` only) until builder-security plugs the real SSRF guard into `services/egress/src/falcon_egress/guard.py`.
- 2026-11-22 · builder-platform · `DATABASE_URL` is composed in docker-compose.yml from POSTGRES_*, so a changed password cannot drift from the value in `.env`.
- 2026-11-22 · builder-platform · Incident pydantic model is root-strict only (nested models permissive), matching the schema, which sets `additionalProperties: false` only at the root.
- 2026-11-22 (builder-platform, T-013): fastapi 0.165.0 native SSE verified by reading `fastapi/sse.py`: `@app.get(..., response_class=EventSourceResponse)` on an async-generator endpoint yielding `ServerSentEvent(data=..., event=..., id=..., comment=...)`; data is always JSON-encoded; built-in keepalive `: ping` every 15 s. sse-starlette not needed.
- 2026-11-22 (T-013): added deps redis>=5.2 (redis-py asyncio), asyncpg 0.32.0, python-multipart 0.0.34, python-ulid 4.2.0; dev: fakeredis, pyyaml. Exact versions are pinned in uv.lock.
- T-013: rate limit is a fixed one-minute window counter (Redis INCR+EXPIRE), not a true token bucket: no Lua needed, fakeredis-testable; burst up to 2x at a window edge is accepted. Applies to POST /v1/check/* only (the cost-bearing calls).
- T-013: default FL_RATE_LIMIT_PER_IP_PER_MIN raised 30 -> 60 (settings, .env.example, compose) to match the T-013 acceptance ("61st request/min -> 429").
- T-013: client IP = socket peer; the last X-Forwarded-For hop is trusted only when the peer is a private/loopback address (the gateway). Public peers cannot spoof it.
- T-013: POST /v1/check/* requires Content-Length (411 otherwise) and rejects over-limit bodies before parsing (413); the per-field caps (URL 4 KB, message 8 KB, email 2 MB, image 5 MB) are enforced again after parsing.
- T-013: authenticated = `X-API-Key` or `Authorization: Bearer` equal to FL_SANDBOX_API_KEY (constant-time). Argon2 per-key auth is a later card. Only authenticated callers may set `X-Falcon-Source` and receive `screenshot_url`.
- T-013: SSE max lifetime 120 s, heartbeat comment every 5 s; unknown verdict ids give 404 problem+json before the stream starts. No Last-Event-ID resume: every connect replays the latest known partial.
- T-013: single-flight and verdict cache apply to all input types (fingerprint = sha256 of type + canonical content); a cache hit returns 200 with the existing verdict and header `X-Verdict-State: cached`.
- T-013: CORS allows only FL_PUBLIC_BASE_URL plus origins in env FL_CORS_EXTENSION_ORIGINS (comma-separated, e.g. chrome-extension://<id>).
- T-013: contracts/openapi.yaml is generated by scripts/gen_openapi.py (`make openapi`); CI and a pytest compare it with the code. Committed by builder-platform with L1 permission for this card.
- T-015: scripts/smoke.sh needs fixture pages `http://fixtures/phish/` and `http://fixtures/official/` in the tools profile (builder-sandbox content); override with FL_SMOKE_PHISH_URL / FL_SMOKE_OFFICIAL_URL. Feed injection seeds `feed:openphish` with sha256 hex of the canonical URL and of the host (hashes only, never plaintext), keyed with the API's canonicalisation.
- T-015: FL_SMOKE_FAKE_WORKER=1 uses the fake-worker test double (compose profile smoke-fake) and prints "NOT a G1 result"; worker-metric checks (4b, 8) are SKIPPED in that mode. The real `make smoke` has no double.
