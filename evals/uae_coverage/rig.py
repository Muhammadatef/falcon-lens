#!/usr/bin/env python3
"""Run the held-out URL set through the shipped cascade, BEFORE vs AFTER, on identical page reads.

Run inside a worker-image container attached to an ISOLATED sandbox + egress-proxy pair (compose project
``fluae``, never the live ``falcon`` project); see evals/uae_coverage/run_rig.sh for the exact commands.

    python -m evals.uae_coverage.rig --variant after  --brands /wt/data/brands.yaml --h7 1
    python -m evals.uae_coverage.rig --variant before --brands /wt/work/brands_main.yaml --h7 0

Each URL is visited by the sandbox ONCE: the first variant stores the sandbox features (or the render error) under
``--cache``; the second variant replays them, so both variants judge the same page. Network signal results (RDAP,
crt.sh) go through a file-backed signal cache shared by both runs for the same reason. The feed mirror is empty (no
reputation shortcut: every row is judged as "not on a feed") and the LLM tiers are off (FL_AI_ENABLED=false), in
both variants. Raw rows (with URLs) are written only under data/private.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from falcon_core.cascade import Cascade, CascadeDeps, HttpSandboxClient
from falcon_core.cascade.engine import CallbackSink
from falcon_core.cascade.favicons import load_brand_favicons
from falcon_core.cascade.ids import new_verdict_id
from falcon_core.cascade.models import SandboxFeatures
from falcon_core.cascade.ports import SandboxError
from falcon_core.scoring.params import load_params
from falcon_core.scoring.t1_model import load_t1_model
from falcon_core.security import GuardedHTTPClient, GuardPolicy
from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.signals.reputation.external import FEED_POST_HOSTS


class CachingSandbox:
    """First call renders through the real sandbox and stores the result; later calls replay it."""

    def __init__(self, inner: HttpSandboxClient, cache_dir: Path, replay_only: bool) -> None:
        self.inner, self.dir, self.replay_only = inner, cache_dir, replay_only
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        return self.dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    async def render(self, url: str, verdict_id: str) -> SandboxFeatures:
        p = self._path(url)
        if p.exists():
            d = json.loads(p.read_text())
            if "error" in d:
                raise SandboxError(d["error"])
            return SandboxFeatures.model_validate(d["features"])
        if self.replay_only:
            raise SandboxError("not_in_replay_cache")
        try:
            f = await self.inner.render(url, verdict_id)
        except SandboxError as exc:
            p.write_text(json.dumps({"error": exc.reason}))
            raise
        p.write_text(json.dumps({"features": f.model_dump(mode="json")}))
        return f


class FileKV:
    """Signal KV cache persisted to one JSON file (values that are not JSON are kept in memory only)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
        self.sets: dict[str, frozenset[str]] = {}

    def save(self) -> None:
        ok = {}
        for k, v in self.data.items():
            try:
                json.dumps(v)
            except TypeError:
                continue
            ok[k] = v
        self.path.write_text(json.dumps(ok))

    async def get(self, key: str) -> Any | None:
        return self.data.get(key)

    async def set(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def sismember(self, key: str, member: str) -> bool:
        return member in self.sets.get(key, frozenset())

    async def replace_set(self, key: str, members: Iterable[str]) -> int:
        self.sets[key] = frozenset(members)
        return len(self.sets[key])

    async def scard(self, key: str) -> int:
        return len(self.sets.get(key, frozenset()))


def _row(r: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    ev = doc.get("evidence", [])
    return {
        **{k: r[k] for k in ("url", "label", "group", "domain") if k in r},
        "verdict": doc.get("verdict"),
        "risk_score": doc.get("risk_score"),
        "degraded": bool(doc.get("degraded")),
        "degraded_reasons": doc.get("degraded_reasons") or [],
        "tier": doc.get("tier_reached"),
        "hard_rules": sorted({e["hard_rule"] for e in ev if e.get("hard_rule")}),
        "risk_signals": sorted({e["signal"] for e in ev if (e.get("weight") or 0) > 0}),
        "signals": sorted({e["signal"] for e in ev}),
    }


async def run(a: argparse.Namespace) -> int:
    rows = [json.loads(ln) for ln in Path(a.set).read_text().splitlines() if ln.strip()]
    params = dataclasses.replace(load_params(), h7_enabled=bool(a.h7))
    registry = BrandRegistry.from_file(a.brands)
    kv = FileKV(Path(a.cache) / "signal_kv.json")
    token = os.environ.get("FL_SANDBOX_TOKEN", "change-me-sandbox")
    sandbox = CachingSandbox(
        HttpSandboxClient(os.environ.get("FL_SANDBOX_URL", "http://sandbox:8000"), token=token, timeout_s=30.0),
        Path(a.cache) / "sandbox",
        replay_only=bool(a.replay_only),
    )
    http = GuardedHTTPClient(
        policy=GuardPolicy(post_allow_hosts=FEED_POST_HOSTS), proxy=os.environ.get("FL_EGRESS_PROXY")
    )
    deps = CascadeDeps(
        registry=registry,
        sandbox=sandbox,
        favicons=load_brand_favicons(Path(a.brands)),
        params=params,
        t1_model=load_t1_model(),
        signal_http=http,
        signal_cache=kv,
        sandbox_timeout_s=30.0,
    )
    cascade = Cascade(deps)
    sem = asyncio.Semaphore(a.workers)
    out: list[dict[str, Any]] = []

    async def one(r: dict[str, Any]) -> None:
        async with sem:
            try:
                doc = await cascade.run_url(new_verdict_id(), r["url"], CallbackSink(), source="replay")
                out.append(_row(r, doc))
            except Exception as exc:  # noqa: BLE001 - one bad row never stops the run
                out.append(
                    {**{k: r[k] for k in ("url", "label", "group", "domain") if k in r}, "error": type(exc).__name__}
                )
            if len(out) % 20 == 0:
                print(f"{a.variant}: {len(out)}/{len(rows)}", flush=True)
                kv.save()

    await asyncio.gather(*(one(r) for r in rows))
    kv.save()
    Path(a.out).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out))
    print(f"{a.variant}: wrote {len(out)} rows")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--brands", required=True)
    ap.add_argument("--h7", type=int, default=0)
    ap.add_argument("--set", default="/priv/set.jsonl")
    ap.add_argument("--cache", default="/priv/cache")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--replay-only", type=int, default=0)
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
