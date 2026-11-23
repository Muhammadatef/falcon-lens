"""One handler per task kind. Handlers write only into their own output dir (under work/) and return extras
for the manifest. They get the repo root and an Ollama client; nothing else."""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
import subprocess  # noqa: S404  (runs `make` targets only; see tests/test_local_worker.py)
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.local_worker.llm import BULK_MODEL, QUALITY_MODEL, Ollama, extract_json
from scripts.local_worker.safety import check_path, input_paths

FILE_KINDS = frozenset({"synthetic_messages", "arabic_review", "label_pass", "summarize", "docstring_draft"})
AR_LETTER = re.compile(r"[ء-ي]")
STRING_LITERAL = re.compile(r"""(["'`])((?:(?!\1)[^\\\n]|\\.)*?)\1""")
MAKE_TIMEOUT = 6 * 3600


@dataclass
class Ctx:
    root: Path
    out: Path
    task: dict[str, Any]
    llm: Ollama
    model_fn: Callable[..., str] | None = None  # test hook for qwen_task

    def files(self) -> list[Path]:
        return [check_path(p, self.root) for p in input_paths(self.task)]

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.task.get("params") or {})


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def synthetic_messages(c: Ctx) -> dict[str, Any]:
    """Reuse scripts/qwen_task.py (validation pipeline). Results stay in work/qwen/<task>/ for supervisor audit."""
    sys.path.insert(0, str(c.root / "scripts"))
    try:
        import qwen_task as q
    finally:
        sys.path.pop(0)
    spec = c.files()[0]
    task_id = str(c.params.get("task_id") or c.task["id"])
    args = argparse.Namespace(
        task=task_id,
        kind=json.loads(spec.read_text(encoding="utf-8")).get("kind", "synthetic_messages"),
        spec=str(spec),
        seed=c.params.get("seed"),
        timeout=float(c.params.get("timeout", 300.0)),
    )
    rc = q.run(args, c.model_fn) if c.model_fn else q.run(args)
    qdir = q.ROOT / "work" / "qwen" / task_id
    for name in ("output.jsonl", "manifest.json"):
        if (qdir / name).exists():
            _write(c.out / name, (qdir / name).read_text(encoding="utf-8"))
    if rc != 0:
        raise RuntimeError(f"qwen_task exited {rc}")
    return {"qwen_dir": str(qdir), "needs_supervisor_audit": True}


