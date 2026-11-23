"""Demo tooling package: seed, replay, prewarm, urls, tunnel and reset helpers (build prompt section 15, gate G6).

What it does:
    Holds the code behind `make seed`, `make replay`, `make demo`, `make urls`, `make tunnel`,
    `make tunnel-stop` and `make demo-reset`. Every request it sends is labelled source=replay.

When to use it:
    You normally do not import it; use the make targets. The entry point is `python -m falcon_demo <cmd>`
    (see __main__.py). Modules: common (env, API client, Redis sink), corpus (what gets seeded), seed,
    replay, ops (urls, prewarm, tunnel, reset).
"""
