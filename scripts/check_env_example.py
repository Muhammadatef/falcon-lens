#!/usr/bin/env python3
"""Guard: .env.example must have no inline comments.

Compose v5 treats `KEY=   # note` as the value `# note`, so a blank feed key silently becomes
a bogus credential. Fails (exit 1) on any `KEY=value` line where whitespace + `#` follows the `=`.

How to run: make guard  (or: python3 scripts/check_env_example.py [path])
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BAD = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=.*\s#")
BAD_EMPTY = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=\s+#")


def problems(text: str) -> list[str]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if BAD.match(line) or BAD_EMPTY.match(line):
            out.append(f"{n}: inline comment after a value (move it to its own line): {line}")
    return out


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / ".env.example"
    errs = problems(path.read_text())
    for e in errs:
        print(f"{path}:{e}", file=sys.stderr)
    if errs:
        return 1
    print("check_env_example: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
