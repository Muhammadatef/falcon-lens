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
