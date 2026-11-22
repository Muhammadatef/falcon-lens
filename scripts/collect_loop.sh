#!/usr/bin/env bash
# Poll OpenPhish at the published 12 h interval. Usage: scripts/collect_loop.sh &
# The poller itself also enforces the rate guard (state.json); early polls are refused.
set -u
cd "$(dirname "$0")/.."
INTERVAL=$((12 * 3600 + 120))
while true; do
  uv run --no-project --with httpx --with tldextract python evals/collect/openphish.py \
    || echo "$(date -u +%FT%TZ) poll failed or refused" >&2
  sleep "$INTERVAL"
done
