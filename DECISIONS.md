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
- 2026-11-22 · owner · All frontend work (design vision, layout, palette, typography, motion, PWA, boards, extension UI) is led by **Fable 5.2**: `builder-frontend` now runs on `model: fable`, overriding the spec's Sonnet. The owner asked for a niche, state-of-the-art site with rich animated visuals.
- 2026-11-22 · owner · Approved the Ollama upgrade 0.40.13 → 0.40.17 (brew; service restarted) and Inkling-2-Mini as the local model, pending the capability check.
- 2026-11-22 · L1 · OpenPhish (checked by builder-evals at openphish.com/terms.html): the feed is the GitHub raw `public_feed/main/feed.txt`, updated every 12 h. Terms allow personal or academic research only; commercial use (including security operations) and redistribution need written consent. Decisions:
  - (a) The public manifest is **hash-only**: no URLs, defanged or not.
  - (b) OpenPhish is used for the research or eval dataset and for the non-commercial hackathon prototype. A production or police deployment needs an OpenPhish licence, and the README says so.
  - (c) The feed has no per-entry timestamps, so `first_seen` = poll time.
- 2026-11-22 · L1 · `first_poll`: 300 rows at 2026-11-22 ~16:00 GST. Next poll is allowed about 12 h later, so the loop runs in the background.

