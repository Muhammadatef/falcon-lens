"""Shared helpers for cascade tests (Falcon Demo Bank fixtures only)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from prometheus_client import CollectorRegistry
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from falcon_core.cascade import (
    CallbackSink,
    Cascade,
    CascadeDeps,
    CascadeMetrics,
    SandboxClient,
    StubSandboxClient,
)
from falcon_core.cascade.engine import default_t1_signals
from falcon_core.cascade.testing import FIXTURE_POLICY, loaded_mirror, stub_resolver
from falcon_core.signals.base import SignalFn, SignalSpec
from falcon_core.signals.brands.registry import default_registry

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"


@lru_cache(maxsize=4)
def validator(name: str = "verdict") -> Draft202012Validator:
    resources = []
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], DRAFT202012.create_resource(schema)))
    registry: Registry[Any] = Registry().with_resources(resources)
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text())
    return Draft202012Validator(schema, registry=registry)


def assert_valid(doc: Mapping[str, Any], name: str = "verdict") -> None:
    errors = list(validator(name).iter_errors(json.loads(json.dumps(doc))))
    assert not errors, [e.message for e in errors[:3]]
    if name == "verdict":
        ids = {e["id"] for e in doc["evidence"]}
        for r in doc["reasons"]:
            assert set(r["evidence_ids"]) <= ids


def make_cascade(
    sandbox: SandboxClient | None = None,
    *,
    extra_signals: Mapping[str, tuple[SignalSpec, SignalFn]] | None = None,
    signals: Mapping[str, tuple[SignalSpec, SignalFn]] | None = None,
    **kw: Any,
) -> tuple[Cascade, CascadeMetrics]:
    metrics = CascadeMetrics(CollectorRegistry())
    t1 = dict(signals if signals is not None else default_t1_signals())
    t1.update(extra_signals or {})
    kw.setdefault("guard_policy", FIXTURE_POLICY)
    kw.setdefault("resolver", stub_resolver)
    kw.setdefault("mirror", loaded_mirror())  # fresh, empty: no hit, not degraded
    deps = CascadeDeps(
        registry=default_registry(),
        sandbox=sandbox or StubSandboxClient(error="no_stub"),
        metrics=metrics,
        t1_signals=t1,
        **kw,
    )
    return Cascade(deps), metrics


async def run(cascade: Cascade, url: str, vid: str | None = None, **kw: Any) -> CallbackSink:
    from falcon_core.cascade import new_verdict_id

    sink = CallbackSink()
    await cascade.run_url(vid or new_verdict_id(), url, sink, **kw)
    return sink


def rules(doc: Mapping[str, Any]) -> set[str]:
    return {e["hard_rule"] for e in doc["evidence"] if e.get("hard_rule")}


def metric(m: CascadeMetrics, name: str, labels: Mapping[str, str] | None = None) -> float:
    v = m.registry.get_sample_value(name, dict(labels or {}))
    return float(v or 0.0)
