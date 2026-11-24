#!/bin/sh
# entrypoint.sh - container entrypoint that renders the Alertmanager config, then starts Alertmanager.
#
# What it does:
#   Alertmanager has no env substitution, so this script picks the receiver at start-up: Telegram only if
#   BOTH TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set; otherwise a webhook if ALERT_WEBHOOK_URL is set;
#   otherwise a null receiver (alerts stay visible in Grafana and Prometheus). Alerts with source="replay"
#   (demo data) always go to the null receiver, so they never page anyone. It then `exec`s alertmanager.
#
# When to use it:
#   You do not run it by hand; the alertmanager container runs it (see the compose file).
#
# How to run:
#   make up        (starts the whole stack, including this container)
#
# Inputs:
#   Env TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALERT_WEBHOOK_URL (all optional) and any extra arguments, which
#   are passed on to alertmanager.
#
# Outputs / side effects:
#   Writes /alertmanager/alertmanager.rendered.yml and, if used, secret files in /alertmanager with
#   permissions 0600 (the secrets are referenced by file, never copied into the YAML). Deletes secret files
#   left over from a previous mode. Logs which receiver is enabled but never the secret values.
set -eu
DIR=/alertmanager
OUT="$DIR/alertmanager.rendered.yml"
umask 077
# Drop secrets left over from a previous mode (e.g. Telegram was disabled since).
rm -f "$DIR/telegram_bot_token" "$DIR/telegram_chat_id" "$DIR/webhook_url"

RECEIVERS="  - name: 'null'"
ROUTE_RECEIVER="null"

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  printf '%s' "$TELEGRAM_BOT_TOKEN" > "$DIR/telegram_bot_token"
  printf '%s' "$TELEGRAM_CHAT_ID" > "$DIR/telegram_chat_id"
  ROUTE_RECEIVER="telegram"
  RECEIVERS="$RECEIVERS
  - name: telegram
    telegram_configs:
      - bot_token_file: $DIR/telegram_bot_token
        chat_id_file: $DIR/telegram_chat_id
        parse_mode: ''
        send_resolved: true
        message: |-
          [{{ .Status | toUpper }}] {{ .CommonLabels.alertname }} ({{ .CommonLabels.severity }})
          {{ range .Alerts }}{{ .Annotations.summary }}
          Runbook: {{ .Annotations.runbook_url }}
          {{ end }}"
  echo "alertmanager: telegram receiver enabled" >&2
elif [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
  printf '%s' "$ALERT_WEBHOOK_URL" > "$DIR/webhook_url"
  ROUTE_RECEIVER="webhook"
  RECEIVERS="$RECEIVERS
  - name: webhook
    webhook_configs:
      - url_file: $DIR/webhook_url
        send_resolved: true"
  echo "alertmanager: webhook receiver enabled" >&2
else
  echo "alertmanager: no Telegram/webhook configured, using null receiver" >&2
fi

cat > "$OUT" <<YAML
route:
  receiver: '$ROUTE_RECEIVER'
  group_by: [alertname, service, source]
  group_wait: 10s
  group_interval: 1m
  repeat_interval: 4h
  routes:
    # Replayed/synthetic data never pages anyone.
    - matchers: ['source="replay"']
      receiver: 'null'
    # Info alerts (e.g. HuntQuotaExhausted) are dashboard-only: they never page anyone.
    - matchers: ['severity="info"']
      receiver: 'null'
receivers:
$RECEIVERS
YAML

exec /bin/alertmanager --config.file="$OUT" --storage.path="$DIR" "$@"
