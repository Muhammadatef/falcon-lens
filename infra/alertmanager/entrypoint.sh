#!/bin/sh
# Renders the Alertmanager config at start-up. Alertmanager has no env substitution, so the
# receiver is chosen here: Telegram only if BOTH token and chat id are set, a webhook if
# ALERT_WEBHOOK_URL is set, otherwise a null receiver (alerts stay in Grafana + Prometheus).
# Secrets go to 0600 files referenced by bot_token_file / chat_id_file, never into the YAML.
set -eu
DIR=/alertmanager
OUT="$DIR/alertmanager.rendered.yml"
umask 077

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
  group_by: [alertname, service]
  group_wait: 10s
  group_interval: 1m
  repeat_interval: 4h
receivers:
$RECEIVERS
YAML

exec /bin/alertmanager --config.file="$OUT" --storage.path="$DIR" "$@"
