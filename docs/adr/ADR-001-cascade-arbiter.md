# ADR-001: Tiered cascade with a deterministic arbiter and a bounded investigator

**Status:** Accepted · 2026-11-22 · L1

## Context
Checks must answer in seconds (median under 2 s, p95 under 8 s), explain themselves in Arabic and English, catch zero-day pages that no blocklist knows, and resist prompt injection from attacker-controlled pages and messages.

## Decision
A cascade T0 → T1 → T2 → T3, with early exit, and a fixed arbiter that produces the score (`docs/SCORING.md`).
- **T0** (50 ms): canonicalise, verdict cache, verified-official registry, local feed mirror.
- **T1** (1 s): deterministic URL, domain and reputation signals in parallel, plus a calibrated GBM.
- **T2** (6 s): sandbox render, page and visual features, the reference-based brand check (hard rule H1), and the quarantined LLM extractor.
- **T3** (15 s): an investigator LLM with at most 6 tool calls, only for the uncertain band.
- The investigator is an explicit state machine (`plan → act → observe → decide`). The LLM emits one JSON `Action` per step, validated against `contracts/tools.schema.json`. Native provider tool calling is **not** required, which keeps cloud and local routes identical and lets local models without tool support (gemma3) work.
- Dual-model separation: the extractor sees untrusted text, with no tools and strict schema output. The investigator and responder see structured evidence only.
- Progressive verdict over SSE, with the same `verdict_id` re-emitted per tier.

## Rejected alternatives
- **A single free-running agent**: slow, costly, nondeterministic, and injectable; a page could talk it out of the evidence.
- **A pure classifier**: no grounded explanations, and weak on new attack styles and brands.
- **A multi-agent chat framework** (CrewAI/AutoGen style): adds latency and unpredictability for no benefit on a seconds-budget path.

## Consequences
- Most checks never touch an LLM. Cost and latency stay low, and evals are reproducible.
- An injection can at most add evidence. It cannot lower a score, because the arbiter is code.
- The arbiter weights and thresholds are fitted on validation and frozen; evals gate any change.
