"""Shipped-cascade rig for the gap evals (offline substitutes, a real model answers).

Builds ``falcon_core.cascade.Cascade`` the way ``falcon_worker.main.build_worker`` does (same ``build_ai`` call:
real quarantined extractor, investigator, injection detector, fitted T1 model, arbiter, default brand registry).
The substitutes are the same as the red-team shipped mode (PR #84, ``evals/redteam/shipped.py``, which this module
mirrors in a trimmed form so the gap evals do not depend on that branch landing): fixture-backed renderer instead of
the Playwright sandbox, stub DNS, no network signals, empty OpenPhish mirror. No live site is ever contacted and no
key is ever read here: the cloud route needs ``ANTHROPIC_API_KEY`` already in the process environment.

On top of the red-team rig this one records every router call (route, model id, tokens, latency, cost) and every
document the cascade emitted (so tier-by-tier verdicts, e.g. T1/T2 before T3, can be compared).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.gaps.corpus import Item
from evals.redteam.html_segments import page_features
from falcon_core.cascade.engine import CallbackSink, Cascade, CascadeDeps
from falcon_core.cascade.models import SandboxFeatures, SandboxForm
from falcon_core.cascade.ports import SandboxError
from falcon_core.cascade.testing import FIXTURE_HOSTS, STUB_PUBLIC_IP, loaded_mirror
from falcon_core.security import GuardPolicy
from falcon_core.signals import REGISTRY
from falcon_core.signals.cache import MemoryCache

CASE_TIMEOUT_S = 240.0
EVAL_EXTRACTOR_TIMEOUT_S = 90.0
EVAL_INVESTIGATOR_TIMEOUT_S = 240.0
CLOUD_CALL_CAP = 300
CLEAN_PAGE = Path(__file__).resolve().parents[2] / "services" / "fixtures" / "redteam" / "clean-login.html"


_ORIG_BACKENDS: Any = None


class BudgetReached(RuntimeError):
    """The cloud call cap was reached: the run stops before the next item."""


@dataclass
class CallLog:
    role: str
    route: str
    model: str | None
    status: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    ms: int
    cost_usd: float
    fell_back: bool
    cloud_provider_calls: int
    local_provider_calls: int
    error: str | None


class FixtureSandbox:
    """Fixture-backed ``SandboxClient``: serves the HTML of the case under test as sandbox features."""

    def __init__(self) -> None:
        self.html: dict[str, str] = {}
        self.default_html = ""
        self.calls: list[str] = []
        self.fail_reason: str | None = None  # set to simulate a failed render (SandboxError reason)

    @staticmethod
    def features(html: str, final_url: str) -> SandboxFeatures:
        feats = page_features(html)
        forms = [SandboxForm(fields=["password"] * feats.password_fields)] if feats.password_fields else []
        acc = feats.accessible_text()
        text = feats.visible_text + (("\n" + acc) if acc else "")
        return SandboxFeatures(
            redirect_chain=[final_url], final_url=final_url, title=feats.title, visible_text=text, forms=forms
        )

    async def render(self, url: str, verdict_id: str) -> SandboxFeatures:
        self.calls.append(url)
        if self.fail_reason:
            raise SandboxError(self.fail_reason)
        html = self.html.get(url) or self.default_html
        if not html:
            raise SandboxError("no_stub")
        return self.features(html, url)


async def _stub_resolver(host: str) -> list[str]:
    return [STUB_PUBLIC_IP]


class _OfflineHTTP:
    """Fails closed: no signal or investigator tool reaches the network during the run."""

    async def get(self, *a: Any, **k: Any) -> Any:
        raise RuntimeError("offline gap eval")

    post = head = get


@dataclass
class Rig:
    cascade: Cascade
    sandbox: FixtureSandbox
    router: Any
    route: str
    ai: bool
    calls: list[CallLog] = field(default_factory=list)
    tool_calls: list[tuple[str, str]] = field(default_factory=list)
    cloud_calls: int = 0
    cloud_cap: int = CLOUD_CALL_CAP
    t1_fitted: bool = False
    llm_log_errors: list[str] = field(default_factory=list)


def build_rig(route: str, *, ai: bool = True, budget: str = "extended", cloud_cap: int = CLOUD_CALL_CAP) -> Rig:
    from falcon_core.cascade.favicons import load_brand_favicons
    from falcon_core.llm.config import RouterConfig
    from falcon_core.llm.metrics import InMemoryMetrics
    from falcon_core.llm.router import LLMRouter
    from falcon_core.signals.brands.registry import default_registry
    from falcon_worker import ai as worker_ai

    if route == "local":
        os.environ["FL_SOVEREIGN_MODE"] = "1"  # cloud off even if a key exists
        os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
        os.environ.setdefault("FL_LOCAL_LLM_TIMEOUT_S", "150")
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("--route cloud needs ANTHROPIC_API_KEY in the process environment")
        os.environ.pop("FL_SOVEREIGN_MODE", None)
        os.environ.setdefault("FL_LLM_TIMEOUT_S", "40")
        os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
    os.environ["FL_AI_ENABLED"] = "true" if ai else "false"
    os.environ["FL_T1_MODEL_ENABLED"] = "true"
    metrics = InMemoryMetrics()
    holder: dict[str, Any] = {}

    def router_factory() -> LLMRouter:
        r = LLMRouter(RouterConfig.from_env(), metrics=metrics)
        holder["router"] = r
        return r

    global _ORIG_BACKENDS
    if _ORIG_BACKENDS is None:
        _ORIG_BACKENDS = worker_ai.tool_backends
    orig_backends = _ORIG_BACKENDS

    def recording_backends(*a: Any, **k: Any) -> Any:
        b = orig_backends(*a, **k)
        calls: list[tuple[str, str]] = holder.setdefault("tool_calls", [])

        def wrap(name: str, fn: Any) -> Any:
            if fn is None:
                return None

            async def run(value: str) -> Any:
                calls.append((name, str(value)))
                return await fn(value)

            return run

        from falcon_core.tools.registry import ToolBackends

        return ToolBackends(
            rdap_lookup=wrap("rdap_lookup", b.rdap_lookup),
            cert_lookup=wrap("cert_lookup", b.cert_lookup),
            check_reputation=wrap("check_reputation", b.check_reputation),
        )

    worker_ai.LLMRouter = router_factory  # type: ignore[assignment,misc]
    worker_ai.tool_backends = recording_backends  # type: ignore[assignment]
    sandbox = FixtureSandbox()
    registry = default_registry()
    kv = MemoryCache()
    mirror = loaded_mirror()
    http = _OfflineHTTP()
    agents = worker_ai.build_ai(http=http, cache=kv, mirror=mirror, registry=registry, sandbox=sandbox)
    extended = budget == "extended"
    if ai and extended:
        agents["extractor"].extractor.timeout_s = EVAL_EXTRACTOR_TIMEOUT_S
        agents["investigator"].time_budget_s = EVAL_INVESTIGATOR_TIMEOUT_S
    offline = {n: se for n, se in REGISTRY.items() if se[0].tier == "T1" and "url" in se[0].input_types}
    offline = {n: se for n, se in offline.items() if se[0].network == "none"}
    deps = CascadeDeps(
        registry=registry,
        sandbox=sandbox,
        favicons=load_brand_favicons(),
        guard_policy=GuardPolicy(allow_hosts=FIXTURE_HOSTS),
        resolver=_stub_resolver,
        t1_signals=offline,
        signal_http=http,
        signal_cache=kv,
        mirror=mirror,
        **(
            {
                "extractor_timeout_s": EVAL_EXTRACTOR_TIMEOUT_S + 5,
                "investigator_timeout_s": EVAL_INVESTIGATOR_TIMEOUT_S + 5,
                "llm_cooldown_s": 0.0,
            }
            if ai and extended
            else {}
        ),
        **agents,
    )
    tool_calls: list[tuple[str, str]] = holder.setdefault("tool_calls", [])
    rig = Rig(
        Cascade(deps),
        sandbox,
        holder.get("router"),
        route,
        ai,
        tool_calls=tool_calls,
        cloud_cap=cloud_cap,
        t1_fitted=deps.t1_model is not None,
    )
    if rig.router is not None:
        _instrument(rig)
    logging.getLogger("falcon_core.llm").setLevel(logging.WARNING)
    return rig


def make_router(route: str) -> tuple[Any, list[CallLog], dict[str, int]]:
    """A bare instrumented ``LLMRouter`` for direct agent evals (extractor): (router, call log, cloud counter)."""
    from falcon_core.llm.config import RouterConfig
    from falcon_core.llm.metrics import InMemoryMetrics
    from falcon_core.llm.router import LLMRouter

    if route == "local":
        os.environ["FL_SOVEREIGN_MODE"] = "1"
        os.environ.setdefault("FL_LOCAL_LLM_TIMEOUT_S", "150")
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("--route cloud needs ANTHROPIC_API_KEY in the process environment")
        os.environ.pop("FL_SOVEREIGN_MODE", None)
        os.environ.setdefault("FL_LLM_TIMEOUT_S", "40")
    os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
    router = LLMRouter(RouterConfig.from_env(), metrics=InMemoryMetrics())
    calls: list[CallLog] = []
    counter = {"cloud": 0}
    _wrap(router, calls, counter)
    return router, calls, counter


def _wrap(router: Any, calls: list[CallLog], counter: dict[str, int]) -> None:
    orig = router.complete_json

    async def wrapped(req: Any) -> Any:
        res = await orig(req)
        cloud = sum(1 for c in res.calls if c.route == "cloud")
        counter["cloud"] += cloud
        calls.append(
            CallLog(
                role=str(req.role),
                route=str(res.route),
                model=res.model,
                status=str(res.status),
                input_tokens=res.usage.input_tokens,
                output_tokens=res.usage.output_tokens,
                cache_read_tokens=res.usage.cache_read_tokens,
                cache_write_tokens=res.usage.cache_write_tokens,
                ms=sum(c.ms for c in res.calls),
                cost_usd=float(res.cost_usd),
                fell_back=bool(res.fell_back),
                cloud_provider_calls=cloud,
                local_provider_calls=sum(1 for c in res.calls if c.route == "local"),
                error=res.error,
            )
        )
        return res

    router.complete_json = wrapped


def _instrument(rig: Rig) -> None:
    router = rig.router
    orig = router.complete_json

    async def wrapped(req: Any) -> Any:
        res = await orig(req)
        cloud = sum(1 for c in res.calls if c.route == "cloud")
        rig.cloud_calls += cloud
        rig.calls.append(
            CallLog(
                role=str(req.role),
                route=str(res.route),
                model=res.model,
                status=str(res.status),
                input_tokens=res.usage.input_tokens,
                output_tokens=res.usage.output_tokens,
                cache_read_tokens=res.usage.cache_read_tokens,
                cache_write_tokens=res.usage.cache_write_tokens,
                ms=sum(c.ms for c in res.calls),
                cost_usd=float(res.cost_usd),
                fell_back=bool(res.fell_back),
                cloud_provider_calls=cloud,
                local_provider_calls=sum(1 for c in res.calls if c.route == "local"),
                error=res.error,
            )
        )
        return res

    router.complete_json = wrapped


@dataclass
class Run:
    item_id: str
    ok: bool
    doc: dict[str, Any] | None
    docs: list[dict[str, Any]]
    ms: int
    calls: list[CallLog]
    tool_calls: list[tuple[str, str]]
    error: str | None = None


async def run_item(rig: Rig, item: Item, *, link_page: str | None = None) -> Run:
    """Run one fixture item through the cascade; a crash is recorded, never raised (except the cloud cap)."""
    from falcon_core.cascade.ids import new_verdict_id
    from falcon_core.signals.url.canonical import canonicalize

    if rig.cloud_calls >= rig.cloud_cap:
        raise BudgetReached(f"cloud call cap {rig.cloud_cap} reached")
    sink = CallbackSink()
    c0, t0n = len(rig.calls), len(rig.tool_calls)
    t0 = time.monotonic()
    err: str | None = None
    doc: dict[str, Any] | None = None
    vid = new_verdict_id()
    try:
        if item.kind == "page":
            assert item.url is not None and item.html is not None  # noqa: S101
            host = item.url.split("/")[2]
            rig.cascade.d.guard_policy = GuardPolicy(allow_hosts=FIXTURE_HOSTS | {host})
            rig.sandbox.html = {}
            rig.sandbox.default_html = item.html
            rig.sandbox.fail_reason = None
            canon = canonicalize(item.url)
            if canon.ok:
                rig.sandbox.html[canon.url] = item.html
            doc = await asyncio.wait_for(rig.cascade.run_url(vid, item.url, sink, source="fixture"), CASE_TIMEOUT_S)
        else:
            assert item.text is not None  # noqa: S101
            rig.cascade.d.guard_policy = GuardPolicy(allow_hosts=FIXTURE_HOSTS)
            rig.sandbox.default_html = link_page or CLEAN_PAGE.read_text(encoding="utf-8")
            rig.sandbox.fail_reason = None
            doc = await asyncio.wait_for(
                rig.cascade.run_input(vid, "message", item.text.encode("utf-8"), sink, source="fixture"),
                CASE_TIMEOUT_S,
            )
    except Exception as exc:  # noqa: BLE001 - a crash is a finding, recorded not raised
        err = f"{type(exc).__name__}: {exc}"[:200]
    ms = int((time.monotonic() - t0) * 1000)
    return Run(item.item_id, err is None, doc, list(sink.docs), ms, rig.calls[c0:], list(rig.tool_calls[t0n:]), err)


def model_ids(rig: Rig) -> dict[str, Any]:
    cfg = rig.router.config if rig.router is not None else None
    return {
        "route": rig.route,
        "local": cfg.local_model if cfg is not None and rig.route == "local" else None,
        "cloud": dict(cfg.cloud_models) if cfg is not None and rig.route == "cloud" else None,
        "t1": "t1_hgb (fitted, sha256-verified artifact)" if rig.t1_fitted else "draft p_clf",
    }
