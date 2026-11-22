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
