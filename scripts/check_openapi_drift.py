#!/usr/bin/env python3
"""OpenAPI drift check: every route the API implements must be declared in contracts/openapi.yaml.

Contracts are law: code may implement a subset of the contract (work in progress), never more.
If contracts/openapi.yaml does not exist yet the check prints a SKIPPED notice and exits 0
(visible in the log; it starts to bite as soon as the file lands).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

CONTRACT = Path("contracts/openapi.yaml")
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def main() -> int:
    if not CONTRACT.exists():
        print("openapi-drift: SKIPPED (contracts/openapi.yaml not present yet)")
        return 0
    from falcon_api.main import app

    declared = {
        (path, method)
        for path, item in (yaml.safe_load(CONTRACT.read_text()).get("paths") or {}).items()
        for method in item
        if method in METHODS
    }
    implemented = {
        (path, method) for path, item in app.openapi().get("paths", {}).items() for method in item if method in METHODS
    }
    extra = sorted(implemented - declared)
    missing = sorted(declared - implemented)
    if missing:
        print(f"openapi-drift: info: {len(missing)} contract operations not implemented yet")
    if extra:
        print("openapi-drift: FAILED, implemented but not in contracts/openapi.yaml:", file=sys.stderr)
        for path, method in extra:
            print(f"  {method.upper()} {path}", file=sys.stderr)
        return 1
    print("openapi-drift: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
