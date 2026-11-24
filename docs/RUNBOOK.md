# RUNBOOK — one entry per alert (anchors referenced by alert rules)

## campaign-surge
A Sentinel R1 rule fired. Open the incident board, review the indicators and summary, then approve or reject the drafted takedown. Revert a wrong block with `make unblock ID=<action_id>`.
## sentinel-lag
`fl_event_lag_seconds` > 60. Check the sentinel container health and `XPENDING fl:events sentinel`, then restart it (it resumes from checkpoints).
## sentinel-dlq
Dead-letter growth. Inspect `fl:events:dlq`, fix the cause, then requeue with `make sentinel-requeue-dlq`.
## approvals-waiting
An external draft has been waiting for approval for more than 30 min. Notify the operator.
## latency-burn
Multi-window burn on the p95 < 8 s objective. Open the Pipeline dashboard and find the slowest stage. Usual causes: sandbox pool saturation or a slow LLM (fall back to local).
## error-rate
Follow the dashboard links in the alert. For a stale feed, check egress and the feed terms. If fallback is active, check the cloud key and status.
## service-down
A scrape target has been down for 2 minutes. Run `docker compose ps` and look for `Restarting` or `unhealthy`, then `docker compose logs --tail 50 <service>`. A restart loop at startup usually means the image is older than the code on `main` (rebuild that service: `docker compose up -d --build <service>`) or a dependency in `.env` is wrong. While the Sentinel is down, checks still work, but no incident is created and the incident board stays empty; it resumes from its checkpoints when it comes back.
## sandbox-failure
See [error-rate](#error-rate): same procedure; use this alert's own dashboard panel for the specifics.
## feed-stale
The feed mirror is older than 6 hours, so hard rule H2 (known-bad address, answered at T0) is off: a listed address is still scored, but not floored at `dangerous` by the feed alone. Check that the collector is running (`scripts/collect_loop.sh`) and that `data/private/feeds/` has a recent file. The OpenPhish community feed may be polled at most every 12 hours (its terms; the collector refuses earlier polls), so plan the poll before a demo take. Never fetch a feed in a way its terms forbid.
## llm-fallback
See [error-rate](#error-rate): same procedure; use this alert's own dashboard panel for the specifics.
## route-agreement-drop
See [error-rate](#error-rate): same procedure; use this alert's own dashboard panel for the specifics.
## injection-spike
Expected under redteam replay (check `source`). On live traffic, review samples on the Security dashboard.
## ssrf-spike
See [injection-spike](#injection-spike): same procedure; use this alert's own dashboard panel for the specifics.
## fp-spike
See [injection-spike](#injection-spike): same procedure; use this alert's own dashboard panel for the specifics.
## eval-regression
Compare the latest `evals/results/` artifact with the baseline. Block merges until the cause is found.
## score-drift
See [eval-regression](#eval-regression): same procedure; use this alert's own dashboard panel for the specifics.
## canary-leak
`fl_canary_leak_total` grew: a canary token planted in a prompt came back in model output, so the reply was discarded and the template used. This must stay at 0. Find the `verdict_id` in the worker logs (the `canary leak` line), open its LLM span in Phoenix, and check which untrusted text (page, message) carried the extraction attempt. Under `make redteam` the canary cases trip this on purpose (check `source`). On live traffic treat it as an incident: keep the verdict as degraded, review the spotlighting of that input type, and do not widen any allowlist to silence the alert.

## Voice assistant ("Hey Falcon")
Speech is recognised on this machine by Whisper; audio is decoded in memory and dropped, and transcripts are never logged. `POST /v1/voice/utterance` (read scope) tries the engines in `FL_VOICE_STT_URLS` in order: the **native** engine on the Mac (`services/voice-native`, mlx-whisper large-v3-turbo on the Metal GPU, `127.0.0.1:8093`), then the **container** `voice` (faster-whisper on CPU, started by `make up`; its model downloads on first use into the `voice_models` volume, so a fresh clone is healthy at once and `/readyz` turns ready after the download). The response `model` field says which one answered (`native:...` or `container:...`).
- **Start the native engine:** `make voice-native` (detached; pid and log in `work/voice-native/`; warm-up 10 to 60 s). `make voice-native-status` shows readiness, `make voice-native-stop` stops it. Weights: `FL_WHISPER_PATH`, else `~/neo-models/whisper-large-v3-turbo` if it exists, else the Hugging Face `mlx-community/whisper-large-v3-turbo` is downloaded into `work/models/hf`. It needs about 2 to 3 GB of GPU memory; it does not touch Ollama or the llm-gate.
- **Native engine down:** the API parks it for 10 s and answers from the container (slower: see the latency artifacts under `evals/results/published/voice/`). Both down: `503 stt-unavailable`. Check `fl_voice_errors_total{reason="stt_unavailable"}`.
- **Container model still downloading:** `docker compose logs voice`; `/readyz` of the `voice` service reports `model_loaded`. The container has no internet of its own: the download goes through `voice-egress`, which may reach only huggingface.co and hf.co. Once the model is in the volume it loads from disk; `FL_VOICE_OFFLINE=true` forbids the download for good.
- **Keep it running across reboots (launchd, NOT installed by any make target):** copy `infra/voice_native/ae.falconlens.voicenative.plist`, replace `@REPO@`, `@UV@` (`command -v uv`) and `@TOKEN@` (the `FL_VOICE_TOKEN` from `.env`), save it to `~/Library/LaunchAgents/`, check with `plutil -lint`, then `launchctl bootstrap gui/$(id -u) <file>`. Remove with `launchctl bootout gui/$(id -u)/ae.falconlens.voicenative`. Stop `make voice-native` first so the port is free.
- **Measure:** `make voice-bench ENGINES="native=http://127.0.0.1:8093 container=http://127.0.0.1:18094"` (macOS `say` speech, labelled synthetic) writes `evals/results/published/voice/<time>.json`.
## Demo day
Run on the presenting Mac. Nothing acts without confirmation, and the `falcon` compose project is only ever read.
1. `make up`, then `make demo-mode-check`: a READY / NOT READY board with the reason for every failing threshold (free memory >= 25%, swap <= 2 GB, CPU idle >= 50%, no thermal limit, disk >= 15 GB, no other compose project running, link and message probe <= 8 s). Exit code 0 only when READY.
2. `make demo-mode-on` lists exactly what it would pause. Add `CONFIRM=yes` to act: other compose projects get `docker compose -p <proj> stop`, and processes named in `infra/demo_mode.yaml` get SIGSTOP. Nothing is killed, removed or pruned. What was paused goes to `work/demo_mode/state.json`. It then pre-warms Whisper, three fixture checks and the voice web route, and re-runs the check.
3. `make voice-rehearsal` speaks the English and Arabic (Majed voice) demo lines, posts them to `/v1/voice/utterance` (skipped with a message if the endpoint is not merged) and copies three demo messages to the clipboard (`~/Eaglelens/demo-kit/messages/*.txt`, else the built-in Falcon Demo Bank fixtures).
4. After the demo, `make demo-mode-off` restores exactly what `state.json` lists (`docker compose -p <proj> start`, SIGCONT). Safe to run twice, also after an interrupted pause.
To protect another project or process, leave it out of `infra/demo_mode.yaml`; to pause one, add it there.
