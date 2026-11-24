"""Every markdown table row in README.md has as many cells as its header (a row copied into the wrong table breaks this)."""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def _cells(line: str) -> int:
    body = re.sub(r"`[^`]*`", "x", line.strip())  # a pipe inside inline code is not a separator
    return len(re.split(r"(?<!\\)\|", body.strip("|")))


def test_readme_table_rows_match_their_header() -> None:
    header_cells = 0
    in_table = False
    bad: list[str] = []
    for number, line in enumerate(README.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("|"):
            if not in_table:
                in_table, header_cells = True, _cells(line)
            elif _cells(line) != header_cells:
                bad.append(f"line {number}: {_cells(line)} cells, header has {header_cells}")
        else:
            in_table = False
    assert not bad, bad
