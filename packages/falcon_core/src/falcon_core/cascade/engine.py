"""The investigator cascade for URLs: T0 -> T1 -> T2 (-> T3 stub), exits per docs/SCORING.md §1.6.

- T0: canonicalise (``signals.url.canonical``), verdict cache, SSRF pre-check, verified-official
  registry, local feed mirror. Exits on a cache hit or a fresh feed hit (H2).
- T1: every registered T1 URL signal concurrently, each under its own timeout. Exits when
  ``t1_should_exit`` holds, or when H3/H2 already decide the verdict, or the URL may not be
  rendered (SSRF guard).
- T2: sandbox ``/render`` -> page/visual/brand evidence (H1 brand check), extractor hook (T-024).
  Exits when ``t2_should_exit`` holds; otherwise the T3 escalation is recorded (investigator not
  built yet, ``model_route='none'``).

A schema-valid verdict is emitted after every tier through ``VerdictSink.emit``; exactly one has
``final=true`` and it is emitted last. The arbiter alone sets verdict and score.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeGuard

from falcon_core.cascade.assemble import TraceStep, build_verdict, reissue
from falcon_core.cascade.evidence import dedupe, from_signal, make_evidence
from falcon_core.cascade.metrics import CascadeMetrics
from falcon_core.cascade.page import page_evidence
from falcon_core.cascade.ports import (
    Extractor,
    SandboxClient,
    SandboxError,
)
from falcon_core.scoring.arbiter import (
    ArbiterContext,
    ArbiterResult,
    has_brand_conflict,
    score,
    t1_should_exit,
    t2_should_exit,
)
from falcon_core.scoring.evidence import Evidence
from falcon_core.scoring.params import ScoringParams, load_params
from falcon_core.scoring.reasons import ReportingChannels
from falcon_core.security import (
    DEFAULT_POLICY,
    BlockReason,
    GuardPolicy,
    Resolver,
    SSRFBlocked,
    resolve_and_check,
    validate_url,
)
from falcon_core.signals import REGISTRY
from falcon_core.signals.base import SignalFn, SignalSpec
from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.signals.url.canonical import CanonicalURL, canonicalize
from falcon_core.signals.url.textutil import defang

log = logging.getLogger("falcon.cascade")

Tier = Literal["T0", "T1", "T2", "T3"]


class VerdictSink(Protocol):
    """Publishes one verdict doc. Errors must propagate (the worker retries the job).

    ``meta`` carries non-contract data for events: registrable_domain, fingerprints,
    ``reissued_from`` (cache hit / single-flight follower).
    """

    async def emit(self, doc: dict[str, Any], meta: Mapping[str, Any]) -> None: ...


class VerdictCache(Protocol):
    """T0 verdict cache (read side). ``get`` returns a previous *final, non-degraded* verdict doc.

    The write side belongs to the publisher: ``vc:`` is written only after the final was published
    (worker ``RedisSink``), never by the cascade.
    """

    async def get(self, key: str) -> dict[str, Any] | None: ...


class NullCache:
    async def get(self, key: str) -> dict[str, Any] | None:
        return None


class SinkError(Exception):
    """Publishing a verdict failed. Never turned into a re-scored verdict; the worker retries."""


def usable_cached(doc: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """A cached doc is reusable only if it is a final, non-degraded verdict."""
    return doc is not None and doc.get("final") is True and doc.get("degraded") is False


@dataclass
class SignalCtx:
    """``signals.base.SignalContext`` for one URL check."""

    url: str | None
    input_type: str = "url"
    text: str | None = None
    http: Any = None
    cache: Any = None
    mirror: Any = None
    clock: Any = time.time
    brands: Any = None


def default_signals(tier: str) -> dict[str, tuple[SignalSpec, SignalFn]]:
    return {
        name: (spec, fn) for name, (spec, fn) in REGISTRY.items() if spec.tier == tier and "url" in spec.input_types
    }


def default_t1_signals() -> dict[str, tuple[SignalSpec, SignalFn]]:
    return default_signals("T1")


def url_sha256(canonical: CanonicalURL) -> str:
    return hashlib.sha256(canonical.url.encode("utf-8")).hexdigest()


@dataclass
class CascadeDeps:
    registry: BrandRegistry
    sandbox: SandboxClient
    metrics: CascadeMetrics = field(default_factory=CascadeMetrics)
    cache: VerdictCache = field(default_factory=NullCache)
    extractor: Extractor | None = None  # T-024 hook
    t1_signals: Mapping[str, tuple[SignalSpec, SignalFn]] | None = None  # None -> REGISTRY
    guard_policy: GuardPolicy = DEFAULT_POLICY
    resolver: Resolver | None = None  # None -> system resolver
    favicons: Mapping[str, str] = field(default_factory=dict)  # favicon sha256 -> brand_id
    channels: ReportingChannels | None = None
    params: ScoringParams | None = None
    t0_signals: Mapping[str, tuple[SignalSpec, SignalFn]] | None = None  # None -> REGISTRY (rep.openphish)
    # Overall cap per tier on top of each signal's own timeout_ms (a hung signal never stalls a tier).
    tier_grace_s: float = 0.5
    sandbox_timeout_s: float = 7.0
    ssrf_timeout_s: float = 2.0
    # Shared signal context (SignalContext): guarded http client (``security.GuardedHTTPClient`` with
    # ``post_allow_hosts=FEED_POST_HOSTS``), signal KV cache (``signals.cache.RedisCache``) and the
    # OpenPhish mirror (``signals.reputation.mirror.FeedMirror``). None -> the signals' in-process defaults.
    signal_http: Any = None
    signal_cache: Any = None
    mirror: Any = None
    clock: Any = time.time


@dataclass
class _Run:
    verdict_id: str
    source: str
    t_start: float
    canonical: CanonicalURL | None = None
    fingerprint: str | None = None
    cache_key: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)
    blocked: str | None = None  # SSRF block reason: never render
    meta: dict[str, Any] = field(default_factory=dict)  # for platform events, never published
    final_emitted: bool = False  # structural guard: at most one final per verdict_id

    def ms(self) -> int:
        return int((time.perf_counter() - self.t_start) * 1000)


class Cascade:
    def __init__(self, deps: CascadeDeps) -> None:
        self.d = deps
        self.params = deps.params or load_params()
        self.verified: dict[str, frozenset[str]] = {
            b.brand_id: frozenset(b.verified_domains) for b in deps.registry.brands
        }

    # --- helpers ---------------------------------------------------------------------------

    def _score(self, run: _Run) -> ArbiterResult:
        ctx = ArbiterContext(
            input_type="url",
            registrable_domain=run.canonical.registrable if run.canonical else None,
            verified_domains=self.verified,
            extra_degraded_reasons=tuple(dict.fromkeys(run.degraded_reasons)),
            params=self.params,
        )
        return score(dedupe(run.evidence), None, ctx)

    async def _emit(
        self, sink: VerdictSink, run: _Run, result: ArbiterResult, tier: Tier, final: bool
    ) -> dict[str, Any]:
        doc = build_verdict(
            result,
            verdict_id=run.verdict_id,
            input_type="url",
            tier=tier,
            final=final,
            latency_ms=run.ms(),
            registry=self.d.registry,
            canonical_url_defanged=defang(run.canonical.url) if run.canonical else None,
            input_fingerprint=run.fingerprint,
            trace=run.trace,
            source=run.source,
            channels=self.d.channels,
        )
        await self._publish(sink, run, doc)
        if final:
            self.d.metrics.record_final("url", doc["verdict"], tier, "none", run.source)
            if doc["degraded"]:
                self.d.metrics.degraded.inc()
        return doc

    async def _publish(self, sink: VerdictSink, run: _Run, doc: dict[str, Any]) -> None:
        if run.final_emitted:
            raise RuntimeError("a final verdict was already emitted for this run")
        if doc["final"]:
            run.final_emitted = True  # set first: a failed final must not be re-scored into another
        try:
            await sink.emit(doc, run.meta)
        except Exception as exc:
            raise SinkError(f"{type(exc).__name__}") from exc

    def _observe(self, stage: str, t0: float) -> int:
        dt = time.perf_counter() - t0
        self.d.metrics.stage_latency.labels(stage).observe(dt)
        return int(dt * 1000)

    # --- entry point -----------------------------------------------------------------------

    async def run_url(
        self,
        verdict_id: str,
        url: str,
        sink: VerdictSink,
        *,
        source: str = "live",
        cache_key: str | None = None,
    ) -> dict[str, Any]:
        """Run the cascade and return the final verdict doc (also emitted to ``sink``)."""
        run = _Run(verdict_id=verdict_id, source=source, t_start=time.perf_counter())
        tier: Tier = "T0"
        try:
            done = await self._t0(run, url, sink, cache_key)
            if done is not None:
                return done
            tier = "T1"
            done = await self._t1(run, sink)
            if done is not None:
                return done
            tier = "T2"
            return await self._t2(run, sink)
        except SinkError:
            raise  # transport failure: the worker leaves the job pending and retries
        except Exception as exc:  # noqa: BLE001 - a cascade bug still ends with one final verdict
            if run.final_emitted:
                raise
            log.exception("cascade failed", extra={"verdict_id": verdict_id})
            run.degraded_reasons.append(f"internal_error:{type(exc).__name__}")
            run.trace.append(TraceStep(tier, "Check stopped by an internal error", ms=run.ms()))
            return await self._emit(sink, run, self._score(run), tier, final=True)

    # --- T0 --------------------------------------------------------------------------------

    async def _t0(self, run: _Run, url: str, sink: VerdictSink, cache_key: str | None) -> dict[str, Any] | None:
        t0 = time.perf_counter()
        c = canonicalize(url)
        if not c.ok or c.scheme not in ("http", "https") or not c.host:
            run.degraded_reasons.append("invalid_url")
            run.trace.append(TraceStep("T0", "URL could not be parsed", ms=self._observe("T0", t0)))
            return await self._emit(sink, run, self._score(run), "T0", final=True)
        run.canonical = c
        run.meta["registrable_domain"] = c.registrable or c.host
        run.fingerprint = url_sha256(c)
        run.cache_key = cache_key or run.fingerprint

        cached = None
        try:
            cached = await self.d.cache.get(run.cache_key)
        except Exception:  # noqa: BLE001 - cache is best effort
            log.warning("verdict cache get failed", extra={"verdict_id": run.verdict_id})
        if usable_cached(cached):
            self.d.metrics.cache_hits.labels("verdict").inc()
            return await self._emit_cached(run, cached, sink)

        # SSRF pre-check: an internal or unresolvable target is never rendered.
        try:
            target = validate_url(c.url, self.d.guard_policy)
            await asyncio.wait_for(
                resolve_and_check(target, self.d.resolver, self.d.guard_policy),
                self.d.ssrf_timeout_s,
            )
        except SSRFBlocked as exc:
            if exc.reason is BlockReason.DNS_FAILURE and c.host_ascii in self.d.guard_policy.allow_hosts:
                # An explicitly allow-listed fixture host lives on the sandbox network, which the worker
                # cannot resolve. The sandbox resolves and guards it itself (through the egress proxy).
                pass
            else:
                self.d.metrics.on_ssrf_block(exc.reason)
                run.blocked = exc.reason.value
                run.degraded_reasons.append(f"not_rendered:{exc.reason.value}")
        except TimeoutError:
            self.d.metrics.on_ssrf_block("dns_failure")
            run.blocked = "dns_timeout"
            run.degraded_reasons.append("not_rendered:dns_timeout")

        added: list[Evidence] = []
        brand = self.d.registry.official_brand(c.registrable) if c.registrable else None
        if brand is not None:
            added.append(
                make_evidence(
                    "registry.verified_official",
                    "brand",
                    {"brand_id": brand.brand_id, "registrable_domain": defang(c.registrable)},
                    tier="T0",
                    source="registry",
                    en=f"Registered official site of {brand.name_en[:80]}",
                    ar=f"موقع رسمي مسجّل لـ {brand.name_ar[:80]}",
                )
            )
        t0_signals = self.d.t0_signals if self.d.t0_signals is not None else default_signals("T0")
        added.extend(await self._run_signals(t0_signals, self._ctx(run)))
        run.evidence.extend(added)
        result = self._score(run)
        ms = self._observe("T0", t0)
        h2 = any(r.rule_id == "H2" for r in result.fired_rules)
        run.trace.append(
            TraceStep(
                "T0",
                "Canonical URL, official registry and feed mirror checked" + ("; fresh feed hit" if h2 else ""),
                tuple(e.id for e in added),
                ms,
            )
        )
        if h2:
            return await self._emit(sink, run, result, "T0", final=True)
        await self._emit(sink, run, result, "T0", final=False)
        return None

    async def _emit_cached(self, run: _Run, cached: dict[str, Any], sink: VerdictSink) -> dict[str, Any]:
        doc = reissue(
            cached,
            verdict_id=run.verdict_id,
            source=run.source,
            latency_ms=run.ms(),
            note=f"Verdict cache hit (from {str(cached.get('verdict_id'))[:32]})",
            input_fingerprint=run.fingerprint,
        )
        run.meta["reissued_from"] = str(cached.get("verdict_id"))
        await self._publish(sink, run, doc)
        self.d.metrics.record_final("url", doc["verdict"], doc["tier_reached"], doc["model_route"], run.source)
        return doc

    # --- T1 --------------------------------------------------------------------------------

    def _ctx(self, run: _Run) -> SignalCtx:
        if run.canonical is None:
            raise RuntimeError("T0 did not canonicalise")
        return SignalCtx(
            url=run.canonical.raw,
            brands=self.d.registry,
            http=self.d.signal_http,
            cache=self.d.signal_cache,
            mirror=self.d.mirror,
            clock=self.d.clock,
        )

    async def _run_signals(self, signals: Mapping[str, tuple[SignalSpec, SignalFn]], ctx: SignalCtx) -> list[Evidence]:
        """All signals concurrently, each under its own timeout; results kept per signal."""
        if not signals:
            return []
        specs = list(signals.values())
        tasks = [asyncio.create_task(self._run_signal(spec, fn, ctx)) for spec, fn in specs]
        cap = max(spec.timeout_ms for spec, _ in specs) / 1000 + self.d.tier_grace_s
        done, pending = await asyncio.wait(tasks, timeout=cap)
        out: list[Evidence] = []
        for (spec, _), task in zip(specs, tasks, strict=True):
            if task in done:
                out.extend(task.result())
            else:  # belt and braces: the per-signal timeout should have fired first
                task.cancel()
                self.d.metrics.tool_errors.labels(spec.name, "timeout").inc()
                out.append(
                    make_evidence(
                        spec.name, spec.family, None, tier=spec.tier, source="computed",
                        confidence=0.0, error="timeout",
                    )
                )  # fmt: skip
        return out

    async def _run_signal(self, spec: SignalSpec, fn: SignalFn, ctx: SignalCtx) -> list[Evidence]:
        try:
            out = await asyncio.wait_for(fn(ctx), spec.timeout_ms / 1000)
            evs = [from_signal(e) for e in out]
            for e in evs:
                if e.error is not None:
                    self.d.metrics.tool_errors.labels(spec.name, "error").inc()
            return evs
        except Exception as exc:  # noqa: BLE001 - timeouts and crashes become error evidence
            reason = "timeout" if isinstance(exc, TimeoutError) else "error"
            self.d.metrics.tool_errors.labels(spec.name, reason).inc()
            detail = "timeout" if reason == "timeout" else f"{type(exc).__name__}"
            return [
                make_evidence(
                    spec.name, spec.family, None, tier=spec.tier, source="computed",
                    confidence=0.0, error=detail,
                )
            ]  # fmt: skip

    async def _t1(self, run: _Run, sink: VerdictSink) -> dict[str, Any] | None:
        if run.canonical is None:
            raise RuntimeError("T0 did not canonicalise")
        t0 = time.perf_counter()
        signals = self.d.t1_signals if self.d.t1_signals is not None else default_t1_signals()
        added = await self._run_signals(signals, self._ctx(run))
        run.evidence.extend(added)
        result = self._score(run)
        ms = self._observe("T1", t0)
        fired = {r.rule_id for r in result.fired_rules}
        conflict = has_brand_conflict(run.evidence)
        exit_now = (
            t1_should_exit(result.p_clf, conflict, self.params) or bool(fired & {"H2", "H3"}) or run.blocked is not None
        )
        why = (
            "not rendered (blocked target)"
            if run.blocked
            else "decided by hard rule"
            if fired & {"H2", "H3"}
            else "confident"
            if exit_now
            else "uncertain or brand conflict, escalating to T2"
        )
        errors = sum(1 for e in added if e.error is not None)
        run.trace.append(
            TraceStep(
                "T1",
                f"{len(signals)} URL signals ran ({errors} failed); {why}",
                tuple(e.id for e in added if e.error is None and e.observed is not None),
                ms,
            )
        )
        if exit_now:
            return await self._emit(sink, run, result, "T1", final=True)
        self.d.metrics.escalations.labels("T1", "T2").inc()
        await self._emit(sink, run, result, "T1", final=False)
        return None

    # --- T2 --------------------------------------------------------------------------------

    async def _t2(self, run: _Run, sink: VerdictSink) -> dict[str, Any]:
        if run.canonical is None:
            raise RuntimeError("T0 did not canonicalise")
        t0 = time.perf_counter()
        added: list[Evidence] = []
        summary = "Page rendered in the sandbox"
        try:
            features = await asyncio.wait_for(
                self.d.sandbox.render(run.canonical.url, run.verdict_id),
                self.d.sandbox_timeout_s,
            )
            if features.error and not features.final_url:
                raise SandboxError("render_failed")
        except (TimeoutError, SandboxError) as exc:
            reason = "timeout" if isinstance(exc, TimeoutError) else exc.reason
            if reason == "timeout":
                self.d.metrics.sandbox_timeouts.inc()
            self.d.metrics.tool_errors.labels("sandbox", reason[:40]).inc()
            # The input was escalated because T1 was unsure: without the page we must not
            # fall back to no_warning_signs (DECISIONS: sandbox failure degrades).
            run.degraded_reasons.append(f"sandbox_unavailable:{reason}"[:80])
            summary = "Sandbox could not render the page"
        else:
            added.extend(page_evidence(features, run.canonical.registrable, self.d.registry, self.d.favicons))
            final_reg = canonicalize(features.final_url).registrable if features.final_url else ""
            run.meta["fingerprints"] = {
                "dom_simhash": features.dom_simhash,
                "favicon_hash": features.favicon_sha256,
            }
            if final_reg:
                run.meta["final_registrable_domain"] = final_reg
            if self.d.extractor is not None:  # T-024: quarantined extractor hook
                try:
                    extra = await asyncio.wait_for(self.d.extractor.extract(features, run.verdict_id), 4.0)
                    added.extend(extra)
                except Exception as exc:  # noqa: BLE001 - extractor is optional
                    self.d.metrics.tool_errors.labels("extractor", type(exc).__name__[:40]).inc()
        run.evidence.extend(added)
        result = self._score(run)
        ms = self._observe("T2", t0)
        hard = ",".join(r.rule_id for r in result.fired_rules)
        if hard:
            summary += f"; hard rule {hard}"
        if not t2_should_exit(result, self.params) and not run.degraded_reasons:
            # T3 investigator is not built yet (T-0xx): record the escalation only.
            self.d.metrics.escalations.labels("T2", "T3").inc()
            summary += "; uncertain band, T3 escalation recorded (investigator not enabled)"
        run.trace.append(TraceStep("T2", summary, tuple(e.id for e in added), ms))
        return await self._emit(sink, run, result, "T2", final=True)


AsyncDocFn = Callable[[dict[str, Any], Mapping[str, Any]], Awaitable[None]]


class CallbackSink:
    """Adapter: wrap an ``async fn(doc, meta)`` as a ``VerdictSink``; records emitted docs."""

    def __init__(self, fn: AsyncDocFn | None = None) -> None:
        self.fn = fn
        self.docs: list[dict[str, Any]] = []
        self.meta: list[dict[str, Any]] = []

    async def emit(self, doc: dict[str, Any], meta: Mapping[str, Any]) -> None:
        self.docs.append(doc)
        self.meta.append(dict(meta))
        if self.fn is not None:
            await self.fn(doc, meta)
