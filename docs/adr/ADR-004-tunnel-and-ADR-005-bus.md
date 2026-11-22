# ADR-004: Public demo through a Cloudflare quick tunnel

**Status:** Accepted · 2026-11-22 (owner choice)
`cloudflared tunnel --url https://localhost:8443` runs on the host and points at the Caddy gateway. It costs nothing and needs no domain. Risks: the URL changes on restart (the owner pastes the final URL into the submission), and the Mac must stay awake (`caffeinate`). Anonymous callers get per-IP rate limits and never receive screenshots or raw page content.

# ADR-005: Redis Streams as the event bus

**Status:** Accepted · 2026-11-22
Redis is already required for the verdict cache, single-flight locks and rate limits. Streams give consumer groups, acknowledgements, pending-entry recovery and trimming (`MAXLEN ~ 100k`). Kafka and NATS were rejected as an extra service with no benefit at hackathon scale. Stream names: `fl:events`, `fl:events:dlq`, `fl:board` (SSE fan-out).
