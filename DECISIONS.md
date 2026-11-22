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
- 2026-11-22 · builder-platform · Review round 1 fix: the sandbox is NOT on `observability` (supervisor measured 14 reachable internal endpoints). Only `sandbox` + `sandbox_ctl`. The worker relays sandbox metrics at `/metrics/sandbox`; the sandbox API needs `FL_SANDBOX_TOKEN`; the worker exposes only health and metrics on `sandbox_ctl`.
- 2026-11-22 · builder-platform · falcon-core runtime deps added for the feature PRs: httpx >=0.28.1,<0.29, httpcore >=1,<2, tldextract >=5 (offline: no cache dir, no suffix-list URLs), pyyaml >=6; dev: types-PyYAML, pytest-cov. Ruff line-length is 120; mypy is strict on `packages/falcon_core/src` only (tests are not type-checked because several test dirs have a `conftest.py`).
- 2026-11-22 · builder-platform · Images carry `data/brands.yaml` and `config/reporting_channels.yaml` (`FALCON_BRANDS_YAML`, `FL_REPORTING_CHANNELS`); `.dockerignore` keeps all other `data/*` (notably `data/private`) out of every build context.
- 2026-11-22 · builder-platform · `make eval-gate` prints an explicit SKIPPED notice (never a pass) while `evals/baseline.json` is absent, and runs `make eval` once it exists. The `eval-gate` CI job is not a required check.
- 2026-11-22 · builder-platform · Host ports come from `FL_GATEWAY_PORT`, `FL_PROMETHEUS_PORT`, `FL_GRAFANA_PORT`; parallel stacks use `COMPOSE_PROJECT_NAME`. `FL_LOCAL_MODEL` default follows `.env.example` (`inkling-2-mini-chat`).
- 2026-11-22 · builder-platform · CI actions are pinned by full commit SHA; CI needs no secrets so fork PRs are safe. Branch protection is scripted in `scripts/protect_main.sh` (owner/L1 runs it).
- 2026-11-22 · builder-platform · Web tooling: eslint 9 + typescript-eslint 8, vitest 3 (pnpm 12 needs `allowBuilds` in `web/pnpm-workspace.yaml`).
- 2026-11-22 · builder-platform · Gateway CSP keeps `script-src 'unsafe-inline'` because Next.js emits inline hydration scripts. Moving to nonces is later hardening.
- 2026-11-22 · builder-platform · Alloy mounts `/var/run/docker.sock` read-only and runs as root to tail container logs (obs profile only). Accepted for a local demo stack, not for a shared host.
- 2026-11-22 · builder-platform · The egress stub `guard.check` is fail-closed (ports 80/443 and `ipaddress.is_global` only) until builder-security plugs the real SSRF guard into `services/egress/src/falcon_egress/guard.py`.
- 2026-11-22 · builder-platform · `DATABASE_URL` is composed in docker-compose.yml from POSTGRES_*, so a changed password cannot drift from the value in `.env`.
- 2026-11-22 · builder-platform · Incident pydantic model is root-strict only (nested models permissive), matching the schema, which sets `additionalProperties: false` only at the root.

