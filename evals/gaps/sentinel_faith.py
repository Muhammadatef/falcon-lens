"""Faithfulness of Sentinel LLM summaries on replayed incidents (verifier accept rate, claim -> evidence coverage).

The incidents come from the planted Falcon Demo Bank replay fixture (``sentinel_core.fixtures.generate``, source
``replay``, synthetic: three incidents). Each incident is triaged by the real Sentinel graph with a ``RouterLLM`` over
the real router (local or cloud route). Per incident the run records:

* the raw model output of ``assess`` and ``summarise`` before the verifier (how many claims cite real evidence ids);
* whether the verifier accepted the text (``generated_by == "llm"``) or the graph fell back to the template;
* the claims that survived and the evidence ids they cite.

No score or verdict is involved: Sentinel summaries never carry one. Nothing here reads or prints a key.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from evals.common import ROOT
from evals.gaps.common import mean_ci, not_evaluated, pctl, rate

_SENTINEL_TESTS = ROOT / "services" / "sentinel" / "tests"


class Capture:
    """Router-level recorder (tokens, latency, route) shared by the LLM client."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.cloud_calls = 0


def _make_llm(route: str, capture: Capture) -> Any:
    import os

    from falcon_core.llm.config import RouterConfig
    from falcon_core.llm.router import LLMRouter
    from falcon_sentinel.llm import RouterLLM

    if route == "local":
        os.environ["FL_SOVEREIGN_MODE"] = "1"
        os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
        os.environ.setdefault("FL_LOCAL_LLM_TIMEOUT_S", "150")
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("cloud route needs ANTHROPIC_API_KEY in the process environment")
        os.environ.pop("FL_SOVEREIGN_MODE", None)
        os.environ.setdefault("FL_LLM_TIMEOUT_S", "40")
        os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
    router = LLMRouter(RouterConfig.from_env())
    orig = router.complete_json

    async def wrapped(req: Any) -> Any:
        res = await orig(req)
        cloud = sum(1 for c in res.calls if c.route == "cloud")
        capture.cloud_calls += cloud
        capture.calls.append(
            {
                "role": str(req.role),
                "route": str(res.route),
                "model": res.model,
                "status": str(res.status),
                "input_tokens": res.usage.input_tokens,
                "output_tokens": res.usage.output_tokens,
                "ms": sum(c.ms for c in res.calls),
                "cost_usd": float(res.cost_usd),
                "fell_back": bool(res.fell_back),
                "cloud_provider_calls": cloud,
            }
        )
        return res

    router.complete_json = wrapped  # type: ignore[method-assign]

    class Recording(RouterLLM):
        def __init__(self) -> None:
            super().__init__(router)
            self.raw: list[dict[str, Any]] = []

        async def complete_model(
            self, model: Any, *, system: str, user_json: dict[str, Any], on_tokens: Any = None
        ) -> Any:
            task = str(user_json.get("task"))
            try:
                v = await super().complete_model(model, system=system, user_json=user_json, on_tokens=on_tokens)
            except Exception as exc:
                self.raw.append({"task": task, "value": None, "error": type(exc).__name__})
                raise
            self.raw.append({"task": task, "value": v, "error": None})
            return v

    llm = Recording()
    llm.router_cfg = router.config  # type: ignore[attr-defined]
    return llm


