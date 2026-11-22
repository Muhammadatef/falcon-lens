---
name: run-evals
description: Run the Falcon Lens eval harness and publish the artifact.
---
# run-evals

1. `make eval ROUTE=cloud` and `make eval ROUTE=local` (sovereign). The splits come from `evals/splits.lock`.
2. Check that the artifact `evals/results/<ts>.json` contains dataset_hash, git_sha, model_ids, thresholds and seeds.
3. Compare with `evals/baseline.json` using the tolerances in docs/EVALS.md, and print the gate result.
4. To publish: copy the JSON (no live URLs) to `evals/results/published/` and update STATUS.md "Latest metrics" **only from that file** (`scripts/status_metrics.py`).
5. Never tune anything on the test split.