## Docs and README (builder-docs)
- 2026-11-22 · builder-docs · README diagrams are hand-written animated SVGs (`docs/assets/*.svg`): CSS `@keyframes` and CSS motion path (`offset-path`) only, no `<script>`, no `foreignObject`, no external resources, system font stacks. GitHub shows README images through `<img>`, where scripts and external fetches do not run but CSS animation does (checked 2026-11-22 against GitHub community discussions and public write-ups; GitHub has no official page on this).
- 2026-11-22 · builder-docs · Each SVG honours `prefers-reduced-motion: reduce` (animations off, packets hidden) and hides motion-path packets under `@supports not (offset-path: path(...))`. The static frame stays fully readable.
- 2026-11-22 · builder-docs · Diagram palette is the Night theme from `web/design/tokens.css` (frontend design branch). The mark (ring, pupil, brow stroke, malar stripe) follows `docs/DESIGN.md` on that branch. No police or government marks.
- 2026-11-22 · builder-docs · Diagram examples use only "Falcon Demo Bank" and defanged hosts under the reserved `.example` TLD. Evidence rows show `+w` placeholders, not weights, so no number can drift from `docs/SCORING.md`.
- 2026-11-22 · builder-docs · `scripts/readme_metrics.py` assumes published artifacts are JSON objects named so that the newest sorts last (`<timestamp>.json`), with numbers under a top-level `metrics` key. It flattens that key verbatim and copies `git_sha`, `dataset_hash`, `created_at`/`timestamp`, `seeds`, `models`/`model_ids` when present. The artifact schema is not fixed yet (T-023); builder-evals should confirm or the script follows their schema.
- 2026-11-22 · builder-docs · README feature status uses four labels (merged, scaffold, in progress, planned) derived from `STATUS.md`, the branch contents and the open feature branches. Budgets and rule thresholds quoted in the README and diagrams are design parameters from the ADRs and SCORING.md, not measurements.
- 2026-11-22 · builder-docs · Preview renders used Playwright (Python, latest via `uv run --with playwright`, not added to the lockfile) with the locally cached Chromium 159. Dev-time tool only; nothing shipped depends on it.

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
## Security (builder-security)
- 2026-11-22 · builder-security · Verified httpx **0.28.1** and httpcore **1.0.9** (PyPI and the docs at python-httpx.org/advanced/extensions and encode.io/httpcore/network-backends, plus the installed source). The guard uses only httpx and the stdlib. No dnspython: `loop.getaddrinfo` is the default resolver and can be injected for tests.
- 2026-11-22 · builder-security · IP pinning: the request goes to the checked IP literal, with `Host` set to the hostname and the `sni_hostname` extension set, so TLS still verifies the hostname. Defence in depth: the httpcore network backend refuses any non-IP or disallowed connect.
- 2026-11-22 · builder-security · httpx 0.28.1 does not expose `network_backend`, so `security/http.py` replaces the private `AsyncHTTPTransport._pool`. `test_transport_pool_uses_guarded_backend` pins this, so an httpx upgrade fails loudly.
- 2026-11-22 · builder-security · httpcore 1.0.9 ignores `sni_hostname` inside CONNECT tunnels (it uses the origin host). So in proxy mode the client keeps the hostname and pre-checks each hop, and the egress proxy re-resolves, re-checks and pins.
- 2026-11-22 · builder-security · If any record in a DNS answer is disallowed, the whole host is blocked, so a mixed public and private answer cannot win.
- 2026-11-22 · builder-security · Non-canonical numeric hosts (decimal, octal, hex, short forms such as 127.1) are always blocked, even when they decode to a public IP. Legitimate links don't use them.
- 2026-11-22 · builder-security · Userinfo (`@` in the authority) is always blocked, even for public hosts.
- 2026-11-22 · builder-security · Ports 80 and 443 are allowed for either scheme. Every other port is blocked.
- 2026-11-22 · builder-security · Only GET and HEAD are allowed, because the checker never submits anything. 303 changes the method to GET.
- 2026-11-22 · builder-security · Special-use and internal suffixes are blocked: localhost, local, internal, lan, home.arpa, test, example, invalid, onion, svc, cluster.local and others, plus every single-label name. The `falcon-demo-bank.test` fixture needs an explicit `GuardPolicy(allow_hosts=...)`, and production leaves that empty.
- 2026-11-22 · builder-security · IPv6-embedded IPv4 (mapped, 6to4, NAT64 64:ff9b::/96, IPv4-compatible) is unwrapped and judged as IPv4. Teredo and other 2001::/23 addresses, plus anything outside 2000::/3, are blocked.
- 2026-11-22 · builder-security · A body over max_bytes (hard cap 5 MB, after decoding) raises `SSRFBlocked(response_too_large)` instead of being truncated. Only gzip and deflate are requested and decoded, with bounded zlib output, and any other encoding gives `FetchFailed(unsupported_encoding)`.
- 2026-11-22 · builder-security · The caller can lower max_bytes or max_redirects but not raise them: values are clamped to 5 MB and 10. Keep-alive is off, so every hop gets a freshly pinned socket.
- 2026-11-22 · builder-security · The `on_block(reason)` hook is per-client, with a process-wide default set through `set_default_on_block`. Hook exceptions are logged and swallowed. T-014 wires it to `fl_ssrf_blocked_total{reason}` using `BlockReason` values as the labels.
- 2026-11-22 · owner · All frontend work (design vision, layout, palette, typography, motion, PWA, boards, extension UI) is led by **Fable 5.2**: `builder-frontend` now runs on `model: fable`, overriding the spec's Sonnet. The owner asked for a niche, state-of-the-art site with rich animated visuals.
- 2026-11-22 · owner · Approved the Ollama upgrade 0.40.13 → 0.40.17 (brew; service restarted) and Inkling-2-Mini as the local model, pending the capability check.
- 2026-11-22 · L1 · OpenPhish (checked by builder-evals at openphish.com/terms.html): the feed is the GitHub raw `public_feed/main/feed.txt`, updated every 12 h. Terms allow personal or academic research only; commercial use (including security operations) and redistribution need written consent. Decisions:
  - (a) The public manifest is **hash-only**: no URLs, defanged or not.
  - (b) OpenPhish is used for the research or eval dataset and for the non-commercial hackathon prototype. A production or police deployment needs an OpenPhish licence, and the README says so.
  - (c) The feed has no per-entry timestamps, so `first_seen` = poll time.
