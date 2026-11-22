# HIERARCHY & WORKFLOW

| Level | Who | Model | Responsibility |
|---|---|---|---|
| L0 | Owner | human | Secrets; irreversible decisions; Arabic spot-checks; records the demo video |
| L1 | Lead architect (main session) | Opus 5.5 (the spec says Fable 5.2; see DECISIONS) | Vision, architecture, ADRs, contracts, scoring, threat model, dispatch, merging approved work. **Writes no feature code.** |
| L2 | `supervisor` | opus | Task cards, review of every PR (contracts, tests, evals, security), audit of every local-model batch. Sole approver. Writes only `reviews/` and `TASKS.md`. |
| L3 | builders | **sonnet 5.5 for all builders** (owner decision 2026-11-23, cost) | One module each, on its own branch or worktree |
| L4 | local workers | `FL_LOCAL_WORKER_MODEL` via Ollama (currently `qwen3:4b`; `qwen3.8:27b` when mirai is reachable) | Bulk, low-risk drafts via `scripts/qwen_task.py` only |

## How it runs
- Subagents can't start other subagents, so L1 dispatches both the builders and the supervisor.
- Independent builders run in parallel in git worktrees (`isolation: worktree`).
- The supervisor's verdict is binding. Nothing merges without `reviews/PR-<n>.md` saying **APPROVE**.

## PR flow
1. The supervisor writes a task card in `TASKS.md`: id, scope, contract refs, acceptance tests, eval impact, owner.
2. The builder works on `feat/<module>-<slug>` and opens a GitHub PR with `gh pr create`. The remote exists and is public.
3. CI runs: ruff, mypy, pytest, contract tests (JSON Schema ↔ pydantic round-trip), the eval gate (`docs/EVALS.md` tolerances) and `make scan`.
4. The supervisor runs the `pr-review` skill and writes `reviews/PR-<n>.md` with APPROVE or CHANGES REQUESTED and the reasons. After two rounds it escalates to L1.
5. L1 merges with a squash merge. L1 never merges anything unapproved, including its own doc edits after G0.

## Local model rules
- Only `scripts/qwen_task.py --task <id> --kind <synthetic_messages|unit_test_draft|docstring|ui_strings|label_pass> --spec <file>` may call the local worker model. It writes `work/qwen/<task-id>/{output.jsonl,manifest.json}` and never commits.
- Each batch is schema-validated and de-duplicated (MinHash). The supervisor then audits a random sample of max(20%, 30) items. An error rate above 5% rejects the batch.
- Synthetic items carry `synthetic=true` and are reported separately in every eval.

## Budget discipline
- L1 keeps its context small and delegates reading.
- **Opus is used ONLY for the supervisor.** Builders run on Sonnet 5.5; bulk text (synthetic data, drafts, labelling) goes to the local LLM via scripts/qwen_task.py. Fable is no longer used.
- If usage limits get close, the supervisor reviews only P0 PRs and no stretch work starts.
