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
- 2026-11-22 · builder-signals · T-007 versions used: tldextract 5.4.0 (`include_psl_private_domains=True`, `suffix_list_urls=()`, bundled snapshot, no network), PyYAML (safe_load), Unicode confusables.txt UTS#39 v18.0.0 (file date 2026-08-06) vendored at `signals/url/data/confusables.txt`.
- 2026-11-22 · builder-signals · tldextract returns no suffix for TLDs outside the PSL (.test, .example), so `canonical.psl_split` falls back to the default `*` rule (last label = suffix). Fixtures on `.test` depend on it.
- 2026-11-22 · builder-signals · T1 signals are sync CPU bodies wrapped by `base.signal()` into `async run(ctx)` (timeout 50 ms, never raises, stamps latency_ms); REGISTRY lives in `signals/base.py` and is re-exported by `signals/__init__.py`. Evidence/SignalSpec are plain dataclasses until T-002 ships pydantic mirrors; `Evidence.to_dict()` matches evidence.schema.json. Evidence id = `ev_` + sha256(signal, observed)[:16] (deterministic).
- 2026-11-22 · builder-signals · SignalContext for URL signals reads `ctx.url` (falls back to `ctx.text`) and optional `ctx.brands` (BrandRegistry; default loads data/brands.yaml, override env FALCON_BRANDS_YAML).
- 2026-11-22 · builder-signals · Typosquat tiers (assumption): brand label < 5 chars (du, moi, rta, dib, adcb, eand) is never edit-distance matched (false-positive risk); 5-7 chars allow distance 1 (or 2 when every edit is a QWERTY-adjacent substitution); >= 8 chars allow distance 2. Same label on another TLD is emitted as kind=tld_swap (confidence 0.8); hyphen insertion/removal as kind=hyphenation.
- 2026-11-22 · builder-signals · Script detection uses the first word of `unicodedata.name()` (stdlib has no Script property); digits, hyphen and marks are Common. A single mixed-script label with no brand match still emits url.homograph at confidence 0.6 (reason mixed_script).
- 2026-11-22 · builder-signals · Same-script I/l tricks (paypaI): hosts are lowercased by the canonicaliser, so homograph also tests the as-typed host (`host_raw_case`) through the skeleton. Plain-lowercase `paypai` is not detectable and is not claimed.
- 2026-11-22 · builder-signals · Brand tokens derive from verified domain labels, compact name_en and parenthesised acronyms, multi-word non-generic keywords_en, and name_ar/keywords_ar (Arabic normalised: tashkeel/tatweel removed, alef/hamza/ya folded). Generic service words (fine, bill, مخالفة ...) are never brand tokens. Path-only brand mentions get confidence 0.5 (news pages quote brands).
- 2026-11-22 · builder-signals · Proposals for L1 (not edited): add `url.data_uri` (data: URI input; currently only a classifier feature) to SCORING.md §2; confirm weights for confidence < 1 evidence (arbiter should scale by `confidence`).
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
