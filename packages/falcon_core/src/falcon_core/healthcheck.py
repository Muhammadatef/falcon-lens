"""Container HEALTHCHECK helper: ``python -m falcon_core.healthcheck [url]``; exit 0 = healthy."""

from __future__ import annotations

import sys
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8000/healthz"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    url = args[0] if args else DEFAULT_URL
    if not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        return 2  # only ever probe the local container
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 - scheme checked above
            return 0 if 200 <= resp.status < 300 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
