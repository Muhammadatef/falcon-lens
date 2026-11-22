from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_openapi_matches_committed() -> None:
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "gen_openapi.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
