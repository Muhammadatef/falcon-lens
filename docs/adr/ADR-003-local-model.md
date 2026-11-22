# ADR-003: Local model for sovereign mode and L4 workers

**Status:** Provisional · 2026-11-22 · L1. Revisit when mirai is reachable or Ollama is upgraded.

## Context
The spec assumes `qwen3.8:27b` through Ollama. This Mac (M5 Max, 128 GB) has `gemma3:27b` (completion and vision, no tools), `qwen3:4b`, and `qwen3-embedding:4b`. The owner says qwen3.8:27b lives on host "mirai", which can't be reached from here. Inkling-2-Mini (Apache-2.0, 26B MoE with 3.4B active, text+image) is at `~/Models/Inkling-2-Mini`, but Ollama 0.40.13 can't pull it.

## Decision
- All local calls go through the OpenAI-compatible `/v1` endpoint at `OLLAMA_BASE_URL`. Models are set in env (`FL_LOCAL_MODEL`, `FL_LOCAL_VISION_MODEL`, `FL_LOCAL_WORKER_MODEL`, `FL_EMBED_MODEL`).
- Tool selection uses JSON actions (ADR-001), so native tool support is optional.
- Order of preference, chosen by a 5-prompt capability smoke test (`scripts/local_model_check.py`: JSON schema adherence, Arabic, vision, latency):
  1. `qwen3.8:27b` at mirai
  2. `inkling-2-mini` (once Ollama ≥ 0.40.17)
  3. `gemma3:27b` (current)
- Embeddings: `qwen3-embedding:4b`. Its dimension is checked at startup and must match `FL_EMBED_DIM`.
- Sovereign-mode metrics are reported with the exact model tag that produced them.

## Consequences
- Switching models is a change to `.env` and needs no code change. The eval artifact records the model ids.
