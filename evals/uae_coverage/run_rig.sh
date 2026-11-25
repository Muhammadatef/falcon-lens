#!/bin/sh
# Run one rig variant inside a worker-image container on the ISOLATED project "fluae" (never the live "falcon").
# Usage: sh evals/uae_coverage/run_rig.sh <variant> <brands-path-inside-/wt> <h7 0|1> [replay_only 0|1]
# Needs: FL_ENV=local docker compose -p fluae --profile core up -d --no-build --no-deps egress-proxy sandbox
set -eu
WT=$(cd "$(dirname "$0")/../.." && pwd)
PRIV="${FL_PRIV_DIR:-$(git -C "$WT" rev-parse --path-format=absolute --git-common-dir)/../data/private}/evals/uae_heldout"
IMG="${FL_RIG_IMAGE:-falcon-lens-ci/worker:56b50049c63f}"
NAME="fluae-rig-$1"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker create --name "$NAME" --network fluae_sandbox_ctl --user "$(id -u):$(id -g)" \
  -v "$WT:/wt:ro" -v "$PRIV:/priv" -w /wt \
  -e PYTHONPATH=/wt/packages/falcon_core/src:/wt -e FL_ENV=local -e FL_AI_ENABLED=false \
  -e FL_FEED_OPENPHISH_ENABLED=false -e FALCON_BRANDS_YAML="/wt/$2" \
  -e FL_EGRESS_PROXY=http://egress-proxy:3128 -e FL_SANDBOX_URL=http://sandbox:8000 \
  "$IMG" python -m evals.uae_coverage.rig --variant "$1" --brands "/wt/$2" --h7 "$3" \
  --replay-only "${4:-0}" --out "/priv/raw_$1.jsonl" >/dev/null
docker network connect fluae_app "$NAME"
docker start -a "$NAME"
docker rm "$NAME" >/dev/null
