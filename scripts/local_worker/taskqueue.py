"""File queue: pending/<id>.json -> running/ -> done/<id>/ or failed/<id>/. Moves are atomic renames."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KINDS = (
    "synthetic_messages",
    "arabic_review",
    "label_pass",
    "summarize",
    "docstring_draft",
    "eval_sovereign",
    "dspy_local",
)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
ROOT = Path(__file__).resolve().parents[2]
STATES = ("pending", "running", "done", "failed")


def default_queue_dir(root: Path = ROOT) -> Path:
    return Path(os.environ.get("FL_LOCAL_WORKER_DIR", root / "work" / "queue"))


@dataclass
class Queue:
    base: Path

    def __post_init__(self) -> None:
        for d in STATES:
            (self.base / d).mkdir(parents=True, exist_ok=True)

    def _d(self, name: str) -> Path:
        return self.base / name

    def enqueue(
        self,
        kind: str,
        input: Any = None,  # noqa: A002
        params: dict[str, Any] | None = None,
        priority: int = 5,
        created_by: str = "cli",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; choose from {', '.join(KINDS)}")
        tid = task_id or f"{kind}-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{os.urandom(2).hex()}"
        if not ID_RE.match(tid):
            raise ValueError(f"bad task id {tid!r}")
        if any((self._d(s) / tid).exists() or (self._d(s) / f"{tid}.json").exists() for s in STATES):
            raise ValueError(f"task id already used: {tid}")
        task = {
            "id": tid,
            "kind": kind,
            "priority": int(priority),
            "input": input,
            "params": params or {},
            "created_by": created_by,
            "created_at": time.time(),
        }
        tmp = self._d("pending") / f".{tid}.tmp"
        tmp.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.rename(self._d("pending") / f"{tid}.json")
        return task

    def pending(self) -> list[dict[str, Any]]:
        out = []
        for f in self._d("pending").glob("*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                f.rename(self._d("failed") / f"{f.stem}.corrupt")
        return sorted(out, key=lambda t: (t.get("priority", 5), t.get("created_at", 0)))  # lower number first

    def claim(self) -> dict[str, Any] | None:
        for task in self.pending():
            src = self._d("pending") / f"{task['id']}.json"
            try:
                src.rename(self._d("running") / src.name)
            except OSError:
                continue
            return task
        return None

    def recover(self) -> int:
        """After a crash or reboot, put interrupted jobs back in pending."""
        n = 0
        for stale in self._d("running").glob("*.out"):
            shutil.rmtree(stale, ignore_errors=True)
        for f in self._d("running").glob("*.json"):
            f.rename(self._d("pending") / f.name)
            n += 1
        return n

    def workdir(self, tid: str) -> Path:
        d = self._d("running") / f"{tid}.out"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def requeue(self, task: dict[str, Any]) -> None:
        """Put a running job back (Ollama vanished mid-job); partial output is discarded."""
        shutil.rmtree(self._d("running") / f"{task['id']}.out", ignore_errors=True)
        (self._d("running") / f"{task['id']}.json").rename(self._d("pending") / f"{task['id']}.json")

    def finish(self, task: dict[str, Any], ok: bool, manifest: dict[str, Any], error: str = "") -> Path:
        state = "done" if ok else "failed"
        d = self._d(state) / task["id"]
        work = self._d("running") / f"{task['id']}.out"
        if work.exists():
            work.rename(d)
        else:
            d.mkdir(parents=True, exist_ok=True)
        if error:
            (d / "error.txt").write_text(error, encoding="utf-8")
        manifest = {**manifest, "task": task, "status": state, "finished_at": time.time()}
        (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        running = self._d("running") / f"{task['id']}.json"
        if running.exists():
            running.unlink()
        return d

    def counts(self) -> dict[str, int]:
        c = {s: len(list(self._d(s).glob("*.json"))) for s in ("pending", "running")}
        for s in ("done", "failed"):
            c[s] = len([p for p in self._d(s).iterdir() if p.is_dir()])
        return c

    def recent(self, n: int = 5) -> list[dict[str, Any]]:
        items = []
        for s in ("done", "failed"):
            for m in self._d(s).glob("*/manifest.json"):
                items.append((m.stat().st_mtime, s, m))
        out = []
        for _, s, m in sorted(items, reverse=True)[:n]:
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append(
                {
                    "id": data.get("task", {}).get("id"),
                    "kind": data.get("task", {}).get("kind"),
                    "status": s,
                    "seconds": data.get("seconds"),
                    "error": data.get("error"),
                }
            )
        return out
