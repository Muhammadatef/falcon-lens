#!/usr/bin/env python3
"""Guard: .env.example must not put comments on the same line as a value.

docker compose reads `KEY=  # comment` as the literal value '# comment', so a fresh
clone would get bogus non-empty secrets (e.g. ANTHROPIC_API_KEY). Comments go on
their own line above the variable.
"""
import re
import sys
from pathlib import Path

PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*=[^\"'\n]*\s#")


def main() -> int:
    bad = [
        f".env.example:{n}: inline comment after a value"
        for n, line in enumerate(Path(".env.example").read_text().splitlines(), 1)
        if PATTERN.match(line)
    ]
    for b in bad:
        print(b)
    print("check_env_example: " + ("FAILED" if bad else "ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
