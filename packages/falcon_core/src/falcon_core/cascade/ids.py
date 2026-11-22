"""ULID ids (``vd_`` verdicts, ``evt_`` events) and deterministic evidence ids."""

from __future__ import annotations

import hashlib
import json
import re

from ulid import ULID

VERDICT_ID_RE = re.compile(r"^vd_[0-9A-HJKMNP-TV-Z]{26}$")


def new_verdict_id() -> str:
    return f"vd_{ULID()}"


def new_event_id() -> str:
    return f"evt_{ULID()}"


def is_verdict_id(value: str) -> bool:
    return bool(VERDICT_ID_RE.match(value))


def evidence_id(signal: str, observed: object) -> str:
    """Same scheme as ``signals.base.Evidence``: ``ev_`` + sha256(signal, observed)[:16]."""
    blob = json.dumps([signal, observed], sort_keys=True, default=str, ensure_ascii=True)
    return "ev_" + hashlib.sha256(blob.encode()).hexdigest()[:16]