- 2026-11-22 · L1 · `first_poll`: 300 rows at 2026-11-22 ~16:00 GST. Next poll is allowed about 12 h later, so the loop runs in the background.
- 2026-11-22 · L1 · **Local model = `inkling-2-mini-chat`**, imported from the owner's `~/Models/Inkling-2-Mini` with a hand-written chat template (infra/ollama/). Smoke test: valid JSON, correct Arabic summary, and it flagged an embedded "ignore instructions" injection rather than obeying it. About 4.7 s warm, about 50 s cold. No structured-output support, so JSON is prompt-level plus validation and repair. Vision stays on gemma3:27b until tested. L4 worker stays on qwen3:4b (fast bulk).
- 2026-11-22 · L1 · Sentinel windows accepted: R2 is 7 days, R4 is 30 days. Event payload documents optional `previous_verdict` and `script_fingerprint`.
- 2026-11-22 · L1 · SCORING updates from PR #5 and #7: `url.data_uri` +2.0; `message|email.link_verdict` is informational and drives H5; weights scale by confidence; draft ε, θ, H3 cap and intercept accepted; precedence degraded > H3 > H1/H4/H6; typosquat length tiers accepted.
- 2026-11-22 · L1 · Sentinel incident ids must be **canonical**, independent of arrival order. The seed is rule_id + correlation-group key + the earliest `occurred_at` among the group's qualifying events, recomputed when the group changes. The id is kept stable once published, and later merges alias the original.
- 2026-11-22 · L1 · Repo recreate in progress: the first public repo had a commit with defanged feed URLs (PR #1). The owner chose delete-and-recreate. Clean branches are backed up in `data/private/repo-backup/` (bundle plus keep/* branches).
- 2026-11-22 · L1 · The supervisor role may run as up to two parallel instances, each on a separate PR set, for throughput before the deadline. Approval rules are unchanged.
- 2026-11-22 · owner · Collaborator @Abdulrahman-alseiari invited with write access. Human task board is in docs/CONTRIBUTOR_TASKS.md (Arabic review, domain verification, data audits, device QA, iOS Shortcut).
- 2026-11-22 · L1 · Message, email and image evidence names were added to SCORING §2 (PR feat/signals-message).
- 2026-11-22 · L1 · CONTRACTS invariant 5 (defang) applies to attacker or input URLs. **Official reporting channels from config/reporting_channels.yaml are exempt**: they're shown as plain text and never auto-linked.
- 2026-11-22 · L1 · Public OpenPhish manifest domain and URL hashes become **HMAC-SHA256 keyed** with a local secret `data/private/hash.key`, generated on first run and never committed. The same key gives stable grouping for splits.
- 2026-11-22 · L1 · The synthetic batch qwen-msg-001 was REJECTED by the supervisor (31/32 wrong). The re-run uses `inkling-2-mini-chat` (not qwen3:4b), with script fixes: language verified by character-script detection, allowlist for links and phones. The demo brand Arabic name is «بنك الصقر التجريبي» everywhere.
- 2026-11-22 · owner · The owner merged PRs #1, #2, #3 and #5 on GitHub before supervisor approval. The review findings in reviews/PR-4/5/6 are tracked as follow-up fix PRs.

## T-011 arbiter (builder-agent-core, feat/core-arbiter)
- 2026-11-22 · agent-core · Versions used (PyPI checked 2026-11-22): PyYAML 6.0.4 (`yaml.safe_load` only), pytest 9.2.0, jsonschema 4.26.0 (optional, schema tests skip without it), ruff 0.17.6, mypy 2.4.1 + types-PyYAML 6.0.12.20261122.
- 2026-11-22 · agent-core · Branch is `feat/core-arbiter` per the dispatcher (TASKS.md says `feat/scoring-arbiter`). Scope is H1–H6 (the dispatcher widened the card's H1–H4).
- 2026-11-22 · agent-core · `scoring/params.yaml` was created by hand with the SCORING.md draft values, as the dispatcher instructed, and is labelled `draft: true`. From now on only `make fit-thresholds` writes it.
- 2026-11-22 · agent-core · No `falcon_core/__init__.py` in this PR. It is a PEP 420 namespace package, to avoid a conflict with T-001's skeleton.
- 2026-11-22 · agent-core · Evidence in families url/domain/reputation feeds `p_clf`. Only the other families (page, visual, brand, message, email, image, injection, llm) go into the log-odds adjustment, so nothing is counted twice when a fitted `p_clf` is passed.
- 2026-11-22 · agent-core · T-022's fitted classifier must include reputation hits as features. Otherwise a stale (non-H2) feed hit adds nothing once `p_clf` is fitted.
- 2026-11-22 · agent-core · Draft classifier when `p_clf=None`: `logit = -2.2 + Σ w·c` over url/domain/reputation evidence, using the SCORING §2 weights. The prior is about 0.10. The result is flagged `p_clf_draft=True`.
- 2026-11-22 · agent-core · `Evidence.weight` = `w·c`, the log-odds contribution after confidence and the message-rule cap. It is also filled for T1 families as attribution for ordering reasons.
- 2026-11-22 · agent-core · The `registry.verified_official` −4.0 trust weight counts only when H3 holds. With open-redirect abuse or a feed hit it is 0, so an abused official redirector can't lower the score. **Accepted: SCORING §6.**
- 2026-11-22 · agent-core · Negative weights are zeroed for evidence from `llm*` or `user` sources and from the llm/injection families. Evidence whose family doesn't match its signal prefix gets weight 0 and triggers no rule. This is the "injection can only raise risk" guard.
- 2026-11-22 · agent-core · H3 overrides any co-firing H1/H4/H6 floor, which keeps zero `dangerous` on verified-official. **Accepted: SCORING §6 precedence.** The overridden rules are reported in `suppressed_rules`. H3 applies only when `input_type=url`.
- 2026-11-22 · agent-core · The H3 cap sets p ≤ 0.05 (draft), so the score matches the capped verdict. Floors: H1 p ≥ 0.95; H2/H4/H5 p ≥ τ_high; H6 p ≥ τ_low.
- 2026-11-22 · agent-core · H1 θ is 0.70 (draft, **accepted by L1, SCORING §6**) on the `brand.claimed_not_owned` confidence. "Payment request" = `message.rule.payment`. If the caller passes `registrable_domain` + `verified_domains`, both H1 and H3 are cross-checked against the registry.
- 2026-11-22 · agent-core · H2 requires an explicit `observed.fresh=true` or `observed.feed_age_s` < 21600, plus `match` ∈ {url, host} when `match` is present. A feed hit with no freshness info is not H2, but its +6.0 weight still applies.
- 2026-11-22 · agent-core · H4 = `page.cross_origin_post` with `bot=true` or a bot/webhook `target_kind`, AND either `credentials=true` or a present `page.cred_form`.
- 2026-11-22 · agent-core · H5 is driven by new evidence `message.link_verdict` / `email.link_verdict` (`observed.verdict`), weight 0. **Accepted: in SCORING §2.**
- 2026-11-22 · agent-core · H6 impersonation = `message.rule.authority` | `email.display_name_impersonation` | `brand.claimed_not_owned`.
- 2026-11-22 · agent-core · Degraded = an errored T0/T1 evidence item, or `ctx.extra_degraded_reasons` from the cascade. T2 errors degrade only if the cascade passes a reason. `p` is not inflated; only the shown verdict moves to suspicious. This also applies over H3 (CONTRACTS invariant 4). **Accepted: degraded > H3, SCORING §6.**
- 2026-11-22 · agent-core · Cascade ε_low = 0.05 and ε_high = 0.98 are draft values (SCORING gives none). **Accepted by L1, SCORING §6.** "Brand conflict" = any present homograph/typosquat/combosquat/brand-in-path/claimed_not_owned/favicon-match evidence.
- 2026-11-22 · agent-core · Template reasons: the degraded reason comes first when it caused the verdict, then hard-rule reasons, then by |w| (max 3). `no_warning_signs` shows trust reasons only, and risk verdicts show risk reasons only.
- 2026-11-22 · agent-core · Report channels are shown only when the config has an https `source_url` and an ISO `retrieved_at`. Otherwise the config's `generic_fallback` is used, then the i18n generic line.
- 2026-11-22 · agent-core · Signal errors `feed_disabled` and `rdap_unsupported_tld` (params `informational_errors`) are expected configuration states, not failures: weight 0, the verdict is not degraded, and no reason is generated. Any other T0/T1 error still degrades (L1 instruction).
- 2026-11-22 · agent-core · `email.attachment` gets +1.5 when `observed.risky` is true or `observed.detected_type` is executable/script-like (exe, elf, macho, lnk, msi, jar, script, js, vbs, bat, cmd, ps1, hta, html, ole2). Otherwise it is 0. Present `email.invalid` / `image.invalid` evidence marks the verdict degraded (`invalid_input:<signal>`).
- 2026-11-22 · agent-core · Official reporting channels are passed through un-defanged, per L1's invariant-5 exemption; a test pins this. `pyyaml>=6` was added to falcon-core deps (it was used on main but not declared) and `types-PyYAML` to the dev group.
## Observability metrics, dashboards, alerts (T-014, builder-observability)
- 2026-11-22 · builder-observability · Versions used: opentelemetry-sdk 1.45.2 + opentelemetry-exporter-otlp-proto-grpc 1.45.x (gRPC, matches the existing `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`), prometheus-client (uv.lock), pyyaml 6.0.4 (dev, tests only), Playwright 1.65.2 image used only for dashboard screenshots. Alertmanager telegram_configs fields verified at prometheus.io/docs/alerting/latest/configuration (bot_token_file, chat_id_file, parse_mode, message, send_resolved).
- 2026-11-22 · builder-observability · The metric registry is `falcon_core.telemetry.metrics.REGISTRY` (path per docs/OBSERVABILITY.md, not the `obs/` path in the T-014 card); `falcon_core.service` /metrics now renders it next to the per-service registry. `falcon_core.logging` is a shim over `falcon_core.telemetry.logging`.
- 2026-11-22 · builder-observability · `fl_llm_tokens_total{model,role}` counts input + output tokens together (the contract has no direction label).
- 2026-11-22 · builder-observability · Assumption: the end-to-end latency is observed as `fl_stage_latency_seconds{stage="total"}`; the SLO burn-rate rules and dashboards depend on it. builder-agent-core must emit that stage.
- 2026-11-22 · builder-observability · Label values follow the contracts: `tier` = T0..T3 (uppercase, verdict `tier_reached`) and `route` = cloud|local|none (verdict `model_route`); `record_verdict` rejects anything else. The AI dashboard's T3 panel uses `tier="T3"`.
- 2026-11-22 · builder-observability · Alert thresholds are starting points, not tuned: feed stale > 1 h, event lag > 60 s, approvals waiting 30 min, route agreement < 0.8, drift > 0.2, injection/SSRF > 10 per 5 min, FP feedback > 5 per 15 min, eval regression = drop of > 0.02 vs the value 1 h earlier for f1/precision/recall/auc/pr_auc. Burn rate: 14.4x (1 h and 5 m), 6x (6 h and 30 m) on a 5% budget (p95 < 8 s).
- 2026-11-22 · builder-observability · Alertmanager has no env substitution, so `infra/alertmanager/entrypoint.sh` renders the config at start: Telegram only if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are both set, else webhook if ALERT_WEBHOOK_URL is set, else a null receiver. Secrets are written to 0600 files in the data volume (`bot_token_file`, `chat_id_file`, `url_file`), never into the YAML.
- 2026-11-22 · builder-observability · The Grafana default theme is dark (`GF_USERS_DEFAULT_THEME`). Dashboards are generated by `infra/grafana/gen_dashboards.py` and the JSON is committed; edit the script, not the JSON.
- 2026-11-22 · builder-observability · Demo emitter: `scripts/emit_demo_metrics.py` serves synthetic `source=replay` metrics on 127.0.0.1:9199 (set FL_DEMO_EMITTER_BIND=0.0.0.0 on Linux Docker) and writes a Prometheus file_sd target while it runs (removed on exit). It never emits `fl_eval_metric` (eval gauges come only from eval artifacts; tested) and never emits `source=live`. Prometheus gets `extra_hosts: host.docker.internal`.
- 2026-11-22 · builder-observability · RUNBOOK.md groups several alert ids under one heading (e.g. `## error-rate / sandbox-failure / ...`), which GitHub renders as one long anchor. Tests treat each `/`-separated id as an anchor; L1 should split those headings or add explicit anchors so the links resolve on GitHub.

- 2026-11-22 · builder-observability · `falcon-alerts.yml` holds 17 alerts + 4 recording rules (21 rules). Alert expressions exclude the demo target (`data!="synthetic-replay"`), and Alertmanager routes `source="replay"` alerts to the null receiver (group_by includes `source`), so a demo or replay never pages Telegram.
- 2026-11-22 · builder-observability · Spans never record exception messages (`record_exception=False`, `set_status_on_exception=False`); only `error.type` (the exception class name) is kept. LLM spans are limited to an attribute allowlist (`LLM_SPAN_ATTRIBUTES`). The Alertmanager entrypoint deletes stale secret files on every start.
