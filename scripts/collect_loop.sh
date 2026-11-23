#!/usr/bin/env bash
# collect_loop.sh - poll the OpenPhish feed every 12 hours, forever.
#
# What it does:
#   Runs evals/collect/openphish.py in an endless loop, then sleeps 12 h 2 min (the feed's published update
#   interval plus a margin). If a poll fails or is refused it logs one line to stderr and keeps going. The
#   poller itself also enforces the rate guard (state.json), so an early poll is refused.
#
# When to use it:
#   When you want the phishing eval set to grow over several days (the temporal train/val/test split needs
#   several polls). Start it once in the background and leave it.
#
# How to run:
#   scripts/collect_loop.sh &          (no make target; stop it with `kill %1` or by closing the terminal)
#
# Inputs:
#   Optional env FL_DATA_DIR (where data/ lives). Needs `uv` and network access to the OpenPhish feed.
#
# Outputs / side effects:
#   Whatever openphish.py writes: raw rows under data/private/feeds/openphish/ (gitignored) and hash-only
#   rows in evals/manifests/phishing.manifest.jsonl. Makes one HTTPS request to the public feed per poll.
#
# Safety notes:
#   Never commit or print the private rows; OpenPhish forbids redistribution. The script never opens the URLs.
set -u
cd "$(dirname "$0")/.."
INTERVAL=$((12 * 3600 + 120))
while true; do
  uv run --no-project --with httpx --with tldextract python evals/collect/openphish.py \
    || echo "$(date -u +%FT%TZ) poll failed or refused" >&2
  sleep "$INTERVAL"
done
