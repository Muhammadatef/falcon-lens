"""STUB (T-005 part 2): blocked on T-004 (sandbox /capture).

Reads data/private/feeds/openphish/snapshot_queue.jsonl (written by openphish.py) and will send each
entry to sandbox /capture for both profiles, recording live/dead/cloaked. Not implemented yet.

When to use it:
    Not yet useful: it is a placeholder until the sandbox /capture endpoint exists (T-004).

How to run:
    uv run python evals/collect/snapshot_queue.py

Outputs / side effects:
    Prints how many entries are queued. Read-only: it never sends a URL anywhere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openphish import FEED_DIR

QUEUE = FEED_DIR / "snapshot_queue.jsonl"


def read_queue(path: Path = QUEUE) -> list[dict[str, str]]:
    """Read the private snapshot queue file (empty list if it does not exist)."""
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main() -> int:
    """Print how many entries are queued; capture itself is not implemented yet."""
    print(f"queued={len(read_queue())} (capture not implemented: waiting for T-004)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
