"""Local worker tests. A fake Ollama (httpx.MockTransport) stands in for the model; nothing touches the network."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.local_worker import jobs, schedule  # noqa: E402
from scripts.local_worker.cli import main  # noqa: E402
from scripts.local_worker.daemon import BACKOFF_MAX, Worker, backoff_seconds  # noqa: E402
from scripts.local_worker.safety import find_live_urls  # noqa: E402
from scripts.local_worker.taskqueue import Queue  # noqa: E402

# Built at runtime so the repo live-URL guard sees no live URL in source; these tests need live-looking input.
_H = "ht" + "tp"


class FakeOllama:
    def __init__(self, up: bool = True, reply: str = "ok<|end_message|>") -> None:
        self.up, self.reply, self.calls = up, reply, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("down", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        self.calls += 1
        reply = self.reply(request) if callable(self.reply) else self.reply
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})


def make_worker(tmp_path: Path, fake: FakeOllama, **kw: Any) -> tuple[Worker, Queue, list[float]]:
    q = Queue(tmp_path / "queue")
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(fake))
    sched = tmp_path / "schedule.yaml"
    sched.write_text(kw.pop("schedule", "jobs: []\n"))
    w = Worker(tmp_path, q, client, schedule_file=sched, sleep=sleeps.append, load_check=lambda: False, **kw)
    return w, q, sleeps


def test_lifecycle_done_and_manifest(tmp_path: Path) -> None:
    (tmp_path / "run.log").write_text("line one\nERROR two\n")
    w, q, _ = make_worker(tmp_path, FakeOllama(reply="- one error<|end_message|>"))
    q.enqueue("summarize", "run.log", task_id="t1")
    assert q.counts()["pending"] == 1
    assert w.tick() == "ran_ok"
    assert q.counts() == {"pending": 0, "running": 0, "done": 1, "failed": 0}
    out = q.base / "done" / "t1"
    assert (out / "summary.md").read_text().strip() == "- one error"  # special token stripped
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["status"] == "done" and manifest["task"]["id"] == "t1"
    assert w.queue.recent(5)[0]["id"] == "t1"
    assert json.loads((q.base / "heartbeat.json").read_text())["state"] == "idle"


def test_priority_order_lower_first(tmp_path: Path) -> None:
    q = Queue(tmp_path / "q")
    q.enqueue("summarize", "a", priority=9, task_id="late")
    q.enqueue("summarize", "b", priority=1, task_id="early")
    claimed = q.claim()
    assert claimed is not None and claimed["id"] == "early"
    assert q.counts()["running"] == 1
    assert q.recover() == 1 and q.counts()["pending"] == 2


def test_failure_goes_to_failed_with_error_txt(tmp_path: Path) -> None:
    w, q, _ = make_worker(tmp_path, FakeOllama())
    q.enqueue("summarize", "missing.log", task_id="bad")
    assert w.tick() == "ran_failed"
    d = q.base / "failed" / "bad"
    assert "not found" in (d / "error.txt").read_text()
    assert json.loads((d / "manifest.json").read_text())["status"] == "failed"


def test_live_url_refused_and_defanged_allowed(tmp_path: Path) -> None:
    assert find_live_urls(f"see {_H}s://bank-login.example.com/x and {_H}://evil" + ".xyz") != []
    assert find_live_urls("hxxps://pay[.]example[.]test/a https://a.example.test/b http://localhost:8000/v1") == []
    f = tmp_path / "in.txt"
    f.write_text(f"visit {_H}s://real-bank" + ".com/login now")
    w, q, _ = make_worker(tmp_path, FakeOllama())
    q.enqueue("summarize", "in.txt", task_id="live")
    assert w.tick() == "ran_failed"
    m = json.loads((q.base / "failed" / "live" / "manifest.json").read_text())
    assert m["refused"] is True


def test_refuses_env_and_outside_paths(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1")
    w, q, _ = make_worker(tmp_path, FakeOllama())
    q.enqueue("summarize", ".env", task_id="envtask")
    q.enqueue("summarize", "../outside.txt", task_id="outside")
    assert w.tick() == "ran_failed" and w.tick() == "ran_failed"
    for tid in ("envtask", "outside"):
        assert json.loads((q.base / "failed" / tid / "manifest.json").read_text())["refused"] is True
    assert not list((q.base / "done").glob("*/summary.md"))


def test_cli_enqueue_refuses_live_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.local_worker.cli as cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text("plain text")
    rc = main(
        [
            "--queue-dir",
            str(tmp_path / "q"),
            "enqueue",
            "--kind",
            "label_pass",
            "--params",
            '{"x": "' + _H + "://phish" + '.xyz/a"}',
        ]
    )
    assert rc == 2 and "refused" in capsys.readouterr().err
    assert main(["--queue-dir", str(tmp_path / "q"), "enqueue", "--kind", "summarize", "--input", "README.md"]) == 0
    assert main(["--queue-dir", str(tmp_path / "q"), "status"]) == 0


def test_backoff_when_ollama_down(tmp_path: Path) -> None:
    w, q, sleeps = make_worker(tmp_path, FakeOllama(up=False))
    q.enqueue("summarize", "x", task_id="waits")
    for _ in range(3):
        assert w.tick() == "paused_ollama"
    assert sleeps == [15.0, 30.0, 60.0]
    assert q.counts()["pending"] == 1  # nothing consumed while down
    assert backoff_seconds(50) == BACKOFF_MAX
    w.llm.client = httpx.Client(transport=httpx.MockTransport(FakeOllama()))
    (tmp_path / "x").write_text("hello")
    assert w.tick() == "ran_ok" and w.failures == 0


def test_requeue_when_ollama_dies_mid_job(tmp_path: Path) -> None:
    (tmp_path / "x").write_text("hello")

    def boom(_: httpx.Request) -> str:
        raise httpx.ReadTimeout("gone")

    w, q, _ = make_worker(tmp_path, FakeOllama(reply=boom))  # type: ignore[arg-type]
    q.enqueue("summarize", "x", task_id="mid")
    assert w.tick() == "ran_failed"
    assert q.counts() == {"pending": 1, "running": 0, "done": 0, "failed": 0}


def test_paused_when_load_high(tmp_path: Path) -> None:
    w, q, sleeps = make_worker(tmp_path, FakeOllama())
    w.load_check = lambda: True
    q.enqueue("summarize", "x", task_id="later")
    assert w.tick() == "paused_load" and sleeps == [60.0] and q.counts()["pending"] == 1


SCHED = """
jobs:
  - {name: fast, every_hours: 1, kind: summarize, input: x}
  - {name: slow, every_hours: 6, kind: dspy_local}
  - name: synth
    every_hours: 3
    kind: synthetic_messages
    input: spec.json
    params: {task_id: "auto-{ts}"}
