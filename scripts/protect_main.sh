#!/usr/bin/env bash
# protect_main.sh - turn on branch protection for `main` on GitHub.
#
# What it does:
#   Calls the GitHub API (through `gh`) to require pull requests with one approving review and code-owner
#   review, require the CI checks lint, typecheck, test, contracts and security, resolve all conversations,
#   and forbid force pushes and branch deletion. `docker-build` and `eval-gate` are intentionally NOT
#   required (slow, or not yet a real gate).
#
# When to use it:
#   Once, deliberately, by a repo admin, after the CI job names exist. Re-running it just re-applies the
#   same settings.
#
# How to run:
#   scripts/protect_main.sh [owner/repo]       (no make target; repo defaults to the current `gh` repo)
#
# Inputs:
#   Optional first argument owner/repo. Needs `gh` logged in as an admin of the repo.
#
# Outputs / side effects:
#   One PUT request to repos/<repo>/branches/main/protection. Changes repository settings on GitHub;
#   writes nothing locally.
set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
echo "Applying branch protection to ${REPO}:main"

gh api --method PUT "repos/${REPO}/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "typecheck", "test", "contracts", "security"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
echo "Done."
