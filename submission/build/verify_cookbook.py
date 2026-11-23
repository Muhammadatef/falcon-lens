# ruff: noqa: E501
"""Fail if the cookbook mentions a make target, file path or .env key that does not exist in this checkout.

    python submission/build/verify_cookbook.py [path-to-cookbook-markdown]

Checks: every `make <target>` (in code blocks and inline code) is a Makefile target; every repository path in
inline code or code blocks exists (paths with <placeholders>, build outputs and gitignored private paths are
allowed); every `.env` key named in backticks exists in `.env.example`. Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH_ROOTS = (
    "scripts/",
    "docs/",
    "infra/",
    "services/",
    "extension/",
    "clients/",
    "contracts/",
    "data/",
    "evals/",
    "packages/",
    "config/",
    "web/",
    "reviews/",
    ".claude/",
    "submission/",
    ".mcp.json",
    "Makefile",
    "DECISIONS.md",
    "CONTRIBUTING.md",
    "docker-compose.yml",
    "TASKS.md",
)
ALLOWED_MISSING = ("data/private", "extension/dist", "work/", "evals/results/<", "extension/build")
EXTERNAL = {
    "OLLAMA_KEEP_ALIVE"
}  # variables of other programs (the Ollama server), documented in infra/ollama/README.md
SKIP_KEYS = {"FL_SMOKE_", "FL_CLOUD_MODEL_", "POSTGRES_"}  # prefixes documented as groups


def makefile_targets(text: str) -> set[str]:
    targets = set(re.findall(r"(?m)^([A-Za-z0-9_-]+):", text))
    for group in re.findall(r"(?m)^\.PHONY:(.*)$", text):
        targets.update(group.split())
    return targets


def env_keys(text: str) -> set[str]:
    return set(re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]+)=", text))


def check(md: str) -> list[str]:
    problems: list[str] = []
    targets = makefile_targets((ROOT / "Makefile").read_text(encoding="utf-8"))
    keys = env_keys((ROOT / ".env.example").read_text(encoding="utf-8"))

    code_lines: list[str] = []
    in_fence = False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            code_lines.append(line)
    inline = re.findall(r"`([^`\n]+)`", md)

    for text in code_lines + inline:
        for m in re.finditer(r"(?<![\w-])make ([a-z][a-z0-9-]*)", text):
            if m.group(1) not in targets:
                problems.append(f"make target not in Makefile: {m.group(1)}  (in: {text.strip()[:70]})")

    candidates: set[str] = set()
    for text in code_lines + inline:
        for tok in re.findall(r"[A-Za-z0-9_./<>\-]+", text):
            tok = tok.rstrip(".,;:)")
            tok = tok.removeprefix("/app/")
            if tok.startswith(PATH_ROOTS):
                candidates.add(tok)
    for tok in sorted(candidates):
        if "<" in tok or any(tok.startswith(a) for a in ALLOWED_MISSING):
            continue
        if not (ROOT / tok).exists():
            problems.append(f"path does not exist: {tok}")

    for tok in set(inline):
        if re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", tok) and re.match(
            r"(FL_|OLLAMA_|ANTHROPIC_|POSTGRES_|DATABASE_|REDIS_|GRAFANA_|OTEL_|TELEGRAM_|ALERT_|COMPOSE_)", tok
        ):
            if tok in keys or tok in EXTERNAL or any(tok.startswith(p) for p in SKIP_KEYS) or tok.endswith("_"):
                continue
            problems.append(f"env key not in .env.example: {tok}")
    return problems


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "submission" / "build" / "cookbook.rendered.md"
    problems = check(path.read_text(encoding="utf-8"))
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    print(f"verify_cookbook: {'FAIL' if problems else 'ok'} ({path.name})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
