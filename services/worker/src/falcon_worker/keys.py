"""Redis names shared with the API (docs/CONTRACTS.md, "Internal messages (API <-> worker)")."""

from __future__ import annotations

JOBS_STREAM = "fl:jobs"
JOBS_GROUP = "workers"
JOBS_DEAD = "fl:jobs:dead"
EVENTS_STREAM = "fl:events"
EVENTS_MAXLEN = 100_000

LAST_TTL_S = 3600
SINGLE_FLIGHT_TTL_S = 120
CLAIM_TTL_S = 300
VC_TTL_S = {"dangerous": 24 * 3600, "suspicious": 3600, "no_warning_signs": 6 * 3600}


def channel(verdict_id: str) -> str:
    """Pub/sub channel for partial and final verdicts."""
    return f"fl:verdict:{verdict_id}"


def last_key(verdict_id: str) -> str:
    """Latest verdict JSON for late SSE subscribers (``EX 3600``)."""
    return f"fl:verdict:last:{verdict_id}"


def verdict_cache(fingerprint: str) -> str:
    """``vc:<fingerprint>`` = verdict_id of a final verdict (TTL by verdict)."""
    return f"vc:{fingerprint}"


def blob_key(verdict_id: str) -> str:
    return f"fl:blob:{verdict_id}"


def worker_single_flight(fingerprint: str) -> str:
    """Worker-side single-flight lock (the API's own lock is ``sf:<fingerprint>``)."""
    return f"fl:wsf:{fingerprint}"


def claim_key(verdict_id: str) -> str:
    """Idempotency claim: which stream entry is processing this verdict_id."""
    return f"fl:wclaim:{verdict_id}"
