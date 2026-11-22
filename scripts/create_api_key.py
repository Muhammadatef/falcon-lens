#!/usr/bin/env python3
"""Create an integration API key. The key is printed once; only its argon2id hash is stored.

    DATABASE_URL=... FL_API_KEY_PEPPER=... uv run python scripts/create_api_key.py --label "police-app" \
        --scopes check,read --rate-limit 120
    docker compose exec api python /app/scripts/create_api_key.py ...   (inside the stack)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from falcon_api.auth import SCOPES, Authenticator
from falcon_api.db import Db, PgKeyStore


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--scopes", default="check,read", help=f"comma list from {','.join(SCOPES)}")
    ap.add_argument("--rate-limit", type=int, default=60, help="requests per minute for this key")
    args = ap.parse_args(argv)
    dsn, pepper = os.environ.get("DATABASE_URL"), os.environ.get("FL_API_KEY_PEPPER")
    if not dsn or not pepper:
        print("DATABASE_URL and FL_API_KEY_PEPPER are required", file=sys.stderr)
        return 2
    db = Db(dsn)
    await db.init()
    try:
        key_id, key = await Authenticator(PgKeyStore(db), pepper).create(
            args.label, [s.strip() for s in args.scopes.split(",") if s.strip()], args.rate_limit
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        await db.close()
    print(
        f"key_id: {key_id}\nscopes: {args.scopes}\nrate_limit_per_min: {args.rate_limit}\n\nAPI KEY (shown once): {key}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
