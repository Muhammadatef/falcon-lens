# ADR-002: Sentinel, a 24/7 backend agent on LangGraph

**Status:** Accepted · 2026-11-22 · L1

## Context
Being proactive (استباقية) means linking single checks into campaigns and acting before more residents are hit. The work is long-running and must survive restarts, needs retries, and must stop before any external action until a human approves it.

## Decision
- **Listen**: Redis Streams `fl:events`, consumer group `sentinel`, at-least-once delivery. Handlers are idempotent on `event_id`. Failures go to the `fl:events:dlq` stream after 3 attempts.
- **Correlate** (plain Python, deterministic): bucket events by `dom_simhash` (Hamming distance ≤ 6), brand, registrable-domain pattern (brand skeleton + affix), ASN, registrar, cert issuer, script embedding cluster (cosine ≥ 0.88) and a time window.
- **Trigger** (`services/sentinel/rules.yaml`, unit-tested): R1 campaign (≥3 new lookalike domains for one brand in 60 min); R2 kit reuse (one dom_simhash on ≥3 domains); R3 report burst (≥5 reports on one script cluster in 30 min); R4 reputation flip (previously no_warning_signs, now dangerous); R5 quality (≥5 FP feedback on one signal in 60 min).
- **Triage**: a LangGraph `StateGraph` with nodes `enrich → compare → assess → summarise → propose → act`. It uses a Postgres checkpointer (thread_id = incident_id) and a per-node RetryPolicy, and calls `interrupt()` before any `external_draft` action.
- **LangChain**: only `langchain-core` model and tool interfaces, as LangGraph requires. No chains, memory, retrievers or prebuilt agents.
- **DSPy**: offline only. It optimises the prompt of every shipped LLM role (extractor, investigator, Sentinel assess/summarise/propose) on the train split and selects on validation, per route; the compiled prompts are frozen into `packages/falcon_core/prompts/compiled/`.
- Tools are the same typed registry used by the investigator and MCP (`contracts/tools.schema.json`), going through the same model router, so sovereign mode applies here too.

## Guardrails
- Rules and correlation decide what an incident is. Incident counts are reproducible with the LLM stubbed.
- The agent cannot edit rules, thresholds or scoring, and sees structured evidence only.
- Budget per incident: 8 steps, 20k tokens, 120 s (three local-model calls take 15-25 s each). Every action goes to the append-only `audit_log`, with the evidence ids behind it.
- Each block expires (TTL) and `make unblock ID=` reverts it; reverts are counted in `fl_blocks_reverted_total`.

## Minimum version (if time is short)
R1, R2, R4; correlation on brand + dom_simhash + window; a graph producing one bilingual summary and one `block_indicator`.
