"""Load a JSONL event stream and run it through the deterministic core."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

from .events import Event, EventValidationError, parse_event
from .incidents import IncidentStore, InMemoryIncidentStore, Sentinel


def load_jsonl(path: Path | str, strict: bool = True) -> tuple[list[Event], list[tuple[int, str]]]:
    """Returns (events, errors[(line_no, message)]). strict=True raises on the first bad line."""
    events: list[Event] = []
    errors: list[tuple[int, str]] = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(parse_event(json.loads(line)))
        except (json.JSONDecodeError, EventValidationError) as exc:
            if strict:
                raise EventValidationError(f"line {n}: {exc}") from exc
            errors.append((n, str(exc)))
    return events, errors


def replay(
    events: Iterable[Event],
    store: IncidentStore | None = None,
    vectors: dict[str, list[float]] | None = None,
    rules_path: Path | None = None,
) -> IncidentStore:
    sentinel = Sentinel(store or InMemoryIncidentStore(), vectors=vectors, rules_path=rules_path)
    sentinel.process(sorted(events, key=lambda e: (e.occurred_at, e.event_id)))
    return sentinel.store


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m sentinel_core.replay events.jsonl", file=sys.stderr)
        return 2
    events, _ = load_jsonl(argv[1])
    store = replay(events)
    for inc in store.all():
        print(json.dumps({k: inc[k] for k in ("incident_id", "type", "severity", "rule_ids", "source")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
