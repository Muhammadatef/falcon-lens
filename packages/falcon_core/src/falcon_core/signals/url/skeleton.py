"""UTS #39 skeleton(), implemented in-house from the vendored Unicode confusables.txt.

skeleton(X): NFD(X) -> replace each char by its confusables.txt mapping (type MA) -> NFD.
confusable-homoglyphs 3.3.1 has no skeleton function (docs/research/VERIFIED_VERSIONS.md).
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "confusables.txt"


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    table: dict[str, str] = {}
    for raw in DATA_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 2:
            continue
        try:
            src = chr(int(parts[0], 16))
            dst = "".join(chr(int(h, 16)) for h in parts[1].split())
        except ValueError:
            continue
        table[src] = dst
    return table


def skeleton(s: str) -> str:
    t = _table()
    nfd = unicodedata.normalize("NFD", s)
    return unicodedata.normalize("NFD", "".join(t.get(c, c) for c in nfd))


def skeleton_ci(s: str) -> str:
    """Case-insensitive comparison key: skeleton then casefold, then skeleton again so that
    mappings that land on upper-case letters (0 -> O) fold consistently."""
    return skeleton(skeleton(s).casefold()).casefold()
