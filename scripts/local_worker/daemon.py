"""The 24/7 loop: one job at a time, recurring jobs only when idle, pauses when Ollama or the machine is busy."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import signal
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from scripts.local_worker import jobs, schedule
from scripts.local_worker.llm import Ollama
from scripts.local_worker.safety import Refused, check_task
from scripts.local_worker.taskqueue import KINDS, Queue

LOG = logging.getLogger("local_worker")
BACKOFF_BASE = 15.0
BACKOFF_MAX = 900.0
IDLE_SLEEP = 20.0
LOAD_FACTOR = 1.5


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)), "level": record.levelname}
        data["msg"] = record.getMessage()
        data.update(getattr(record, "extra_fields", {}))
        return json.dumps(data, ensure_ascii=False)


def setup_logging(queue_dir: Path) -> None:
    LOG.setLevel(logging.INFO)
    if LOG.handlers:
        return
    h = logging.handlers.RotatingFileHandler(queue_dir / "worker.log", maxBytes=2_000_000, backupCount=5)
    h.setFormatter(JsonFormatter())
    LOG.addHandler(h)


def log(msg: str, level: int = logging.INFO, **fields: Any) -> None:
    LOG.log(level, msg, extra={"extra_fields": fields})


def load_too_high() -> bool:
    return os.getloadavg()[0] > (os.cpu_count() or 1) * LOAD_FACTOR


def backoff_seconds(failures: int) -> float:
    return float(min(BACKOFF_MAX, BACKOFF_BASE * 2 ** max(0, failures - 1)))


class Worker:
    def __init__(
        self,
        root: Path,
        queue: Queue,
        client: httpx.Client,
        schedule_file: Path = schedule.DEFAULT_FILE,
        sleep: Callable[[float], None] | None = None,
        load_check: Callable[[], bool] = load_too_high,
        model_fn: Callable[..., str] | None = None,
    ) -> None:
        self.root, self.queue, self.llm = root, queue, Ollama(client)
        self.schedule_file = schedule_file
        self.stop = threading.Event()
        self.sleep = sleep or (lambda s: self.stop.wait(s))
        self.load_check = load_check
        self.model_fn = model_fn
        self.failures = 0
        self.state = "starting"
        self.current: str | None = None

    def heartbeat(self) -> None:
        data = {
            "ts": time.time(),
            "pid": os.getpid(),
            "state": self.state,
            "current_job": self.current,
            "ollama_failures": self.failures,
            "counts": self.queue.counts(),
        }
        tmp = self.queue.base / ".heartbeat.tmp"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.rename(self.queue.base / "heartbeat.json")

    def run_task(self, task: dict[str, Any]) -> bool:
        t0 = time.time()
        self.current = task["id"]
        self.state = "running"
        self.heartbeat()
        log("job start", job=task["id"], kind=task["kind"])
        out = self.queue.workdir(task["id"])
        try:
            check_task(task, self.root, KINDS, jobs.FILE_KINDS)
            extra = jobs.HANDLERS[task["kind"]](jobs.Ctx(self.root, out, task, self.llm, self.model_fn))
        except httpx.TransportError as e:
            self.queue.requeue(task)  # Ollama went away mid-job: not the job's fault, retry later
            self.failures += 1
            log("job requeued: ollama unreachable", logging.WARNING, job=task["id"], error=repr(e))
            self.current = None
            return False
        except Exception as e:  # noqa: BLE001  (every failure becomes a failed/ entry; the loop must go on)
            err = f"{type(e).__name__}: {e}"
            refused = isinstance(e, Refused)
            self.queue.finish(
                task,
                False,
                {"seconds": round(time.time() - t0, 1), "error": err, "refused": refused},
                error=err + "\n\n" + traceback.format_exc(),
            )
            log("job failed", logging.WARNING, job=task["id"], error=err, refused=refused)
            self.current = None
            return False
        self.queue.finish(task, True, {"seconds": round(time.time() - t0, 1), **extra})
        log("job done", job=task["id"], seconds=round(time.time() - t0, 1))
        self.current = None
        return True

    def tick(self) -> str:
        """One loop step. Returns what happened (used by tests and the heartbeat)."""
        if self.load_check():
            self.state = "paused_load"
            self.heartbeat()
            log("paused: machine busy (load average)", level=logging.INFO)
            self.sleep(60.0)
            return self.state
        if not self.llm.ping():
            self.failures += 1
            wait = backoff_seconds(self.failures)
            self.state = "paused_ollama"
            self.heartbeat()
            log("paused: ollama unreachable", logging.WARNING, backoff_s=wait, failures=self.failures)
            self.sleep(wait)
            return self.state
        self.failures = 0
        task = self.queue.claim()
        if task is None:
            try:
                name = schedule.enqueue_due(self.queue, schedule.load(self.schedule_file))
            except Exception as e:  # noqa: BLE001
                log("schedule error", logging.ERROR, error=str(e))
                name = None
            if name:
                log("scheduled job enqueued", job=name)
                self.state = "scheduled"
                return self.state
            self.state = "idle"
            self.heartbeat()
            self.sleep(IDLE_SLEEP)
            return self.state
        ok = self.run_task(task)
        self.state = "idle"
        self.heartbeat()
        return "ran_ok" if ok else "ran_failed"

    def run_forever(self) -> None:
        n = self.queue.recover()
        log("worker start", pid=os.getpid(), recovered=n)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.stop.set())
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                log("loop error", logging.ERROR, error=repr(e))
                self.sleep(30.0)
        self.state = "stopped"
        self.heartbeat()
        log("worker stop")