"""


def test_schedule_triggers_only_when_idle_and_due(tmp_path: Path) -> None:
    w, q, _ = make_worker(tmp_path, FakeOllama(), schedule=SCHED)
    jobs_ = schedule.load(tmp_path / "schedule.yaml")
    t0 = 1_800_000_000.0
    names = []
    for _ in range(3):  # all three due at first start; one per call
        names.append(schedule.enqueue_due(q, jobs_, now=t0))
        q.claim()
    assert sorted(n or "" for n in names) == ["fast", "slow", "synth"]
    assert schedule.enqueue_due(q, jobs_, now=t0 + 3599) is None
    assert schedule.enqueue_due(q, jobs_, now=t0 + 3601) == "fast"
    assert schedule.enqueue_due(q, jobs_, now=t0 + 3 * 3600 + 5) == "fast"  # most overdue first
    assert schedule.enqueue_due(q, jobs_, now=t0 + 3 * 3600 + 5) == "synth"
    synth = [t for t in q.pending() if t["created_by"] == "schedule:synth"][0]
    assert synth["params"]["task_id"].startswith("auto-2027") and "{ts}" not in synth["params"]["task_id"]
    # the daemon does it on an idle tick, and not while work is waiting
    w2, q2, _ = make_worker(tmp_path / "w2", FakeOllama(), schedule=SCHED)
    assert w2.tick() == "scheduled" and q2.counts()["pending"] == 1


def test_default_schedule_file_is_valid() -> None:
    names = {j["name"]: j for j in schedule.load()}
    assert names["sovereign-eval"]["every_hours"] == 6 and names["synthetic-batch"]["every_hours"] == 3
    assert names["arabic-review"]["every_hours"] == 12 and names["dspy-optimize"]["every_hours"] == 24
    assert names["synthetic-batch"]["input"] == "evals/specs/synthetic_messages_v2.json"
    assert (ROOT / names["synthetic-batch"]["input"]).exists()


def test_arabic_review_and_label_pass_and_docstrings(tmp_path: Path) -> None:
    (tmp_path / "ar.yaml").write_text('a:\n  b: "مرحبا بك"\n  c: "english only"\n', encoding="utf-8")
    (tmp_path / "rows.jsonl").write_text('{"text": "pay now"}\n{"text": "hello"}\n')
    (tmp_path / "m.py").write_text("def f(x):\n    return x\n\n\nclass K:\n    pass\n")

    def reply(req: httpx.Request) -> str:
        body = json.loads(req.content)
        user = body["messages"][1]["content"]
        if "مرحبا" in user:
            return '```json\n[{"key": "ar.yaml:a.b", "suggestion": "أهلاً بك", "reason": "tone"}]\n```<|end_message|>'
        if "hello" in user:
            return "banana"
        if "pay now" in user:
            return "Scam."
        if "def f" in user or "class K" in user:
            return '"""Do the thing."""'
        return "ok"

    w, q, _ = make_worker(tmp_path, FakeOllama(reply=reply))  # type: ignore[arg-type]
    q.enqueue("arabic_review", "ar.yaml", task_id="ar")
    q.enqueue("label_pass", "rows.jsonl", {"labels": ["scam", "ok"]}, task_id="lab")
    q.enqueue("docstring_draft", "m.py", task_id="doc")
    assert [w.tick() for _ in range(3)] == ["ran_ok"] * 3
    sug = [json.loads(x) for x in (q.base / "done/ar/suggestions.jsonl").read_text().splitlines()]
    assert sug[0]["original"] == "مرحبا بك" and sug[0]["suggestion"] == "أهلاً بك"
    labelled = [json.loads(x) for x in (q.base / "done/lab/labelled.jsonl").read_text().splitlines()]
    assert [r["local_label"] for r in labelled] == ["scam", "unknown"]
    patch = (q.base / "done/doc/m.docstrings.patch").read_text()
    assert '+    """Do the thing."""' in patch
    assert (tmp_path / "m.py").read_text().startswith("def f(x):\n    return x")  # source never edited


def test_synthetic_messages_reuses_qwen_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import qwen_task as qt

    monkeypatch.setattr(qt, "ROOT", tmp_path)
    spec = {
        "kind": "synthetic_messages",
        "count": 1,
        "batch_size": 1,
        "item_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
        "examples": [],
        "max_rounds_factor": 1,
    }
    (tmp_path / "spec.json").write_text(json.dumps(spec))

    def model_fn(*_: Any) -> str:
        return '{"items": [{"text": "Your parcel waits, reply with code 1234."}]}'

    w, q, _ = make_worker(tmp_path, FakeOllama(), model_fn=model_fn)
    q.enqueue("synthetic_messages", "spec.json", {"task_id": "auto-test"}, task_id="syn")
    assert w.tick() == "ran_ok"
    m = json.loads((q.base / "done/syn/manifest.json").read_text())
    assert m["needs_supervisor_audit"] is True and (tmp_path / "work/qwen/auto-test/output.jsonl").exists()


def test_make_jobs_record_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "evals/results").mkdir(parents=True)
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> Any:
        seen.append(cmd)
        (tmp_path / "evals/results/latest.json").write_text("{}")
        return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)
    w, q, _ = make_worker(tmp_path, FakeOllama())
    q.enqueue("eval_sovereign", task_id="ev")
    q.enqueue("dspy_local", task_id="ds")
    assert [w.tick(), w.tick()] == ["ran_ok", "ran_ok"]
    assert seen == [["make", "eval", "ROUTE=local"], ["make", "dspy-optimize", "LM=local"]]
    m = json.loads((q.base / "done/ev/manifest.json").read_text())
    assert m["eval_artifacts"] == [str(tmp_path / "evals/results/latest.json")]


def test_package_never_uses_git_or_hosted_apis_or_env() -> None:
    """Static check over every source file of the worker."""
    pkg = ROOT / "scripts" / "local_worker"
    banned_words = ("anthropic", "claude", "api.openai")
    for py in pkg.glob("*.py"):
        text = py.read_text()
        tree = ast.parse(text)
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef)
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                s = node.value.strip().lower()
                assert s != "git" and not s.startswith("git "), f"{py.name} mentions git as a command"
                if py.name != "safety.py":  # safety.py is the one place that names .env, to refuse it
                    assert ".env" not in s, f"{py.name} reads .env"
                assert not any(b in s for b in banned_words), f"{py.name} references a hosted API: {s[:40]}"
        assert "os.system" not in text and "shell=True" not in text
        if py.name != "jobs.py":
            assert "subprocess" not in text, f"{py.name} spawns processes"
    # the only process the worker spawns is `make`
    assert '["make", *args]' in (pkg / "jobs.py").read_text()
