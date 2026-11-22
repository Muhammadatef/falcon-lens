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
- 2026-11-22 · builder-evals · Tranco (tranco-list.eu) list id 46YLX (top-1m, retrieved 2026-11-22) used only to pick well-known popular sites by hand; the page states no licence for the list itself (upstream: Cisco Umbrella, Majestic CC BY 3.0, CrUX CC BY-SA 4.0, Cloudflare Radar CC BY-NC 4.0). The CSV republishes only ~130 hand-picked domains, not the list; cite Tranco in the README.
- 2026-11-22 · builder-evals · `evals/datasets/legit_urls.csv`: one plain GET per URL (UA `FalconLens-research/0.1`, 1 req/s, redirects followed, 2xx only; official rows must also end on a verified_domain). Failures dropped; per-row log in gitignored `data/private/legit_url_checks.jsonl`. New-domain rows kept only if RDAP (rdap.org) shows registration >= 2024-01-01; only 5 qualified (RDAP is missing for many TLDs), so that category is thin.
- 2026-11-22 · builder-evals · Official shorteners used: youtu.be, aka.ms, g.co, apple.co, mzl.la, go.microsoft.com. Only named slugs or public video ids; no invented ids.
- 2026-11-22 · builder-evals · `scripts/qwen_task.py` calls Ollama 0.40.17 `/v1/chat/completions` with `reasoning_effort: "none"`, `response_format: json_object`, `seed` (docs.ollama.com/api/openai-compatibility, checked 2026-11-22); model `qwen3:4b`. Deps: httpx, jsonschema (via `uv run --no-project --with`).
- 2026-11-22 · builder-evals · Dedup in qwen_task is character 4-shingle Jaccard >= 0.8 on NFKC-normalised, diacritic-stripped text (not MinHash; n is small).
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
- 2026-11-22 · builder-evals · `legit_urls.csv` stores `url` DEFANGED (`hxxps://` scheme prefix only) so `make guard` and CI pass; consumers refang with `url.replace("hxxp", "http", 1)`. `registrable_domain` is plain. Removed `gov.uk` (a public suffix) in favour of `www.gov.uk`, and the `.exe` shortener row (410 rows now).
- 2026-11-22 · builder-evals · qwen_task v2: validation runs on the TEXT (script ratio and dialect markers per spec `language_rules`), links and phones use spec allow-lists, entity rules are subtype-aware, few-shot copies (Jaccard >= 0.7) are rejected, every rejection reason is counted. `FL_LOCAL_STRUCTURED=0` for models without structured output. Re-run `qwen-msg-002` uses `inkling-2-mini-chat` with spec `synthetic_messages_v2.json` (demo brand Arabic name «بنك الصقر التجريبي»).
