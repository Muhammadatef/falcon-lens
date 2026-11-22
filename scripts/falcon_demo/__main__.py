"""python -m falcon_demo <seed|replay|urls|next|prewarm|tunnel|tunnel-stop> [args]"""

import sys

from . import ops, replay, seed


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "seed":
        return seed.main(rest)
    if cmd == "replay":
        return replay.main(rest)
    if cmd in {"urls", "next", "prewarm", "tunnel", "tunnel-stop", "reset-state"}:
        return ops.main([cmd, *rest])
    print(__doc__, file=sys.stderr)
    return 2


raise SystemExit(main(sys.argv[1:]))
