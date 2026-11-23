"""CLI: python -m scripts.local_worker {run,enqueue,status}."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from scripts.local_worker import jobs
from scripts.local_worker.daemon import Worker, setup_logging
from scripts.local_worker.safety import Refused, check_task
from scripts.local_worker.taskqueue import KINDS, ROOT, Queue, default_queue_dir


def cmd_enqueue(a: argparse.Namespace, q: Queue) -> int:
    inp = a.input if len(a.input or []) != 1 else a.input[0]
    params = json.loads(a.params) if a.params else {}
    probe = {"kind": a.kind, "input": inp, "params": params}
    try:
        check_task(probe, ROOT, KINDS, jobs.FILE_KINDS)
        task = q.enqueue(a.kind, inp, params, a.priority, a.created_by, a.id)
    except (Refused, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(task["id"])
    return 0


def cmd_status(_: argparse.Namespace, q: Queue) -> int:
    print("queue:", json.dumps(q.counts()))
    hb = q.base / "heartbeat.json"
    if hb.exists():
        d = json.loads(hb.read_text())
        age = time.time() - d["ts"]
        print(f"heartbeat: {age:.0f}s ago, state={d['state']}, pid={d['pid']}, ollama_failures={d['ollama_failures']}")
        print("current job:", d.get("current_job") or "-")
        if age > 180 and d["state"] != "running":
            print("WARNING: heartbeat is stale; the worker may not be running")
    else:
        print("heartbeat: none (worker has never run)")
    print("last results:")
    for r in q.recent(5):
        extra = f"  {r['error']}" if r.get("error") else ""
        print(f"  {r['status']:6} {r['kind']:20} {r['id']}  {r.get('seconds')}s{extra}")
    return 0


def cmd_run(a: argparse.Namespace, q: Queue) -> int:
    setup_logging(q.base)
    with httpx.Client(timeout=600.0) as client:
        w = Worker(ROOT, q, client)
        if a.once:
            print(w.tick())
        else:
            w.run_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="local_worker", description=__doc__)
    ap.add_argument("--queue-dir", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enqueue", help="add a task to work/queue/pending")
    e.add_argument("--kind", required=True, choices=KINDS)
    e.add_argument("--input", action="append", help="repo-relative file path (repeat for several)")
    e.add_argument("--params", help='JSON object, e.g. \'{"labels": ["scam", "ok"]}\'')
    e.add_argument("--priority", type=int, default=5, help="lower runs first (default 5)")
    e.add_argument("--id", default=None)
    e.add_argument("--created-by", default="cli")
    sub.add_parser("status", help="queue counts, heartbeat, last 5 results")
    r = sub.add_parser("run", help="run the daemon loop (launchd does this)")
    r.add_argument("--once", action="store_true", help="one loop step, then exit")
    a = ap.parse_args(argv)
    q = Queue(a.queue_dir or default_queue_dir())
    return {"enqueue": cmd_enqueue, "status": cmd_status, "run": cmd_run}[a.cmd](a, q)
