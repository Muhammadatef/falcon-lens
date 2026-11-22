---
name: pr-review
description: Review a Falcon Lens PR as the supervisor and record APPROVE or CHANGES REQUESTED in reviews/PR-<n>.md.
---
# pr-review

1. `git fetch && git worktree add /tmp/fl-review-<n> <branch>`, then `cd` there.
2. Run `make test`, `uv run pytest tests/contracts -q`, `make eval-gate` (once it exists) and `make scan`. Capture the exit codes and the last 20 lines of each.
3. `git diff main...<branch>` and check it against:
   - contracts in `contracts/` (field names, enums, invariants in docs/CONTRACTS.md)
   - defensive-only: no live phishing URLs (grep `https?://` in data and test files and check they're defanged or fixture hosts), no brand logos, no form submission in the sandbox
   - security: anything fetching a URL goes through `ctx.http`/`safe_fetch`; no `dangerouslySetInnerHTML`; no secrets (`gitleaks detect --no-git -s .`)
   - no "safe" verdict wording; no hand-typed metrics in docs
   - tests exist for new behaviour
4. Write `reviews/PR-<n>.md` with Verdict, Checks run (command → result), Findings (file:line, severity, fix), and Eval impact.
5. If a GitHub PR exists: `gh pr review <n> --approve|--request-changes -F reviews/PR-<n>.md`.
6. `git worktree remove /tmp/fl-review-<n>`.
