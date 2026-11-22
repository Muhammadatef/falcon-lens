---
name: qwen-task
description: Hand a bulk low-risk job to the local worker model and prepare it for supervisor audit.
---
# qwen-task

1. Write a spec file containing the task kind, an item JSON schema, a count, language mix and examples. Never include real people's data or live URLs.
2. `uv run python scripts/qwen_task.py --task <id> --kind <kind> --spec <file>`. Output goes to `work/qwen/<id>/output.jsonl` and `manifest.json` (model tag, prompt hash, seed, counts, rejected-by-schema, dedup-removed).
3. Ask the supervisor to audit it (reviews/QWEN-<id>.md). Only an APPROVED batch can be imported, with `synthetic=true`.