def _ar_strings(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    found: list[tuple[str, str]] = []
    if path.suffix in (".yaml", ".yml"):

        def walk(node: Any, key: str) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{key}.{k}" if key else str(k))
            elif isinstance(node, str) and AR_LETTER.search(node):
                found.append((f"{path.name}:{key}", node))

        walk(yaml.safe_load(text), "")
    else:
        for n, line in enumerate(text.splitlines(), 1):
            for m in STRING_LITERAL.finditer(line):
                if AR_LETTER.search(m.group(2)):
                    found.append((f"{path.name}:{n}", m.group(2)))
    return found


def arabic_review(c: Ctx) -> dict[str, Any]:
    items = [kv for p in c.files() for kv in _ar_strings(p)][: int(c.params.get("max_strings", 200))]
    system = (
        "You review Arabic user-interface strings for a scam-warning app (Gulf audience, Modern Standard Arabic, "
        "calm and clear). Never suggest wording that calls a site 'safe'. Reply with JSON only: a list of "
        '{"key": ..., "suggestion": ..., "reason": ...} for strings that need a change. Reply [] if all are fine.'
    )
    out_lines: list[str] = []
    for i in range(0, len(items), 10):
        batch = items[i : i + 10]
        user = json.dumps([{"key": k, "text": t} for k, t in batch], ensure_ascii=False)
        data = extract_json(c.llm.chat(QUALITY_MODEL, system, user))
        keys = {k for k, _ in batch}
        for d in data if isinstance(data, list) else []:
            if isinstance(d, dict) and d.get("key") in keys and d.get("suggestion"):
                orig = dict(batch)[d["key"]]
                out_lines.append(json.dumps({**d, "original": orig}, ensure_ascii=False))
    _write(c.out / "suggestions.jsonl", "\n".join(out_lines) + ("\n" if out_lines else ""))
    return {"strings_reviewed": len(items), "suggestions": len(out_lines), "model": QUALITY_MODEL}


def label_pass(c: Ctx) -> dict[str, Any]:
    p = c.params
    labels = list(p.get("labels") or [])
    if not labels:
        raise ValueError("label_pass needs params.labels (list of allowed labels)")
    field = p.get("text_field", "text")
    guide = p.get("guide", "")
    system = (
        f"You label items. Allowed labels: {', '.join(labels)}. {guide}\n"
        "Reply with exactly one allowed label and nothing else."
    )
    rows = [json.loads(x) for x in c.files()[0].read_text(encoding="utf-8").splitlines() if x.strip()][
        : int(p.get("max_items", 200))
    ]
    out, bad = [], 0
    for row in rows:
        reply = c.llm.chat(BULK_MODEL, system, str(row.get(field, "")), temperature=0.0).strip().lower()
        label = next((lab for lab in labels if lab.lower() == reply.strip(" .\"'`")), None)
        bad += label is None
        out.append({**row, "local_label": label or "unknown", "label_source": "local-model", "synthetic_label": True})
    _write(c.out / "labelled.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    return {"items": len(rows), "unparsed": bad, "model": BULK_MODEL}


def summarize(c: Ctx) -> dict[str, Any]:
    limit = int(c.params.get("max_chars", 20000))
    text = c.files()[0].read_text(encoding="utf-8", errors="replace")
    tail = text[-limit:]  # logs: the end matters most
    system = "Summarise the file for an engineer: 5-10 short bullets, facts only, include errors and counts."
    _write(c.out / "summary.md", c.llm.chat(BULK_MODEL, system, tail) + "\n")
    return {"chars_read": len(tail), "model": BULK_MODEL}


def docstring_draft(c: Ctx) -> dict[str, Any]:
    path = c.files()[0]
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    todo = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and not ast.get_docstring(n)
    ][: int(c.params.get("max_items", 30))]
    system = (
        "Write a one-line docstring (max 100 chars, imperative, no quotes, no invented behaviour). "
        "Output the line only."
    )
    inserts: list[tuple[int, str]] = []
    for n in sorted(todo, key=lambda x: x.body[0].lineno, reverse=True):
        seg = ast.get_source_segment(src, n) or ""
        doc = c.llm.chat(BULK_MODEL, system, seg[:3000]).splitlines()
        text = (doc[0] if doc else "").strip().strip("\"'`")
        if not text or '"""' in text:
            continue
        first = n.body[0]
        if first.lineno == n.lineno:  # one-line def: nothing sensible to insert
            continue
        indent = " " * first.col_offset
        inserts.append((first.lineno - 1, f'{indent}"""{text}"""\n'))
    new = list(lines)
    for at, line in inserts:  # already sorted bottom to top
        new.insert(at, line)
    diff = difflib.unified_diff(lines, new, f"a/{path.name}", f"b/{path.name}")
    _write(c.out / f"{path.stem}.docstrings.patch", "".join(diff))
    return {"drafted": len(inserts), "applied": False, "model": BULK_MODEL}


def _make(c: Ctx, args: list[str], log: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(  # noqa: S603
        ["make", *args],  # noqa: S607
        cwd=c.root,
        capture_output=True,
        text=True,
        timeout=MAKE_TIMEOUT,
        check=False,
    )
    _write(c.out / log, f"$ make {' '.join(args)}\n(exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}")
    if proc.returncode != 0:
        raise RuntimeError(f"make {' '.join(args)} exited {proc.returncode}; see {log}")
    return proc


def eval_sovereign(c: Ctx) -> dict[str, Any]:
    started = time.time()
    _make(c, ["eval", "ROUTE=local"], "eval.log")
    results = c.root / "evals" / "results"
    fresh = sorted(
        (p for p in results.glob("*") if p.is_file() and p.stat().st_mtime >= started - 1),
        key=lambda p: p.stat().st_mtime,
    )
    return {"eval_artifacts": [str(p) for p in fresh], "route": "local"}


def dspy_local(c: Ctx) -> dict[str, Any]:
    _make(c, ["dspy-optimize", "LM=local"], "dspy.log")
    return {"lm": "local"}


HANDLERS: dict[str, Callable[[Ctx], dict[str, Any]]] = {
    "synthetic_messages": synthetic_messages,
    "arabic_review": arabic_review,
    "label_pass": label_pass,
    "summarize": summarize,
    "docstring_draft": docstring_draft,
    "eval_sovereign": eval_sovereign,
    "dspy_local": dspy_local,
}