async def run_route(route: str, runs: int, cloud_cap: int, capture: Capture | None = None) -> dict[str, Any]:
    if str(_SENTINEL_TESTS) not in sys.path:
        sys.path.insert(0, str(_SENTINEL_TESTS))
    from graph_helpers import make_env  # type: ignore[import-not-found]

    from falcon_sentinel.graph import evidence_view, template_reason, template_summary

    capture = capture or Capture()
    rows: list[dict[str, Any]] = []
    for run in range(runs):
        env = await make_env()
        incidents = sorted(env.cache.all(), key=lambda i: str(i["incident_id"]))
        for inc0 in incidents:
            if capture.cloud_calls >= cloud_cap:
                raise RuntimeError("cloud call cap reached")
            iid = str(inc0["incident_id"])
            llm = _make_llm(route, capture)
            t0 = time.monotonic()
            err = None
            try:
                await env.runner(llm).run(iid)
            except Exception as exc:  # noqa: BLE001 - recorded, not raised
                err = f"{type(exc).__name__}: {exc}"[:160]
            wall = time.monotonic() - t0
            inc = env.cache.get(iid) or {}
            view = evidence_view(inc) if inc else {"evidence_ids": []}
            valid = set(view["evidence_ids"])
            summ = inc.get("summary") or {}
            sev = inc.get("severity_reason") or {}
            tmpl_sev = template_reason(view) if inc else {}
            raw_sum = [r for r in llm.raw if r["task"] == "summarise"]
            raw_claims = [c for r in raw_sum if r["value"] is not None for c in r["value"].claims]
            raw_ids_ok = [bool(c.evidence_ids) and all(i in valid for i in c.evidence_ids) for c in raw_claims]
            raw_any_ok = [any(i in valid for i in c.evidence_ids) for c in raw_claims]
            kept = list(summ.get("claims") or []) if summ.get("generated_by") == "llm" else []
            rows.append(
                {
                    "run": run,
                    "incident_type": inc.get("type"),
                    "summary_by": summ.get("generated_by"),
                    "summary_route": summ.get("model_route"),
                    "assess_accepted": bool(sev) and sev.get("en") != tmpl_sev.get("en"),
                    "raw_summary_returned": bool(raw_sum) and raw_sum[0]["value"] is not None,
                    "raw_summary_error": next((r["error"] for r in raw_sum if r["error"]), None),
                    "raw_claims": len(raw_claims),
                    "raw_claims_all_ids_valid": sum(raw_ids_ok),
                    "raw_claims_some_id_valid": sum(raw_any_ok),
                    "kept_claims": len(kept),
                    "kept_claims_citing_valid_ids": sum(
                        1 for c in kept if c["evidence_ids"] and all(i in valid for i in c["evidence_ids"])
                    ),
                    "degraded": list(inc.get("degraded") or []) if isinstance(inc.get("degraded"), list) else None,
                    "wall_s": round(wall, 2),
                    "error": err,
                }
            )
            _ = template_summary  # imported to make the template path explicit in the module namespace
    n = len(rows)
    accepted = sum(1 for r in rows if r["summary_by"] == "llm")
    assess_ok = sum(1 for r in rows if r["assess_accepted"])
    raw_total = sum(r["raw_claims"] for r in rows)
    kept_total = sum(r["kept_claims"] for r in rows)
    return {
        "route": route,
        "incidents_per_run": len({r["incident_type"] for r in rows}),
        "triage_runs": n,
        "summary_verifier_accept_rate": rate(accepted, n),
        "severity_reason_accept_rate": rate(assess_ok, n),
        "raw_claims_total": raw_total,
        "raw_claims_with_all_ids_valid": rate(sum(r["raw_claims_all_ids_valid"] for r in rows), raw_total),
        "raw_claims_with_some_id_valid": rate(sum(r["raw_claims_some_id_valid"] for r in rows), raw_total),
        "claims_kept_by_verifier": rate(kept_total, sum(r["raw_claims"] for r in rows if r["summary_by"] == "llm")),
        "kept_claims_coverage": rate(sum(r["kept_claims_citing_valid_ids"] for r in rows), kept_total)
        if kept_total
        else not_evaluated("no claim survived the verifier"),
        "summaries_without_claims_or_template": n - accepted,
        "wall_s": mean_ci([r["wall_s"] for r in rows]),
        "wall_s_p50": pctl([r["wall_s"] for r in rows], 50),
        "wall_s_p95": pctl([r["wall_s"] for r in rows], 95),
        "errors": sum(1 for r in rows if r["error"]),
        "rows": rows,
        "router_calls": capture.calls,
    }
