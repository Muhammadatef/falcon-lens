# ruff: noqa: E501
"""Signal plugin base: SignalSpec, SignalContext protocol, Evidence, REGISTRY.

Contracts: contracts/signal.schema.json, contracts/evidence.schema.json.
T-002 will ship pydantic mirrors; this module stays dependency-free so T1 signals are pure/offline
and the plain dict produced by ``Evidence.to_dict()`` validates against the evidence schema.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Family = Literal[
    "url",
    "domain",
    "reputation",
    "page",
    "visual",
    "brand",
    "message",
    "email",
    "image",
    "injection",
]


@dataclass(frozen=True)
class SignalSpec:
    name: str
    family: Family
    tier: Literal["T0", "T1", "T2"]
    input_types: tuple[str, ...]
    timeout_ms: int
    network: Literal["none", "egress_proxy", "local_mirror"]
    emits: tuple[str, ...]
    cache_ttl_s: int | None = None
    feature_names: tuple[str, ...] = ()
    # "enrichment": errors are informational (weight 0) and never set degraded (SCORING §4).
    criticality: Literal["critical", "enrichment"] = "critical"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "family": self.family,
            "tier": self.tier,
            "input_types": list(self.input_types),
            "timeout_ms": self.timeout_ms,
            "network": self.network,
            "emits": list(self.emits),
        }
        if self.cache_ttl_s is not None:
            d["cache_ttl_s"] = self.cache_ttl_s
        if self.feature_names:
            d["feature_names"] = list(self.feature_names)
        return d


class SignalContext(Protocol):
    """What a signal may see. T1 URL signals only read ``url``; network goes through ``http`` only."""

    input_type: str
    url: str | None
    text: str | None
    http: Any  # SSRF-guarded client (T-003); never used by T1 lexical signals
    cache: Any
    mirror: Any
    clock: Callable[[], float]
    brands: Any  # BrandRegistry | None (None -> default registry)


@dataclass
class Evidence:
    signal: str
    family: str
    observed: Any
    display: dict[str, str] | None = None
    weight: float = 0.0  # filled by the arbiter, never by a signal
    polarity: Literal["risk", "trust", "neutral"] = "risk"
    hard_rule: str | None = None
    source: str = "computed"
    tier: str = "T1"
    confidence: float = 1.0
    latency_ms: int | None = None
    error: str | None = None
    id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.id:
            blob = json.dumps([self.signal, self.observed], sort_keys=True, default=str, ensure_ascii=True)
            self.id = "ev_" + hashlib.sha256(blob.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "signal": self.signal,
            "family": self.family,
            "observed": self.observed,
            "weight": self.weight,
            "polarity": self.polarity,
            "hard_rule": self.hard_rule,
            "source": self.source,
            "tier": self.tier,
            "confidence": self.confidence,
            "error": self.error,
        }
        if self.display is not None:
            d["display"] = {k: v[:200] for k, v in self.display.items()}
        if self.latency_ms is not None:
            d["latency_ms"] = self.latency_ms
        return d


SignalFn = Callable[[SignalContext], Awaitable[list[Evidence]]]
REGISTRY: dict[str, tuple[SignalSpec, SignalFn]] = {}


def signal(spec: SignalSpec) -> Callable[[Callable[[SignalContext], list[Evidence]]], SignalFn]:
    """Register a signal. The wrapped sync body becomes ``async run(ctx)`` that enforces ``timeout_ms``,
    never raises (errors become ``Evidence.error``) and stamps ``latency_ms``.
    The sync body stays reachable as ``run.sync`` (used by the T1 classifier path and perf tests)."""

    def deco(body: Callable[[SignalContext], list[Evidence]]) -> SignalFn:
        async def run(ctx: SignalContext) -> list[Evidence]:
            t0 = time.perf_counter()

            async def inner() -> list[Evidence]:
                return body(ctx)

            # NOTE: body() is synchronous and never awaits, so wait_for cannot interrupt it:
            # timeout_ms is only enforced for awaiting bodies. T1 URL bodies are pure CPU, bounded
            # by the input length cap (MAX_URL_LEN) and measured < 5 ms p95.
            try:
                out = await asyncio.wait_for(inner(), timeout=spec.timeout_ms / 1000)
            except TimeoutError:
                out = [_error(spec, "timeout")]
            except Exception as exc:  # noqa: BLE001 - signals must never raise
                out = [_error(spec, type(exc).__name__)]
            ms = int((time.perf_counter() - t0) * 1000)
            for ev in out:
                ev.latency_ms = ms
            return out

        run.spec = spec  # type: ignore[attr-defined]
        run.sync = body  # type: ignore[attr-defined]
        if spec.name in REGISTRY:
            raise ValueError(f"duplicate signal {spec.name}")
        REGISTRY[spec.name] = (spec, run)
        return run

    return deco


def async_signal(spec: SignalSpec) -> Callable[[SignalFn], SignalFn]:
    """Register a network signal whose body is already ``async def body(ctx)``.

    Same guarantees as :func:`signal`: ``timeout_ms`` is enforced with ``asyncio.wait_for``, nothing is
    raised (errors become ``Evidence.error``) and ``latency_ms`` is stamped. Network I/O inside the body
    must go through ``ctx.http`` / ``ctx.cache`` / ``ctx.mirror`` only."""

    def deco(body: SignalFn) -> SignalFn:
        async def run(ctx: SignalContext) -> list[Evidence]:
            t0 = time.perf_counter()
            try:
                out = await asyncio.wait_for(body(ctx), timeout=spec.timeout_ms / 1000)
            except TimeoutError:
                out = [_error(spec, "timeout")]
            except Exception as exc:  # noqa: BLE001 - signals must never raise
                out = [_error(spec, f"{type(exc).__name__}: {exc}"[:200])]
            ms = int((time.perf_counter() - t0) * 1000)
            for ev in out:
                ev.latency_ms = ms
            return out

        run.spec = spec  # type: ignore[attr-defined]
        run.body = body  # type: ignore[attr-defined]
        if spec.name in REGISTRY:
            raise ValueError(f"duplicate signal {spec.name}")
        REGISTRY[spec.name] = (spec, run)
        return run

    return deco


def _error(spec: SignalSpec, msg: str) -> Evidence:
    return Evidence(
        signal=spec.name,
        family=spec.family,
        observed=None,
        polarity="neutral",
        tier=spec.tier,
        confidence=0.0,
        error=msg,
    )
