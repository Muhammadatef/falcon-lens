"""Deterministic ULID helpers so replays reproduce the same ids."""
from __future__ import annotations

import hashlib
from datetime import datetime

from ulid import ULID


def make_ulid(ts: datetime, seed: str) -> str:
    """ULID whose time part is `ts` (ms) and whose 80 random bits are derived from `seed`."""
    ms = int(ts.timestamp() * 1000)
    rand = hashlib.sha256(seed.encode()).digest()[:10]
    return str(ULID.from_bytes(ms.to_bytes(6, "big") + rand))
