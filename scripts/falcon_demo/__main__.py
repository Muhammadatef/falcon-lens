"""Command dispatcher for `python -m falcon_demo <command>`.

Commands: seed, replay, scenarios, urls, next, prewarm, tunnel, tunnel-stop, reset-state, reset.

What it does:
    Reads the first argument and hands the rest to seed.main, replay.main or ops.main. Any unknown command
    prints this usage line and exits with code 2.

When to use it:
    You rarely call it directly; the Makefile defines DEMO = PYTHONPATH=scripts uv run python -m falcon_demo
    and wraps each command in a target (`make seed`, `make replay`, `make urls`, `make tunnel`, ...).

How to run:
    make seed | make replay | make urls | make demo | make demo-reset
    PYTHONPATH=scripts uv run python -m falcon_demo seed --force     (direct form, from the repo root)

Inputs / outputs:
    See the module of the chosen command. This file itself reads and writes nothing.
"""

import sys

from . import ops, replay, scenarios, seed


def main(argv: list[str]) -> int:
    """Dispatch the first argument to seed, replay or ops; 2 on an unknown command."""
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "seed":
        return seed.main(rest)
    if cmd == "replay":
        return replay.main(rest)
    if cmd == "scenarios":
        return scenarios.main(rest)
    if cmd in {"urls", "next", "prewarm", "tunnel", "tunnel-stop", "reset-state", "reset"}:
        return ops.main([cmd, *rest])
    print(__doc__, file=sys.stderr)
    return 2


raise SystemExit(main(sys.argv[1:]))
