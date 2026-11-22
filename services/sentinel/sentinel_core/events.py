"""Typed event parsing and validation against contracts/event.schema.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[3]
# FL_CONTRACTS_DIR overrides the repo walk (container image copies contracts/ elsewhere)
CONTRACTS_DIR = Path(os.environ.get("FL_CONTRACTS_DIR") or REPO_ROOT / "contracts")
EVENT_SCHEMA_PATH = CONTRACTS_DIR / "event.schema.json"
INCIDENT_SCHEMA_PATH = CONTRACTS_DIR / "incident.schema.json"

# Payload keys that would carry raw page or message text. Never allowed (contract + PRIVACY).
RAW_TEXT_KEYS = frozenset(
    {
        "text",
        "raw_text",
        "body",
        "html",
        "message",
        "message_text",
        "page_text",
        "email_body",
        "content",
    }
)


class EventValidationError(ValueError):
    pass


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(EVENT_SCHEMA_PATH.read_text()))


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value)  # py3.12 accepts "Z"
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def find_raw_text(obj: Any, path: str = "payload") -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in RAW_TEXT_KEYS:
                return f"{path}.{k}"
            hit = find_raw_text(v, f"{path}.{k}")
            if hit:
                return hit
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hit = find_raw_text(v, f"{path}[{i}]")
            if hit:
                return hit
    return None


@dataclass(frozen=True)
class Event:
    event_id: str
    type: str
    occurred_at: datetime
    source: str
    payload: dict[str, Any]
    verdict_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def fingerprints(self) -> dict[str, Any]:
        fp = self.payload.get("fingerprints")
        return fp if isinstance(fp, dict) else {}


def parse_event(data: dict[str, Any]) -> Event:
    """Validate against the JSON schema (plus time parsing and the no-raw-text rule)."""
    errors = sorted(_validator().iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise EventValidationError("; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:3]))
    try:
        occurred = parse_time(data["occurred_at"])
    except ValueError as exc:
        raise EventValidationError(f"occurred_at: {exc}") from exc
    hit = find_raw_text(data["payload"])
    if hit:
        raise EventValidationError(f"raw text field not allowed: {hit}")
    return Event(
        event_id=data["event_id"],
        type=data["type"],
        occurred_at=occurred,
        source=data["source"],
        payload=data["payload"],
        verdict_id=data.get("verdict_id"),
        raw=data,
    )
