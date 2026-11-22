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
- 2026-11-22 · owner · All frontend work (design vision, layout, palette, typography, motion, PWA, boards, extension UI) is led by **Fable 5.2**: `builder-frontend` now runs on `model: fable`, overriding the spec's Sonnet. The owner asked for a niche, state-of-the-art site with rich animated visuals.
- 2026-11-22 · owner · Approved the Ollama upgrade 0.40.13 → 0.40.17 (brew; service restarted) and Inkling-2-Mini as the local model, pending the capability check.
- 2026-11-22 · L1 · OpenPhish (checked by builder-evals at openphish.com/terms.html): the feed is the GitHub raw `public_feed/main/feed.txt`, updated every 12 h. Terms allow personal or academic research only; commercial use (including security operations) and redistribution need written consent. Decisions:
  - (a) The public manifest is **hash-only**: no URLs, defanged or not.
  - (b) OpenPhish is used for the research or eval dataset and for the non-commercial hackathon prototype. A production or police deployment needs an OpenPhish licence, and the README says so.
  - (c) The feed has no per-entry timestamps, so `first_seen` = poll time.
- 2026-11-22 · L1 · `first_poll`: 300 rows at 2026-11-22 ~16:00 GST. Next poll is allowed about 12 h later, so the loop runs in the background.
