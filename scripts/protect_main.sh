#!/usr/bin/env bash
# Set branch protection on main. Needs `gh` authenticated as a repo admin. Run it ONCE, deliberately:
#   scripts/protect_main.sh [owner/repo]
# Required checks are the CI job names `lint`, `typecheck`, `test`, `contracts`, `security`.
# `docker-build` and `eval-gate` are intentionally NOT required (slow / not yet a real gate).
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
