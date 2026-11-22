"""TEST DOUBLE for the cascade worker. Used ONLY when FL_SMOKE_FAKE_WORKER=1 (see scripts/smoke.sh).

It speaks the internal message protocol from docs/CONTRACTS.md (consume `fl:jobs`, publish
`fl:verdict:<id>`, write `fl:verdict:last:<id>`, store the final in Postgres) with canned rules so
the API + SSE path can be exercised before the real worker (T-012) lands. It does no analysis:
`make smoke` against the real worker never starts this process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import redis.asyncio as aioredis

from falcon_api.canon import canonicalize_url, sha256_hex
from falcon_api.jobs import STREAM, channel, last_key

log = logging.getLogger("falcon.fake_worker")
GROUP = "fake-worker"
_PRIVATE = re.compile(r"^(127\.|10\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|localhost$)")


def defang(url: str) -> str:
    return url.replace("http", "hxxp", 1).replace(".", "[.]")


def _evidence(
    signal: str, family: str, tier: str, polarity: str, rule: str | None
) -> dict[str, Any]:
    return {
        "id": "ev_" + re.sub(r"[^a-z0-9]", "", signal)[:16].ljust(8, "0"),
        "signal": signal,
        "family": family,
        "observed": True,
        "display": {"ar": "إشارة اختبار", "en": "Test-double signal"},
        "weight": 0,
        "polarity": polarity,
        "hard_rule": rule,
        "source": "fake_worker",
        "tier": tier,
        "confidence": 1,
    }


def classify(url: str, in_feed: bool) -> tuple[str, list[dict[str, Any]], bool, list[str]]:
    """Return (verdict, evidence, degraded, degraded_reasons) from canned rules."""
    host = (urlsplit(url).hostname or "").lower()
    if _PRIVATE.match(host):
        return "suspicious", [], True, ["ssrf_blocked"]
    if in_feed:
        return (
            "dangerous",
            [_evidence("rep.openphish", "reputation", "T0", "risk", "H2")],
            False,
            [],
        )
    if "phish" in url.lower():
        return (
            "dangerous",
            [_evidence("brand.claimed_not_owned", "brand", "T2", "risk", "H1")],
            False,
            [],
        )
    if "official" in url.lower():
        return (
            "no_warning_signs",
            [_evidence("brand.official_domain", "brand", "T1", "trust", None)],
            False,
            [],
        )
    return "suspicious", [], False, []


def build_doc(
    verdict_id: str, input_type: str, url: str | None, source: str, *, final: bool, in_feed: bool
) -> dict[str, Any]:
    verdict, evidence, degraded, reasons_deg = classify(url or "", in_feed)
    if not final:  # T0 partial: never a confident answer
        verdict, evidence = "suspicious", evidence[:0]
    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "verdict_id": verdict_id,
        "input_type": input_type,
        "canonical_url": defang(url) if url else None,
        "verdict": verdict,
        "risk_score": {"dangerous": 95, "suspicious": 50, "no_warning_signs": 10}[verdict],
        "calibrated_probability": {"dangerous": 0.97, "suspicious": 0.5, "no_warning_signs": 0.05}[
            verdict
        ],
        "evidence": evidence,
        "reasons": [
            {"ar": "إشارة اختبار", "en": "Test-double signal", "evidence_ids": [e["id"]]}
            for e in evidence[:3]
        ],
        "actions": {
            "now": {"ar": [], "en": []},
            "if_already_acted": {"ar": [], "en": []},
            "report": {"ar": "", "en": ""},
        },
        "tier_reached": "T1" if final else "T0",
        "model_route": "none",
        "degraded": degraded or input_type != "url",
        "degraded_reasons": reasons_deg or (["fake_worker"] if input_type != "url" else []),
        "final": final,
        "screenshot_url": None,
        "source": source if source in {"live", "replay", "synthetic", "fixture"} else "live",
        "latency_ms": 5,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if verdict == "no_warning_signs" and not doc["degraded"]:
        doc["actions"]["caution"] = {
            "ar": ["ابقَ حذراً دائماً"],
            "en": ["Stay careful: this is not a guarantee."],
        }
    elif verdict == "no_warning_signs":
        doc["verdict"], doc["risk_score"] = "suspicious", 50
    return doc


async def _store_final(dsn: str | None, doc: dict[str, Any]) -> None:
    if not dsn:
        return
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS verdicts (verdict_id text PRIMARY KEY, doc jsonb NOT NULL, "
            "created_at timestamptz NOT NULL DEFAULT now())"
        )
        await conn.execute(
            "INSERT INTO verdicts (verdict_id, doc) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (verdict_id) DO UPDATE SET doc = EXCLUDED.doc",
            doc["verdict_id"],
            json.dumps(doc),
        )
    finally:
        await conn.close()


async def handle(r: Any, fields: dict[str, str], dsn: str | None) -> None:
    vid = fields["verdict_id"]
    payload = json.loads(fields["payload_json"])
    url = payload.get("url")
    in_feed = False
    if url:
        host = urlsplit(url).hostname or ""
        hashes = [sha256_hex(canonicalize_url(url)), sha256_hex(host.lower())]
        in_feed = any([await r.sismember("feed:openphish", h) for h in hashes])
    for final in (False, True):
        doc = build_doc(
            vid,
            fields["input_type"],
            url,
            fields.get("source", "live"),
            final=final,
            in_feed=in_feed,
        )
        raw = json.dumps(doc)
        if final:
            await _store_final(dsn, doc)
        await r.set(last_key(vid), raw, ex=3600)
        await r.publish(channel(vid), raw)
        if not final:
            await asyncio.sleep(0.6)


async def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    r: Any = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    dsn = os.environ.get("DATABASE_URL")
    with contextlib.suppress(aioredis.ResponseError):
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    log.warning("FAKE WORKER (test double) consuming %s", STREAM)
    while True:
        res = await r.xreadgroup(GROUP, "fw-1", {STREAM: ">"}, count=10, block=2000)
        for _stream, entries in res or []:
            for entry_id, fields in entries:
                try:
                    await handle(r, fields, dsn)
                except Exception:
                    log.exception("fake worker job failed")
                await r.xack(STREAM, GROUP, entry_id)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
