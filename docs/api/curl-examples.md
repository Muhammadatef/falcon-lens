# REST v1: curl examples

Defanged placeholders only. Set `B=https://localhost:8443` and `K=<your key>` (`-k` accepts the local CA).

```bash
B=https://localhost:8443; K=fl_sandbox_demo_key   # sandbox key = check only; mint a `read` key for campaigns/incidents

# Check a URL and wait up to 8 s for the best verdict
curl -sk -X POST "$B/v1/check/url?wait=8" -H "X-API-Key: $K" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' -d '{"url":"http://falcon-demo-bank.test/login"}'

# Poll / stream a verdict
curl -sk -H "X-API-Key: $K" "$B/v1/verdicts/vd_XXXXXXXXXXXXXXXXXXXXXXXXXX"
curl -skN -H "X-API-Key: $K" "$B/v1/verdicts/vd_XXXXXXXXXXXXXXXXXXXXXXXXXX/events"

# Message and email
curl -sk -X POST "$B/v1/check/message" -H "X-API-Key: $K" -H 'Content-Type: application/json' -d '{"text":"message text"}'
curl -sk -X POST "$B/v1/check/email" -H "X-API-Key: $K" -F 'file=@sample.eml;type=message/rfc822'

# Citizen report (hashes only) and feedback
curl -sk -X POST "$B/v1/reports" -H "X-API-Key: $K" -H 'Content-Type: application/json' \
  -d '{"kind":"url","text":"http://falcon-demo-bank.test/login"}'
curl -sk -X POST "$B/v1/feedback" -H "X-API-Key: $K" -H 'Content-Type: application/json' \
  -d '{"verdict_id":"vd_XXXXXXXXXXXXXXXXXXXXXXXXXX","rating":"false_alarm"}'

# Campaigns and incidents (cursor pagination)
curl -sk -H "X-API-Key: $K" "$B/v1/campaigns?limit=10"
curl -sk -H "X-API-Key: $K" "$B/v1/incidents?status=open&severity=high&limit=10&cursor=<next_cursor>"
curl -skN -H "X-API-Key: $K" "$B/v1/incidents/stream"
curl -skN -H "X-API-Key: $K" "$B/v1/campaigns/stream"

# Operator: approve or reject a held action (Bearer works too)
curl -sk -X POST -H "Authorization: Bearer $OPERATOR_KEY" "$B/v1/incidents/inc_XXXXXXXXXXXXXXXXXXXXXXXXXX/actions/act_1/approve"

# STIX 2.1 and meta
curl -sk -H "X-API-Key: $INTEL_KEY" "$B/v1/intel/stix?status=open" -o bundle.json
curl -sk "$B/v1/meta"

# MCP (JSON-RPC over streamable HTTP)
curl -sk -X POST "$B/mcp" -H "Authorization: Bearer $FL_MCP_BEARER_TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Verify a webhook (Python): `from falcon_lens_client import verify_webhook; verify_webhook(secret, request.headers, raw_body)`.
