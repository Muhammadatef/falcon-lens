"""Refusal rules. A task is refused (never run) when it could expose secrets or live phishing URLs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
SAFE_SUFFIXES = (".test", ".example", ".invalid")
SAFE_HOSTS = {"localhost", "127.0.0.1"}
MAX_SCAN_BYTES = 2_000_000


class Refused(Exception):
    """The task breaks a hard safety rule; it moves to failed/ without running."""


def host_is_safe(host: str) -> bool:
    h = host.lower().rstrip(".")
    return h in SAFE_HOSTS or h.endswith(SAFE_SUFFIXES)


def find_live_urls(text: str) -> list[str]:
    """Non-defanged http(s) URLs whose host is not a reserved test name. hxxp:// and example[.]test never match."""
    bad = []
    for m in URL_RE.finditer(text):
        try:
            host = urlsplit(m.group(0)).hostname or ""
        except ValueError:
            host = ""
        if not host_is_safe(host):
            bad.append(m.group(0)[:80])
    return bad


def check_path(raw: str, root: Path) -> Path:
    root = root.resolve()
    p = Path(raw)
    p = p.resolve() if p.is_absolute() else (root / p).resolve()
    if root not in (p, *p.parents):
        raise Refused(f"path outside the repository: {raw}")
    rel = p.relative_to(root)
    if any(part.startswith(".env") for part in rel.parts) or rel.parts[:2] == ("data", "private"):
        raise Refused(f"path is off limits (secrets or private data): {raw}")
    return p


def input_paths(task: dict[str, Any]) -> list[str]:
    inp = task.get("input")
    if isinstance(inp, str):
        return [inp] if inp else []
    if isinstance(inp, list):
        return [str(x) for x in inp]
    return []


def check_task(task: dict[str, Any], root: Path, kinds: tuple[str, ...], file_kinds: frozenset[str]) -> None:
    """Raise Refused unless the task is safe. Scans the spec itself and every input file's text."""
    if task.get("kind") not in kinds:
        raise Refused(f"unknown kind: {task.get('kind')!r}")
    probes = [str(task.get("params", {})), str(task.get("input", ""))]
    if task["kind"] in file_kinds:
        for raw in input_paths(task):
            path = check_path(raw, root)
            if not path.is_file():
                raise Refused(f"input file not found: {raw}")
            probes.append(path.read_bytes()[:MAX_SCAN_BYTES].decode("utf-8", "replace"))
    for text in probes:
        bad = find_live_urls(text)
        if bad:
            raise Refused(f"input contains non-defanged URL(s): {bad[0]} (use hxxps://name[.]test)")
