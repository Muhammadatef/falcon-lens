"""Offline DSPy optimisation (ADR-002). Run via `make dspy-optimize`; production never imports dspy.

    uv run --group dspy python evals/dspy/optimize.py --lm cloud|local --task summary|classifier|both

Default LM is the Anthropic API (task: claude-haiku-5-5 for the classifier, claude-sonnet-5-5 for summaries;
prompt/teacher: claude-sonnet-5-5). `--lm local` uses the sovereign model through an OpenAI-compatible endpoint
(OLLAMA_BASE_URL, default http://localhost:11434/v1, model inkling-2-mini-chat).
The Anthropic key is read from the process environment only (optionally from the single variable
ANTHROPIC_API_KEY in the file named by --env-file / FL_ENV_FILE). It is never printed, never passed as a DSPy kwarg
(so it cannot end up in cache keys) and never written to results.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packages" / "falcon_core" / "src"))

import dspy  # noqa: E402
import fl_data  # noqa: E402
import fl_metrics as M  # noqa: E402
import fl_programs as P  # noqa: E402

from falcon_core.prompts.compiled import content_sha256  # noqa: E402

# USD per million tokens (input, output): https://platform.claude.com/docs/en/about-claude/pricing, 2026-11-22
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0)}
LOCAL_MODEL = "inkling-2-mini-chat"
END_TOKENS = ("<|end_message|>", "<|im_end|>", "<|endoftext|>")
COMPILED_DIR = ROOT / "packages" / "falcon_core" / "src" / "falcon_core" / "prompts" / "compiled"


def load_key_from_env_file(path: str | None) -> None:
    """Read ONLY ANTHROPIC_API_KEY from a dotenv file into this process. Never echoes the value."""
    if os.environ.get("ANTHROPIC_API_KEY") or not path:
        return
    for line in Path(path).read_text().splitlines():
        m = re.match(r"\s*(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.*)", line)
        if m:
            os.environ["ANTHROPIC_API_KEY"] = m.group(1).strip().strip("\"'")
            return


def git_sha() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT)  # noqa: S603, S607
    return r.stdout.strip() or "unknown"


class Lms:
    def __init__(self, route: str, task: str, local_model: str) -> None:
        self.route = route
        if route == "local":
            base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
            if not base.endswith("/v1"):
                base += "/v1"
            self.task_id = self.prompt_id = local_model

            def mk(max_tokens: int) -> dspy.LM:
                return dspy.LM(
                    f"openai/{local_model}", api_base=base, api_key="ollama", max_tokens=max_tokens, temperature=0.0
                )

            self.task_lm, self.prompt_lm = mk(1200), mk(1500)
        else:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit(
                    "ANTHROPIC_API_KEY is not in the environment (cloud is the default LM). Export it, point "
                    "FL_ENV_FILE at a dotenv file that holds it, or pass --lm local."
                )
            self.task_id = "claude-haiku-5-5" if task == "classifier" else "claude-sonnet-5-5"
            self.prompt_id = "claude-sonnet-5-5"
            # Haiku 5.5 / Sonnet 5.5: omit temperature. The key comes from ANTHROPIC_API_KEY, not from kwargs.
            self.task_lm = dspy.LM(f"anthropic/{self.task_id}", max_tokens=1500, temperature=None)
            self.prompt_lm = dspy.LM(f"anthropic/{self.prompt_id}", max_tokens=2000, temperature=None)

    def cost_usd(self) -> float:
        if self.route == "local":
            return 0.0
        total = 0.0
        for lm, mid in {
            id(self.task_lm): (self.task_lm, self.task_id),
            id(self.prompt_lm): (self.prompt_lm, self.prompt_id),
        }.values():
            pin, pout = PRICES[mid]
            for h in lm.history:
                u = h.get("usage") or {}
                total += (u.get("prompt_tokens", 0) * pin + u.get("completion_tokens", 0) * pout) / 1e6
        return round(total, 4)


def strip_end_tokens(text: str) -> str:
    for t in END_TOKENS:
        text = text.replace(t, "")
    return text


# ------------------------------------------------------------------ task definitions


def summary_metric(example: Any, pred: Any, trace: Any = None) -> float | bool:
    score = M.summary_score(P.prediction_to_summary(pred), example.view)
    return score >= 0.95 if trace is not None else score


def classifier_metric(example: Any, pred: Any, trace: Any = None) -> float | bool:
    score = M.classifier_score(str(pred.script_category), bool(pred.is_scam), example.script_category)
    return score >= 1.0 if trace is not None else score


def evaluate(program: dspy.Module, devset: list[Any], metric: Callable[..., Any], threads: int) -> dict[str, Any]:
    res = dspy.Evaluate(devset=devset, metric=metric, num_threads=threads, display_progress=False)(program)
    return {"score": round(float(res.score) / 100, 4), "results": res.results}


def summary_report(results: list[Any]) -> dict[str, Any]:
    comps: list[dict[str, float]] = []
    for ex, pred, _score in results:
        if pred is None or not hasattr(pred, "summary_en"):
            comps.append({k: 0.0 for k in [*M.WEIGHTS, "hygiene_ok", "all_claims_faithful"]})
            continue
        comps.append(M.summary_components(P.prediction_to_summary(pred), ex.view))
    n = max(len(comps), 1)
    return {k: round(sum(c[k] for c in comps) / n, 4) for k in comps[0]} if comps else {}


def classifier_report(results: list[Any]) -> dict[str, Any]:
    gold = [ex.script_category for ex, _p, _s in results]
    pred = [str(getattr(p, "script_category", "")) for _e, p, _s in results]
    return M.per_class_f1(gold, pred)


def export(name: str, program: dspy.Module, route: str, meta: dict[str, Any]) -> Path:
    pred = program.predictors()[0]
    sig = pred.signature
    demos = []
    for d in pred.demos[:4]:
        d = dict(d.items()) if hasattr(d, "items") else dict(d)
        inputs = {k: d.get(k) for k in sig.input_fields}
        outputs = {k: d.get(k) for k in sig.output_fields}
        for k, v in list(inputs.items()):
            if isinstance(v, str) and v.startswith("{"):
                with contextlib.suppress(ValueError):
                    inputs[k] = json.loads(v)
        for k, v in list(outputs.items()):
            if isinstance(v, list):
                outputs[k] = [x.model_dump() if hasattr(x, "model_dump") else x for x in v]
        demos.append({"inputs": inputs, "outputs": outputs})
    instructions = sig.instructions
    body = {
        "schema_version": 1,
        "name": name,
        "inputs": list(sig.input_fields),
        "outputs": list(sig.output_fields),
        "instructions": instructions,
        "demos": demos,
        "content_sha256": content_sha256(instructions, demos),
        "metadata": meta,
    }
    path = COMPILED_DIR / f"{name}.json"
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run_task(args: argparse.Namespace, task: str, lms: Lms, ts: str) -> dict[str, Any]:
    t0 = time.time()
    if task == "summary":
        ts_, vs_ = args.summary_train_seeds, args.summary_val_seeds
        ds = fl_data.build_incident_dataset(range(1, ts_ + 1), range(101, 101 + vs_))
        mk_ex, metric, report, base, name = (
            P.summary_example,
            summary_metric,
            summary_report,
            P.summary_program,
            "incident_summary",
        )
        extra = {
            "train_seeds": f"1-{ts_}",
            "val_seeds": f"101-{100 + vs_}",
            "source": "sentinel replay fixtures (synthetic)",
        }
    else:
        ds = fl_data.build_message_dataset(max_train=args.max_train, max_val=args.max_val)
        mk_ex, metric, report, base, name = (
            P.classifier_example,
            classifier_metric,
            classifier_report,
            P.classifier_program,
            "scam_script",
        )
        extra = {"source": fl_data.load_messages()[1], "synthetic": True}
    train = [mk_ex(i) for i in ds["train"]]
    val = [mk_ex(i) for i in ds["val"]]
    if args.smoke:
        train, val = train[:6], val[:4]
    dhash = fl_data.dataset_hash([*ds["train"], *ds["val"]])
    dspy.configure(lm=lms.task_lm, adapter=dspy.ChatAdapter())
    print(f"[{task}] train={len(train)} val={len(val)} dataset_sha256={dhash[:12]} lm={lms.task_id}", flush=True)

    before = evaluate(base(), val, metric, args.threads)
    print(f"[{task}] BEFORE val score {before['score']}", flush=True)
    candidates: dict[str, dict[str, Any]] = {"seed": {"program": base(), **before, "seconds": 0.0}}

    optimizer = (args.summary_optimizer if task == "summary" else None) or args.optimizer
    if optimizer in ("bootstrap", "both"):
        s = time.time()
        opt = dspy.BootstrapFewShotWithRandomSearch(
            metric=metric,
            max_bootstrapped_demos=2,
            max_labeled_demos=2,
            num_candidate_programs=args.candidates,
            num_threads=args.threads,
            max_errors=20,
        )
        prog = opt.compile(base(), trainset=train, valset=train)
        r = evaluate(prog, val, metric, args.threads)
        candidates["bootstrap_random_search"] = {"program": prog, **r, "seconds": round(time.time() - s, 1)}
        print(f"[{task}] bootstrap val {r['score']} ({candidates['bootstrap_random_search']['seconds']}s)", flush=True)
    if optimizer in ("mipro", "both"):
        s = time.time()
        opt = dspy.MIPROv2(
            metric=metric,
            prompt_model=lms.prompt_lm,
            task_model=lms.task_lm,
            auto="light",
            num_threads=args.threads,
            max_bootstrapped_demos=2,
            max_labeled_demos=2,
            seed=9,
        )
        prog = opt.compile(
            base(), trainset=train, valset=val if args.mipro_on_val else None, requires_permission_to_run=False
        )
        r = evaluate(prog, val, metric, args.threads)
        candidates["mipro_v2_light"] = {"program": prog, **r, "seconds": round(time.time() - s, 1)}
        print(f"[{task}] mipro val {r['score']} ({candidates['mipro_v2_light']['seconds']}s)", flush=True)

    best_name = max(candidates, key=lambda k: (candidates[k]["score"], k == "seed"))
    best = candidates[best_name]
    cost = lms.cost_usd()
    if cost > args.max_cost:
        print(f"[{task}] WARNING estimated cost ${cost} exceeds cap ${args.max_cost}", file=sys.stderr)
    meta = {
        "dspy_version": dspy.__version__,
        "route": lms.route,
        "task_lm": lms.task_id,
        "prompt_lm": lms.prompt_id,
        "optimizer": best_name,
        "dataset_sha256": dhash,
        "seeds": {"optimizer": 9, "data": 7},
        "val_before": before["score"],
        "val_after": best["score"],
        "n_train": len(train),
        "n_val": len(val),
        "generated_at": ts,
        "git_sha": git_sha(),
        **extra,
    }
    exported = None
    if not args.no_export and not args.smoke:
        exported = str(export(name, best["program"], lms.route, meta).relative_to(ROOT))
    return {
        "task": task,
        "dataset_sha256": dhash,
        "n_train": len(train),
        "n_val": len(val),
        "before": {"val_score": before["score"], "detail": report(before["results"])},
        "after": {"optimizer": best_name, "val_score": best["score"], "detail": report(best["results"])},
        "candidates": {k: {"val_score": v["score"], "seconds": v["seconds"]} for k, v in candidates.items()},
        "seconds": round(time.time() - t0, 1),
        "estimated_cost_usd": cost,
        "exported": exported,
        "meta": meta,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lm", choices=["cloud", "local"], default="cloud")
    ap.add_argument("--task", choices=["summary", "classifier", "both"], default="both")
    ap.add_argument("--optimizer", choices=["bootstrap", "mipro", "both"], default="both")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--candidates", type=int, default=4)
    ap.add_argument("--max-train", type=int, default=72)
    ap.add_argument("--max-val", type=int, default=54)
    ap.add_argument("--summary-train-seeds", type=int, default=12, help="fixture seeds 1..N for training")
    ap.add_argument("--summary-val-seeds", type=int, default=8, help="fixture seeds 101..100+N for validation")
    ap.add_argument("--summary-optimizer", choices=["bootstrap", "mipro", "both"], default=None)
    ap.add_argument("--max-cost", type=float, default=8.0, help="USD cap; the run warns and stops starting new tasks")
    ap.add_argument("--local-model", default=os.environ.get("FL_DSPY_LOCAL_MODEL", LOCAL_MODEL))
    ap.add_argument("--env-file", default=os.environ.get("FL_ENV_FILE"))
    ap.add_argument("--cache-dir", default=str(ROOT / "evals" / "results" / ".dspy_cache"))
    ap.add_argument("--mipro-on-val", action="store_true", help="NOT recommended: lets MIPRO see val")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="tiny run, nothing exported")
    args = ap.parse_args()

    load_key_from_env_file(args.env_file)
    dspy.configure_cache(enable_disk_cache=True, enable_memory_cache=True, disk_cache_dir=args.cache_dir)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    t0 = time.time()
    tasks = ["summary", "classifier"] if args.task == "both" else [args.task]
    results, spent = [], 0.0
    for t in tasks:
        if spent > args.max_cost:
            print("cost cap reached, skipping", t, file=sys.stderr)
            break
        lms = Lms(args.lm, t, args.local_model)
        results.append(run_task(args, t, lms, ts))
        spent += results[-1]["estimated_cost_usd"]
    out = {
        "kind": "dspy_optimisation",
        "synthetic_data": True,
        "generated_at": ts,
        "git_sha": git_sha(),
        "dspy_version": dspy.__version__,
        "route": args.lm,
        "args": {k: v for k, v in vars(args).items() if k != "env_file"},
        "tasks": results,
        "total_seconds": round(time.time() - t0, 1),
        "estimated_cost_usd": round(spent, 4),
        "pricing_source": "https://platform.claude.com/docs/en/about-claude/pricing (2026-11-22)",
        "note": "Validation side only; frozen test split untouched. Cloud and local numbers are separate runs.",
    }
    dest = ROOT / "evals" / "results" / f"dspy-{ts}.json"
    if not args.smoke:
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    for r in results:
        print(
            f"{r['task']}: before {r['before']['val_score']} -> after {r['after']['val_score']} ({r['after']['optimizer']})"
        )
    print(f"total {out['total_seconds']}s, est. cost ${out['estimated_cost_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
