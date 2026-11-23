"""Recurring jobs: schedule.yaml + a small state file with the last enqueue time of each."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml

from scripts.local_worker.taskqueue import Queue

DEFAULT_FILE = Path(__file__).with_name("schedule.yaml")


def load(path: Path = DEFAULT_FILE) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("jobs", []))


def _fmt(value: Any, ts: str) -> Any:
    if isinstance(value, str):
        return value.replace("{ts}", ts)
    if isinstance(value, dict):
        return {k: _fmt(v, ts) for k, v in value.items()}
    if isinstance(value, list):
        return [_fmt(v, ts) for v in value]
    return value


def enqueue_due(queue: Queue, jobs: list[dict[str, Any]], now: float | None = None) -> str | None:
    """Enqueue at most one due job (the most overdue). Returns its name. Call only when the queue is empty."""
    now = time.time() if now is None else now
    state_file = queue.base / "schedule_state.json"
    state: dict[str, float] = json.loads(state_file.read_text()) if state_file.exists() else {}
    due = [
        (now - state.get(j["name"], 0.0) - j["every_hours"] * 3600, j)
        for j in jobs
        if now - state.get(j["name"], 0.0) >= j["every_hours"] * 3600
    ]
    if not due:
        return None
    _, job = max(due, key=lambda x: x[0])
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    queue.enqueue(
        job["kind"],
        input=_fmt(job.get("input"), ts),
        params=_fmt(job.get("params") or {}, ts),
        priority=job.get("priority", 8),
        created_by=f"schedule:{job['name']}",
        task_id=f"auto-{job['name']}-{ts}",
    )
    state[job["name"]] = now
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return str(job["name"])
