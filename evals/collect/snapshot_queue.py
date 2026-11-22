"""STUB (T-005 part 2): blocked on T-004 (sandbox /capture).

Reads data/private/feeds/openphish/snapshot_queue.jsonl (written by openphish.py) and will send each
entry to sandbox /capture for both profiles, recording live/dead/cloaked. Not implemented yet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openphish import FEED_DIR

QUEUE = FEED_DIR / "snapshot_queue.jsonl"


def read_queue(path: Path = QUEUE) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main() -> int:
    print(f"queued={len(read_queue())} (capture not implemented: waiting for T-004)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