## T-011 arbiter (builder-agent-core, feat/core-arbiter)
- 2026-11-22 · agent-core · Versions used (PyPI checked 2026-11-22): PyYAML 6.0.4 (`yaml.safe_load` only), pytest 9.2.0, jsonschema 4.26.0 (optional, schema tests skip without it), ruff 0.17.6, mypy 2.4.1 + types-PyYAML 6.0.12.20261122.
- 2026-11-22 · agent-core · Branch is `feat/core-arbiter` per the dispatcher (TASKS.md says `feat/scoring-arbiter`). Scope is H1–H6 (the dispatcher widened the card's H1–H4).
- 2026-11-22 · agent-core · `scoring/params.yaml` was created by hand with the SCORING.md draft values, as the dispatcher instructed, and is labelled `draft: true`. From now on only `make fit-thresholds` writes it.
- 2026-11-22 · agent-core · No `falcon_core/__init__.py` in this PR. It is a PEP 420 namespace package, to avoid a conflict with T-001's skeleton.
- 2026-11-22 · agent-core · Evidence in families url/domain/reputation feeds `p_clf`. Only the other families (page, visual, brand, message, email, image, injection, llm) go into the log-odds adjustment, so nothing is counted twice when a fitted `p_clf` is passed.
- 2026-11-22 · agent-core · T-022's fitted classifier must include reputation hits as features. Otherwise a stale (non-H2) feed hit adds nothing once `p_clf` is fitted.
- 2026-11-22 · agent-core · Draft classifier when `p_clf=None`: `logit = -2.2 + Σ w·c` over url/domain/reputation evidence, using the SCORING §2 weights. The prior is about 0.10. The result is flagged `p_clf_draft=True`.
- 2026-11-22 · agent-core · `Evidence.weight` = `w·c`, the log-odds contribution after confidence and the message-rule cap. It is also filled for T1 families as attribution for ordering reasons.
- 2026-11-22 · agent-core · The `registry.verified_official` −4.0 trust weight counts only when H3 holds. With open-redirect abuse or a feed hit it is 0, so an abused official redirector can't lower the score.
- 2026-11-22 · agent-core · Negative weights are zeroed for evidence from `llm*` or `user` sources and from the llm/injection families. Evidence whose family doesn't match its signal prefix gets weight 0 and triggers no rule. This is the "injection can only raise risk" guard.
- 2026-11-22 · agent-core · H3 overrides any co-firing H1/H4/H6 floor, which keeps zero `dangerous` on verified-official. The overridden rules are reported in `suppressed_rules`. H3 applies only when `input_type=url`.
- 2026-11-22 · agent-core · The H3 cap sets p ≤ 0.05 (draft), so the score matches the capped verdict. Floors: H1 p ≥ 0.95; H2/H4/H5 p ≥ τ_high; H6 p ≥ τ_low.
- 2026-11-22 · agent-core · H1 θ is 0.70 (draft) on the `brand.claimed_not_owned` confidence. "Payment request" = `message.rule.payment`. If the caller passes `registrable_domain` + `verified_domains`, both H1 and H3 are cross-checked against the registry.
- 2026-11-22 · agent-core · H2 requires an explicit `observed.fresh=true` or `observed.feed_age_s` < 21600, plus `match` ∈ {url, host} when `match` is present. A feed hit with no freshness info is not H2, but its +6.0 weight still applies.
- 2026-11-22 · agent-core · H4 = `page.cross_origin_post` with `bot=true` or a bot/webhook `target_kind`, AND either `credentials=true` or a present `page.cred_form`.
- 2026-11-22 · agent-core · H5 is driven by new evidence `message.link_verdict` / `email.link_verdict` (`observed.verdict`), weight 0. I'm proposing to L1 that these be added to SCORING.md.
- 2026-11-22 · agent-core · H6 impersonation = `message.rule.authority` | `email.display_name_impersonation` | `brand.claimed_not_owned`.
- 2026-11-22 · agent-core · Degraded = an errored T0/T1 evidence item, or `ctx.extra_degraded_reasons` from the cascade. T2 errors degrade only if the cascade passes a reason. `p` is not inflated; only the shown verdict moves to suspicious. This also applies over H3 (CONTRACTS invariant 4).
- 2026-11-22 · agent-core · Cascade ε_low = 0.05 and ε_high = 0.98 are draft values (SCORING gives none). "Brand conflict" = any present homograph/typosquat/combosquat/brand-in-path/claimed_not_owned/favicon-match evidence.
- 2026-11-22 · agent-core · Template reasons: the degraded reason comes first when it caused the verdict, then hard-rule reasons, then by |w| (max 3). `no_warning_signs` shows trust reasons only, and risk verdicts show risk reasons only.
- 2026-11-22 · agent-core · Report channels are shown only when the config has an https `source_url` and an ISO `retrieved_at`. Otherwise the config's `generic_fallback` is used, then the i18n generic line.
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

## T-024 / T-025 LLM router, tools, extractor, investigator, responder (builder-agent-core, feat/core-agent)
- 2026-11-22 · agent-core · Versions used: anthropic 2.12.0 (pulls httpx2 2.16.2; its exception classes take `httpx2.Request`), httpx 0.28.1 for Ollama, pydantic 2.14.4, PyYAML 6.0.4, types-PyYAML 6.0.12.20261122. Shapes checked against the installed SDK and the platform.claude.com prompt-caching and effort docs (2026-11-22).
- 2026-11-22 · agent-core · Branch is `feat/core-agent` (dispatcher). It covers the T-024 (`feat/llm-router`) and T-025 (`feat/agent-investigator`) cards plus the extractor and responder. Integration merge of keep/feat/core-arbiter + keep/feat/security-ssrf-egress: DECISIONS conflicts resolved by keeping both sides; arbiter (and two security) files reformatted to the workspace 100-column limit; pyyaml/httpx/httpcore/anthropic added to falcon-core deps.
- 2026-11-22 · agent-core · Local calls use plain httpx against Ollama `/v1/chat/completions` (no openai SDK), with `temperature 0`, `seed 7` and no `response_format` (unsupported for inkling-2-mini-chat). Chat-template tokens `<|...|>` are stripped.
- 2026-11-22 · agent-core · The router's default local model is `inkling-2-mini-chat` (from main's .env.example). `FL_LOCAL_LLM_TIMEOUT_S` defaults to 60 s, since a cold load takes about 50 s. The router reads `os.environ` only (`RouterConfig.from_env`), never a .env file; `config.Settings` still defaults to gemma3:27b.
- 2026-11-22 · agent-core · Cloud requests: `output_config.effort="low"`; `thinking` is "disabled" on Haiku 5.5 and "between_tools" on Sonnet 5.5 (docs: "To have the model respond without thinking first"). No temperature, no tools or tool_choice, and `max_retries=0` because the router owns fallback. Only `text` blocks are read.
- 2026-11-22 · agent-core · No provider structured-output mode is used. Both routes use prompt-level JSON plus pydantic, so cloud and local behave the same (ADR-001) and shadow agreement is comparable.
- 2026-11-22 · agent-core · Prompt caching: the system prompt (base rules + role task + JSON schema + canary) is stable per (role, schema) and is sent as one text block with `cache_control: ephemeral`. Today's prompts are probably under the 512-token minimum, so no cache hits are expected yet. That fails silently, not with an error.
- 2026-11-22 · agent-core · There is one canary per router instance (`FLC-<12 hex>`), which keeps the cached system prompt stable. A reply containing the canary or its hex part is discarded without a repair attempt, and `fl_canary_leak_total{role}` goes up.
- 2026-11-22 · agent-core · Redaction runs on every LLM call, local too, not only cloud ones. The fallback then reuses the same redacted prompt and shadow comparisons see identical input. Toll-free and short official numbers (8002626, 999) are not phone-redacted.
- 2026-11-22 · agent-core · Spotlighting also removes zero-width, bidi and control characters, and replaces `<<<`/`>>>` and the nonce inside untrusted text. The nonce explanation goes in the user turn, because the system prompt must stay cacheable.
- 2026-11-22 · agent-core · Cloud-to-local fallback happens only on a provider error or timeout. A schema failure gets one repair retry on the same route, then the caller's template fallback. The request's overall `timeout_s` deadline covers both routes together.
- 2026-11-22 · agent-core · Shadow sampling runs only when cloud is enabled (never in sovereign mode or without a key), as a background task. It records `fl_route_agreement_ratio` as 0/1 observations (exact equality of the parsed objects). It is off for the investigator, whose actions are stateful.
- 2026-11-22 · agent-core · Metrics go through a `MetricsSink` protocol (`llm/metrics.py`) using the OBSERVABILITY names, because builder-observability's `telemetry/metrics.py` does not exist yet. The default sink is in-memory.
- 2026-11-22 · agent-core · Cost uses the VERIFIED_VERSIONS §2 table. The Haiku tier switches above 100k prompt tokens (cache tokens included). Cache writes are priced at the 5 m rate, unknown cloud models at the Sonnet 5.5 rate, and local calls at 0.
- 2026-11-22 · agent-core · The extractor enums (`requested_data`, `script_category`, `language`) are defined in `agent/extractor.py`. `claimed_brand_id` is checked against the data/brands.yaml ids through the pydantic validation context. Proposed to L1: a `contracts/extraction.schema.json`.
- 2026-11-22 · agent-core · Extractor evidence:
  - `llm.extraction`: weight 0, with the full extraction in `observed`.
  - `injection.instruction_like_text`: confidence 0.7, `observed.detector=extractor`, emitted when `instruction_like` is true. If T-026's regex detector also fires, the cascade should keep only the higher-confidence item so it isn't counted twice.
  - `brand.claimed_not_owned`: confidence 0.8 (H1 θ is 0.70), emitted when the cascade passes a registrable domain that isn't in the claimed brand's verified list.
