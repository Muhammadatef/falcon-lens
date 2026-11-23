"""Extractor field accuracy on labelled synthetic fixtures, per model route.

Each fixture (page visible text or message, all invented, see ``corpus``) carries author labels for the four
extractor fields. The shipped quarantined ``Extractor`` runs on it through a real router (local or cloud) with the
shipped prompt and schema. Scored per field: claimed brand (exact), script category (exact), language (exact),
requested data (exact set match and Jaccard). A call that returned no valid extraction counts as wrong on every
field and is reported as ``no_extraction``. Tokens, latency and the model id come from the router's own accounting.
"""

from __future__ import annotations

import asyncio
from typing import Any

from evals.gaps import corpus
from evals.gaps.common import mean_ci, pctl, rate
from evals.gaps.rig import BudgetReached, FixtureSandbox, make_router
from falcon_core.agent.extractor import Extractor, ExtractorInput
from falcon_core.cascade.ids import new_verdict_id
from falcon_core.llm.spotlight import UntrustedText


def _text_of(item: corpus.Item) -> tuple[str, str, tuple[UntrustedText, ...]]:
    if item.kind == "message":
        return "message", item.text or "", ()
    f = FixtureSandbox.features(item.html or "", item.url or "")
    extra = (UntrustedText("page_title", f.title),) if f.title else ()
    return "page", f.visible_text, extra


async def run_route(route: str, cloud_cap: int = 60, timeout_s: float = 90.0) -> dict[str, Any]:
    router, calls, counter = make_router(route)
    ex = Extractor(router, timeout_s=timeout_s)
    rows: list[dict[str, Any]] = []
    for item in corpus.ITEMS:
        if counter["cloud"] >= cloud_cap:
            raise BudgetReached(f"cloud call cap {cloud_cap} reached")
        kind, text, extra = _text_of(item)
        c0 = len(calls)
        res = await ex.extract(
            ExtractorInput(
                kind=kind, text=text, verdict_id=new_verdict_id(), registrable_domain=None, extra_texts=extra
            )  # type: ignore[arg-type]
        )
        x = res.extraction
        exp = item.expect
        got_req = {r.value if hasattr(r, "value") else str(r) for r in (x.requested_data if x else [])}
        jac = (
            1.0
            if not exp.requested and not got_req
            else len(exp.requested & got_req) / max(1, len(exp.requested | got_req))
        )
        my_calls = calls[c0:]
        rows.append(
            {
                "item_id": item.item_id,
                "kind": item.kind,
                "phish": item.phish,
                "tags": list(item.tags),
                "status": res.status,
                "route_used": res.route,
                "model": res.model,
                "got": None
                if x is None
                else {
                    "brand": x.claimed_brand_id,
                    "requested": sorted(got_req),
                    "script": x.script_category.value,
                    "language": x.language.value,
                    "instruction_like": x.instruction_like,
                },
                "expected": {
                    "brand": exp.brand,
                    "requested": sorted(exp.requested),
                    "script": exp.script,
                    "language": exp.lang,
                },
                "brand_ok": x is not None and x.claimed_brand_id == exp.brand,
                "script_ok": x is not None and x.script_category.value == exp.script,
                "language_ok": x is not None and x.language.value == exp.lang,
                "requested_exact": x is not None and got_req == set(exp.requested),
                "requested_jaccard": jac if x is not None else 0.0,
                "instruction_like_false_alarm": bool(x.instruction_like) if x is not None else False,
                "ms": res.ms,
                "input_tokens": sum(c.input_tokens for c in my_calls),
                "output_tokens": sum(c.output_tokens for c in my_calls),
                "cache_read_tokens": sum(c.cache_read_tokens for c in my_calls),
                "cache_write_tokens": sum(c.cache_write_tokens for c in my_calls),
                "cost_usd": sum(c.cost_usd for c in my_calls),
                "fell_back": any(c.fell_back for c in my_calls),
            }
        )
        print(f"[extractor {route}] {item.item_id}: {res.status} {res.ms}ms", flush=True)
    n = len(rows)
    ok = [r for r in rows if r["got"] is not None]
    lat = [float(r["ms"]) for r in rows]
    return {
        "route": route,
        "model": next((r["model"] for r in rows if r["model"]), None),
        "n": n,
        "no_extraction": rate(n - len(ok), n),
        "fell_back_to_other_route": rate(sum(1 for r in rows if r["fell_back"]), n),
        "field_accuracy": {
            "claimed_brand_exact": rate(sum(r["brand_ok"] for r in rows), n),
            "script_category_exact": rate(sum(r["script_ok"] for r in rows), n),
            "language_exact": rate(sum(r["language_ok"] for r in rows), n),
            "requested_data_exact_set": rate(sum(r["requested_exact"] for r in rows), n),
            "requested_data_jaccard": mean_ci([float(r["requested_jaccard"]) for r in rows]),
            "all_four_fields_exact": rate(
                sum(1 for r in rows if r["brand_ok"] and r["script_ok"] and r["language_ok"] and r["requested_exact"]),
                n,
            ),
        },
        "instruction_like_false_alarms": rate(sum(1 for r in rows if r["instruction_like_false_alarm"]), n),
        "latency_ms": {"p50": pctl(lat, 50), "p95": pctl(lat, 95), "mean": mean_ci(lat)},
        "tokens": {
            "input_total": sum(r["input_tokens"] for r in rows),
            "output_total": sum(r["output_tokens"] for r in rows),
            "cache_read_total": sum(r["cache_read_tokens"] for r in rows),
            "cache_write_total": sum(r["cache_write_tokens"] for r in rows),
            "input_mean": mean_ci([float(r["input_tokens"]) for r in rows]),
            "output_mean": mean_ci([float(r["output_tokens"]) for r in rows]),
        },
        "cloud_provider_calls": counter["cloud"],
        "rows": rows,
    }


def main(route: str) -> dict[str, Any]:
    return asyncio.run(run_route(route))
