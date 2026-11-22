---
name: add-signal
description: Add a new detection signal plugin that emits Evidence.
---
# add-signal

1. Create `packages/falcon_core/signals/<family>/<name>.py` with `SPEC = SignalSpec(...)` (contracts/signal.schema.json) and `async def run(ctx) -> list[Evidence]`.
2. Network access only through `ctx.http` (SSRF-guarded, through the egress proxy) or `ctx.mirror`. Respect `SPEC.timeout_ms`. Never raise; return Evidence with `error` set instead.
3. Add the evidence names to docs/SCORING.md §2. Proposing a weight needs an L1 edit.
4. Tests in `tests/signals/test_<name>.py`: positive, negative, Arabic or confusable edge cases, timeout.
5. Register it in `signals/__init__.py:REGISTRY` and run `make test` plus the eval gate.