- 2026-11-22 · agent-core · Provenance:
  - A URL arg must equal the canonical URL or a hop, after case-folding the scheme and host and dropping the default port and fragment.
  - A domain arg must be an on-chain host, a registrable domain the cascade supplied, or a heuristic eTLD+1 of an on-chain host. The heuristic is used only when the cascade gives no PSL value, and it can only yield suffixes of on-chain hosts.
  - Hops returned by `expand_redirects` (our own fetcher) are added to the context.
- 2026-11-22 · agent-core · A provenance violation adds `injection.tool_provenance` evidence and counts `fl_tool_errors_total{reason=provenance}` and `fl_injection_detected_total{source=tool_provenance}`. Its weight stays 0 until L1 assigns one; proposed +1.5, like instruction_like_text. Fingerprint args must be in `ProvenanceContext.script_fingerprints`.
- 2026-11-22 · agent-core · Tool output is re-stamped: new evidence id, tier T3, weight 0, hard_rule None, polarity neutral, observed strings capped at 512 chars, URL strings defanged. A backend can never pre-set arbiter fields.
- 2026-11-22 · agent-core · Investigator:
  - The model passes target refs (`u0`, `d1`, `f0`), which the investigator resolves to exact on-chain values, so the model never copies URLs. A literal value is still accepted and provenance-checked.
  - Rejected and duplicate calls count toward the 6-call budget.
  - max_tokens per plan step = min(700, what is left of 8000).
  - The time budget bounds both the LLM and the tool timeouts.
- 2026-11-22 · agent-core · Evidence view for the investigator and responder: observed values are reduced to bools, numbers and token-like strings (≤80 chars). Everything else becomes `"<text>"`, and URLs are defanged. This keeps "structured evidence only" even if a signal puts free text in `observed`.
- 2026-11-22 · agent-core · Verifier rules beyond cited ids. Any failure rejects the whole LLM answer and uses the templates. Degraded verdicts always use templates.
  - Cited evidence must exist and not be errored.
  - On a warning verdict, each reason must cite at least one risk item (w>0 or a hard_rule). On no_warning_signs, reasons must cite no w>0 item.
  - Text must not contain "safe"/«آمن», links or domains, `<>%`, or "score"/«نسبة».
  - `ar` must contain Arabic script.
- 2026-11-22 · agent-core · Agents get brand ids from `agent/brands.py`, which finds data/brands.yaml by walking up from the package or reads `FL_BRANDS_PATH`. Containers must set `FL_BRANDS_PATH`.
