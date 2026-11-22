# Local worker (runs 24/7, local models only)

## What it does

A small background program that keeps the local models busy even when Claude is rate-limited or no session is open. It talks only to Ollama (`OLLAMA_BASE_URL`, default `http://localhost:11434`): `inkling-2-mini-chat` for quality text (Arabic review), `qwen3:4b` for bulk work. It never calls Claude or any hosted API, never runs git, never edits tracked files, never reads `.env`. Everything it produces lands under `work/` (gitignored).

It takes one job at a time from a folder queue. When the queue is empty it adds its own recurring jobs, set in `scripts/local_worker/schedule.yaml`:

| Job | How often | Result |
|---|---|---|
| Sovereign eval (`make eval ROUTE=local`) | 6 h | log and artifact paths in the manifest |
| Synthetic message batch (`evals/specs/synthetic_messages_v2.json`) | 3 h | `work/qwen/auto-<timestamp>/` |
| Arabic review (`ar.yaml` and `web/lib/i18n.ts`) | 12 h | suggestions file |
| DSPy optimisation (`make dspy-optimize LM=local`) | daily | log in the job folder |

It pauses by itself when Ollama is unreachable (waits 15 s, then 30 s, 60 s... up to 15 min) and when the Mac is busy (load average above 1.5 times the CPU count, for example during a heavy Docker build). A job interrupted by Ollama going away goes back to the queue. After a crash or reboot, running jobs are re-queued.

## Add a task

```bash
make local-worker-enqueue KIND=summarize INPUT=work/some.log
make local-worker-enqueue KIND=label_pass INPUT=data/x.jsonl PARAMS='{"labels":["scam","ok"],"text_field":"text"}'
# or directly:
uv run python -m scripts.local_worker enqueue --kind docstring_draft --input services/api/src/falcon_api/foo.py
```

Kinds: `synthetic_messages` (input = spec JSON, runs the `scripts/qwen_task.py` pipeline), `arabic_review` (input = yaml or source files; writes `suggestions.jsonl`), `label_pass` (input = jsonl, `params.labels` required), `summarize` (input = file, the tail is summarised), `docstring_draft` (input = Python file; writes a `.patch`, never applied), `eval_sovereign`, `dspy_local`. Lower `--priority` runs first (default 5).

A task is refused, and moves to `failed/` with the reason, when its input has a non-defanged `http(s)://` URL (only `.test`, `.example`, `.invalid` and localhost are allowed; write `hxxps://name[.]test`), points outside the repo, or names `.env` or `data/private`.

## Where results land

```
work/queue/pending/<id>.json        waiting
work/queue/running/                 the job in progress
work/queue/done/<id>/               output files + manifest.json (task, seconds, extras)
work/queue/failed/<id>/             error.txt + manifest.json
work/queue/worker.log               JSON lines, rotated (2 MB x 5)
work/queue/heartbeat.json           written every loop step
work/qwen/auto-<ts>/                synthetic batches (output.jsonl + manifest.json)
```

## How the supervisor audits

Everything the worker writes is unreviewed model output. Nothing is imported or applied automatically. The supervisor opens `done/<id>/manifest.json` (`needs_supervisor_audit: true` for synthetic batches), reads the output, and only then copies anything into tracked files through a normal PR. Patches from `docstring_draft` are suggestions to apply by hand. Labels carry `label_source: local-model`. Check on it with:

```bash
make local-worker-status     # queue counts, current job, last heartbeat, last 5 results
```

## Install, stop

```bash
make local-worker-install     # renders infra/local_worker/ae.falconlens.localworker.plist into ~/Library/LaunchAgents, starts it
make local-worker-uninstall   # stop and remove it
make local-worker-run         # or run in the foreground, Ctrl-C to stop
```

The agent starts at login, restarts if it dies, and runs at low priority (Nice 10). Launchd output goes to `work/queue/launchd.*.log`. To pause without uninstalling: `launchctl bootout gui/$(id -u)/ae.falconlens.localworker`, and start again with `make local-worker-install`.
