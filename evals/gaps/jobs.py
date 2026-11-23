"""Raw cascade jobs for the gap evals: run fixture items through the shipped-cascade rig, append to a JSONL.

``python -m evals.gaps.jobs cascade --route local|cloud --set s12|rest|all|new|t3extra --repeats N --out NAME``

Each line of ``work/gaps/raw/<NAME>.jsonl`` is one run (full final document, every emitted document's tier/verdict,
router call log, tool calls). Raw files stay in ``work/`` (gitignored); the area reports aggregate them into
``evals/results/published/<area>/``. The run resumes: (item, repeat) pairs already in the file are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from evals.common import ROOT
from evals.gaps import corpus
from evals.gaps.rig import BudgetReached, build_rig, run_item

RAW = ROOT / "work" / "gaps" / "raw"

S12 = (
    "pg-official-login",
    "pg-look-verify-en",
    "pg-look-verify-ar",
    "pg-generic-login",
    "pg-benign-events",
    "pg-benign-recipe",
    "msg-bank-otp-en",
    "msg-bank-otp-ar",
    "msg-delivery-en",
    "msg-prize-en",
    "msg-benign-lunch",
    "msg-benign-ar",
)


def select(name: str) -> list[corpus.Item]:
    items = list(corpus.ITEMS)
    if name == "s12":
        return [i for i in items if i.item_id in S12]
    if name == "rest":
        return [i for i in items if i.item_id not in S12]
    if name == "all":
        return items
    new = corpus.new_lookalike_set()
    if name == "new":
        return new
    if name == "t3extra":  # fixtures on novel hosts that sit in the uncertain band without a hard rule
        return [i for i in new if "new_benign" in i.tags or "new_generic" in i.tags]
    raise SystemExit(f"unknown set {name}")


def _done(path: Path) -> set[tuple[str, int]]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out.add((r["item_id"], int(r["repeat"])))
    return out


async def cascade(route: str, set_name: str, repeats: int, out: str, ai: bool, cloud_cap: int) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{out}.jsonl"
    done = _done(path)
    rig = build_rig(route, ai=ai, cloud_cap=cloud_cap)
    items = select(set_name)
    meta_path = RAW / f"{out}.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "route": route,
                "ai": ai,
                "set": set_name,
                "repeats": repeats,
                "t1_fitted": rig.t1_fitted,
                "local_model": rig.router.config.local_model if rig.router is not None else None,
                "cloud_models": dict(rig.router.config.cloud_models) if rig.router is not None else None,
            }
        )
    )
    for rep in range(repeats):
        for it in items:
            if (it.item_id, rep) in done:
                continue
            try:
                run = await run_item(rig, it)
            except BudgetReached as exc:
                print("STOP:", exc, flush=True)
                return
            rec = {
                "item_id": it.item_id,
                "repeat": rep,
                "route": route,
                "ok": run.ok,
                "error": run.error,
                "ms": run.ms,
                "doc": run.doc,
                "emitted": [
                    {
                        "tier": d.get("tier_reached"),
                        "verdict": d.get("verdict"),
                        "score": d.get("risk_score"),
                        "final": d.get("final"),
                    }
                    for d in run.docs
                ],
                "calls": [asdict(c) for c in run.calls],
                "tool_calls": [{"tool": n, "arg": v} for n, v in run.tool_calls],
                "cloud_calls_total": rig.cloud_calls,
            }
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            d = run.doc or {}
            print(
                f"[{route} r{rep}] {it.item_id}: {d.get('verdict')} {d.get('risk_score')} {d.get('tier_reached')} {run.ms}ms cloud={rig.cloud_calls}",  # noqa: E501
                flush=True,
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cascade")
    c.add_argument("--route", choices=["local", "cloud"], required=True)
    c.add_argument("--set", dest="set_name", default="s12")
    c.add_argument("--repeats", type=int, default=1)
    c.add_argument("--out", required=True)
    c.add_argument("--no-ai", action="store_true")
    c.add_argument("--cloud-cap", type=int, default=300)
    e = sub.add_parser("extractor")
    e.add_argument("--route", choices=["local", "cloud"], required=True)
    e.add_argument("--cloud-cap", type=int, default=60)
    sn = sub.add_parser("sentinel")
    sn.add_argument("--route", choices=["local", "cloud"], required=True)
    sn.add_argument("--runs", type=int, default=3)
    sn.add_argument("--cloud-cap", type=int, default=60)
    a = ap.parse_args()
    if a.cmd == "cascade":
        asyncio.run(cascade(a.route, a.set_name, a.repeats, a.out, not a.no_ai, a.cloud_cap))
    elif a.cmd == "extractor":
        from evals.gaps.extractor_eval import run_route

        RAW.mkdir(parents=True, exist_ok=True)
        res = asyncio.run(run_route(a.route, a.cloud_cap))
        (RAW / f"extractor_{a.route}.json").write_text(json.dumps(res, ensure_ascii=False, default=str))
    else:
        from evals.gaps.sentinel_faith import run_route as sentinel_route

        RAW.mkdir(parents=True, exist_ok=True)
        res = asyncio.run(sentinel_route(a.route, a.runs, a.cloud_cap))
        (RAW / f"sentinel_{a.route}.json").write_text(json.dumps(res, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
