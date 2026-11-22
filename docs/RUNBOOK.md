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
## sandbox-failure
See [error-rate](#error-rate): same procedure; use this alert's own dashboard panel for the specifics.
## feed-stale
See [error-rate](#error-rate): same procedure; use this alert's own dashboard panel for the specifics.
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
