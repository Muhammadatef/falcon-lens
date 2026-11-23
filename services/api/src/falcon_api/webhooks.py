"""Outbound webhooks for campaign alerts.

Signature: `X-Falcon-Signature: v1=<hex>` where hex = HMAC-SHA256(secret, f"{timestamp}.{body}"), with the unix
timestamp in `X-Falcon-Timestamp`. Receivers reject timestamps more than 300 s from their clock (replay window).
Targets are operator configuration (`FL_WEBHOOK_TARGETS`, comma-separated http(s) URLs), never request input.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from prometheus_client import CollectorRegistry, Counter
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = logging.getLogger("falcon.api.webhooks")

REPLAY_WINDOW_S = 300
SIG_HEADER = "X-Falcon-Signature"
TS_HEADER = "X-Falcon-Timestamp"
ID_HEADER = "X-Falcon-Delivery"
BOARD_STREAM = "fl:board"


class SignatureError(Exception):
    pass


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"v1={mac}"


def verify(secret: str, headers: dict[str, str], body: bytes, *, now: float | None = None) -> None:
    """Raise SignatureError unless the signature is valid and the timestamp is within the replay window."""
    low = {k.lower(): v for k, v in headers.items()}
    ts_raw, sig = low.get(TS_HEADER.lower(), ""), low.get(SIG_HEADER.lower(), "")
    if not ts_raw.isdigit() or not sig:
        raise SignatureError("missing or malformed signature headers")
    ts = int(ts_raw)
    if abs((now if now is not None else time.time()) - ts) > REPLAY_WINDOW_S:
        raise SignatureError("timestamp outside the replay window")
    if not hmac.compare_digest(sig.encode(), sign(secret, ts, body).encode()):
        raise SignatureError("bad signature")


def parse_targets(raw: str | None) -> list[str]:
    out = []
    for t in (raw or "").split(","):
        t = t.strip()
        if t.startswith(("http://", "https://")):
            out.append(t)
    return out


class Dispatcher:
    def __init__(
        self,
        redis: Redis,
        targets: list[str],
        secret: str,
        registry: CollectorRegistry,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        card_loader: Any = None,
        backoff_s: tuple[float, ...] = (1.0, 3.0),
    ) -> None:
        self.redis, self.targets, self.secret = redis, targets, secret
        self.transport, self.card_loader, self.backoff = transport, card_loader, backoff_s
        self.sent = Counter("fl_webhook_deliveries_total", "Webhook deliveries", ["result"], registry=registry)

    async def deliver(self, client: httpx.AsyncClient, url: str, delivery_id: str, body: bytes) -> bool:
        for attempt in range(len(self.backoff) + 1):
            ts = int(time.time())  # fresh timestamp per attempt keeps retries inside the replay window
            headers = {
                "Content-Type": "application/json",
                TS_HEADER: str(ts),
                SIG_HEADER: sign(self.secret, ts, body),
                ID_HEADER: delivery_id,
            }
            try:
                r = await client.post(url, content=body, headers=headers)
                if r.status_code < 300:
                    self.sent.labels("ok").inc()
                    return True
                if r.status_code < 500 and r.status_code != 429:
                    break  # receiver rejected it: retrying will not help
            except httpx.HTTPError:
                pass
            if attempt < len(self.backoff):
                await asyncio.sleep(self.backoff[attempt])
        self.sent.labels("failed").inc()
        return False

    async def handle(self, client: httpx.AsyncClient, stream_id: str, card: dict[str, Any]) -> None:
        if card.get("type") not in ("campaign", "kit_reuse"):
            return
        if self.card_loader is not None:
            card = await self.card_loader(card)
        body = json.dumps({"event": "campaign.alert", "id": stream_id, "data": card}, separators=(",", ":")).encode()
        await asyncio.gather(*(self.deliver(client, u, stream_id, body) for u in self.targets))

    async def run(self) -> None:
        last = "$"
        async with httpx.AsyncClient(transport=self.transport, timeout=5, follow_redirects=False) as client:
            while True:
                try:
                    res: Any = await self.redis.xread({BOARD_STREAM: last}, block=5000, count=20)
                except RedisError:
                    await asyncio.sleep(2)
                    continue
                for _stream, entries in res or []:
                    for sid, fields in entries:
                        last = sid
                        try:
                            await self.handle(client, sid, json.loads(fields.get("data", "{}")))
                        except (ValueError, TypeError):
                            log.warning("skipping malformed board entry")
