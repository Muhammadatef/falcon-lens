#!/usr/bin/env python3
"""Fill empty LOCAL-ONLY secrets in .env so a fresh clone starts with `make up`.

Only secrets that exist solely inside this stack are generated (never cloud API keys).
Values are random, distinct, written in place and never printed. Existing values are kept.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

LOCAL_ONLY = ("PHOENIX_SECRET", "PHOENIX_ADMIN_SECRET", "PHOENIX_ADMIN_INITIAL_PASSWORD")


def fill(text: str) -> tuple[str, list[str]]:
    filled: list[str] = []
    for name in LOCAL_ONLY:
        pattern = re.compile(rf"^{name}=[ \t]*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(f"{name}={secrets.token_urlsafe(36)}", text, count=1)
            filled.append(name)
        elif not re.search(rf"^{name}=", text, re.MULTILINE):
            text = text.rstrip("\n") + f"\n{name}={secrets.token_urlsafe(36)}\n"
            filled.append(name)
    return text, filled


def main(path: str = ".env") -> int:
    env = Path(path)
    if not env.is_file():
        print(f"{path} not found", file=sys.stderr)
        return 1
    text, filled = fill(env.read_text(encoding="utf-8"))
    if filled:
        env.write_text(text, encoding="utf-8")
        print("generated local secrets: " + ", ".join(filled))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
