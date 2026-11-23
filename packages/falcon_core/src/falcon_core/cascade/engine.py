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
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeGuard

from falcon_core.cascade.ai import InjectionDetect, injection_evidence, risk_only, to_contract_model, to_scoring
from falcon_core.cascade.assemble import TraceStep, build_verdict, display_url, reissue
from falcon_core.cascade.evidence import dedupe, from_signal, make_evidence
from falcon_core.cascade.metrics import CascadeMetrics
from falcon_core.cascade.page import page_evidence
from falcon_core.cascade.ports import (
    Extractor,
    SandboxClient,
    SandboxError,
)
from falcon_core.scoring.arbiter import (
    OLD_DOMAIN_DAYS,
    YOUNG_DOMAIN_DAYS,
    ArbiterContext,
    ArbiterResult,
    has_brand_conflict,
    t1_risk_evidence,
    t1_should_exit,
    t2_should_exit,
)
from falcon_core.scoring.evidence import Evidence, observed_number
from falcon_core.scoring.model_cap import score_with_model
from falcon_core.scoring.params import ScoringParams, load_params
from falcon_core.scoring.reasons import CLASSIFIER_SIGNAL, ReportingChannels
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

# Sandbox failures meaning "could not open the page" (bot blocking, slow site), not a platform fault.
# Fail closed: ONLY codes that the browser-to-TARGET leg alone can produce are soft (the page refused or
# did not answer us). Everything else degrades: the sandbox service's own errors (http_5xx, unreachable,
# bad_json), egress/SSRF policy blocks (``blocked_by_policy[:reason]``, the egress proxy's
# ``X-Falcon-Block-Reason``), redirect/size limits and any code not listed here.
SOFT_RENDER_FAILURES: frozenset[str] = frozenset(
    ["timeout", "dns_failure", "tls_error", "http_403_empty", "empty_response"]
)


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
    # AI wiring (all optional; None = deterministic-only cascade, which is also the fallback on any failure).
    t1_model: Any = None  # scoring.t1_model.T1Model (p_clf); None -> draft p_clf
    investigator: Any = None  # agent.Investigator (T3, uncertain band only)
    injection: InjectionDetect | None = None
    extractor_timeout_s: float = 7.0
    investigator_timeout_s: float = 16.0
    llm_cooldown_s: float = 60.0
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
    unreachable: str | None = None  # blocked only because DNS did not answer (not an egress/SSRF policy block)
    meta: dict[str, Any] = field(default_factory=dict)  # for platform events, never published
    final_emitted: bool = False  # structural guard: at most one final per verdict_id
    p_clf: float | None = None  # fitted T1 model probability (None -> draft)
    routes: set[str] = field(default_factory=set)  # LLM routes used ("cloud" / "local")
    page_tier: bool = False  # a page (T2+) or text input was judged: the responder may phrase reasons
    redirect_chain: tuple[str, ...] = ()

    input_type: Literal["url", "message", "email", "image"] = "url"

    def ms(self) -> int:
        return int((time.perf_counter() - self.t_start) * 1000)

    def route(self) -> Literal["cloud", "local", "none"]:
        return "cloud" if "cloud" in self.routes else "local" if "local" in self.routes else "none"


class Cascade:
    def __init__(self, deps: CascadeDeps) -> None:
        self.d = deps
        self.params = deps.params or load_params()
        # Signals whose errors are informational only (SignalSpec.criticality == "enrichment").
        specs = [
            *(deps.t1_signals if deps.t1_signals is not None else default_t1_signals()).values(),
            *(deps.t0_signals if deps.t0_signals is not None else default_signals("T0")).values(),
        ]
        self._enrichment: frozenset[str] = frozenset(sp.name for sp, _ in specs if sp.criticality == "enrichment")
        self._llm_open_until = 0.0
        self.verified: dict[str, frozenset[str]] = {
            b.brand_id: frozenset(b.verified_domains) for b in deps.registry.brands
        }

    # --- LLM circuit breaker ----------------------------------------------------------------

    def llm_allowed(self) -> bool:
        """False for ``llm_cooldown_s`` after an LLM call timed out: with no reachable provider every
        check would otherwise wait the full timeout. Deterministic results are unaffected."""
        return time.monotonic() >= self._llm_open_until

    def llm_trip(self) -> None:
        self._llm_open_until = time.monotonic() + self.d.llm_cooldown_s

    # --- helpers ---------------------------------------------------------------------------

    def _score(self, run: _Run) -> ArbiterResult:
        ctx = ArbiterContext(
            input_type=run.input_type,
            registrable_domain=run.canonical.registrable if run.canonical else None,
            verified_domains=self.verified,
            extra_degraded_reasons=tuple(dict.fromkeys(run.degraded_reasons)),
            enrichment_signals=self._enrichment,
            params=self.params,
        )
        return score_with_model(dedupe(run.evidence), run.p_clf, ctx)

    async def _emit(
        self, sink: VerdictSink, run: _Run, result: ArbiterResult, tier: Tier, final: bool
    ) -> dict[str, Any]:
        doc = build_verdict(
            result,
            verdict_id=run.verdict_id,
            input_type=run.input_type,
            tier=tier,
            final=final,
            latency_ms=run.ms(),
            registry=self.d.registry,
            canonical_url_defanged=defang(display_url(run.canonical)) if run.canonical else None,
            input_fingerprint=run.fingerprint,
            trace=run.trace,
            source=run.source,
            channels=self.d.channels,
            model_route=run.route(),
        )
        await self._publish(sink, run, doc)
        if final:
            self.d.metrics.record_final(run.input_type, doc["verdict"], tier, run.route(), run.source)
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

    async def run_input(
        self,
        verdict_id: str,
        input_type: Literal["message", "email", "image"],
        data: bytes,
        sink: VerdictSink,
        *,
        source: str = "live",
        input_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Message / email / image check (``cascade.inputs``): child URLs go through ``run_url`` (H5)."""
        from falcon_core.cascade.inputs import run_input

        return await run_input(
            self, verdict_id, input_type, data, sink, source=source, input_fingerprint=input_fingerprint
        )

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
                if exc.reason is BlockReason.DNS_FAILURE:
                    run.unreachable = exc.reason.value  # host does not resolve: judged on the address checks
                else:
                    run.degraded_reasons.append(f"not_rendered:{exc.reason.value}")
        except TimeoutError:
            if c.host_ascii not in self.d.guard_policy.allow_hosts:  # see the DNS_FAILURE case above
                self.d.metrics.on_ssrf_block("dns_failure")
                run.blocked = "dns_timeout"
                run.unreachable = "dns_timeout"

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

    async def _fit_p_clf(self, run: _Run) -> None:
        """Fitted T1 classifier probability; any failure falls back to the draft p_clf (flagged)."""
        model = self.d.t1_model
        if model is None or run.canonical is None:
            return
        try:
            run.p_clf = float(await asyncio.to_thread(model.p_clf, run.canonical.url))
            if run.p_clf >= self.params.tau_low:  # informational: lets reasons cite the classifier
                run.evidence.append(
                    make_evidence(CLASSIFIER_SIGNAL, "url", {"p_clf": round(run.p_clf, 2)}, tier="T1", source="model")
                )
        except Exception as exc:  # noqa: BLE001 - missing/tampered artifact or bad features
            self.d.metrics.tool_errors.labels("t1_model", type(exc).__name__[:40]).inc()
            run.degraded_reasons.append("t1_model_unavailable")

    async def _t1(self, run: _Run, sink: VerdictSink) -> dict[str, Any] | None:
        if run.canonical is None:
            raise RuntimeError("T0 did not canonicalise")
        t0 = time.perf_counter()
        signals = self.d.t1_signals if self.d.t1_signals is not None else default_t1_signals()
        added = await self._run_signals(signals, self._ctx(run))
        run.evidence.extend(added)
        await self._fit_p_clf(run)
        if run.unreachable is not None:
            # Same rule as a sandbox render failure (SCORING §4): degrade only if the address checks show risk.
            if not self._may_clear_unrendered(run):
                run.degraded_reasons.append(f"not_rendered:{run.unreachable}")
            else:
                run.evidence.append(self._not_rendered_evidence(run.unreachable, "T1"))
        result = self._score(run)
        ms = self._observe("T1", t0)
        fired = {r.rule_id for r in result.fired_rules}
        conflict = has_brand_conflict(run.evidence)
        exit_now = (
            t1_should_exit(result.p_clf, conflict, self.params, t1_risk_evidence(result, self.params))
            or bool(fired & {"H2", "H3"})
            or run.blocked is not None
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

    @staticmethod
    def _not_rendered_evidence(reason: str, tier: Tier) -> Evidence:
        return make_evidence(
            "sandbox.not_rendered", "page", {"reason": reason[:40]}, tier=tier, source="computed",
            en="We could not open the page itself; the address checks found no warning signs.",
            ar="تعذّر علينا فتح الصفحة نفسها؛ فحوصات العنوان لم تُظهر أي علامات تحذير.",
        )  # fmt: skip

    def _t1_risky(self, run: _Run) -> bool:
        """T1 in or above the uncertain band, a hard rule fired, or url./brand./rep./domain. risk evidence."""
        r = self._score(run)
        if r.calibrated_probability >= self.params.tau_low or r.fired_rules:
            return True
        risk_families = ("url", "brand", "rep", "domain")
        if any(e.weight > 0 and e.signal.split(".", 1)[0] in risk_families for e in r.weighted_evidence):
            return True
        return any((age := self._domain_age(e)) is not None and age < YOUNG_DOMAIN_DAYS for e in run.evidence)

    @staticmethod
    def _domain_age(e: Evidence) -> float | None:
        if e.signal not in ("domain.age_days", "domain.age") or e.error is not None:
            return None
        return observed_number(e, "age_days")

    def _has_trust(self, run: _Run) -> bool:
        """Page-independent trust that did not error: an established domain or a verified official one."""
        for e in run.evidence:
            if e.signal == "registry.verified_official" and e.error is None:
                return True
            age = self._domain_age(e)
            if age is not None and age > OLD_DOMAIN_DAYS:
                return True
        return False

    def _may_clear_unrendered(self, run: _Run) -> bool:
        return not self._t1_risky(run) and self._has_trust(run)

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
                err = features.error.lower()
                raise SandboxError(err if re.fullmatch(r"[a-z0-9_:]{1,40}", err) else "render_failed")
        except (TimeoutError, SandboxError) as exc:
            reason = "timeout" if isinstance(exc, TimeoutError) else exc.reason
            if reason == "timeout":
                self.d.metrics.sandbox_timeouts.inc()
            self.d.metrics.tool_errors.labels("sandbox", reason[:40]).inc()
            summary = "Sandbox could not render the page"
            # SCORING §4: a page that cannot be opened (bot blocking, timeout, DNS) may end in
            # no_warning_signs only when T1 shows no risk AND page-independent trust evidence exists
            # (established domain or verified official). Egress/SSRF blocks, unknown codes and the
            # sandbox's own errors always degrade.
            if reason in SOFT_RENDER_FAILURES and self._may_clear_unrendered(run):
                added.append(self._not_rendered_evidence(reason, "T2"))
                summary += "; address checks clean and domain established, not degraded"
            else:
                run.degraded_reasons.append(f"sandbox_unavailable:{reason}"[:80])
        else:
            added.extend(page_evidence(features, run.canonical.registrable, self.d.registry, self.d.favicons))
            final_reg = canonicalize(features.final_url).registrable if features.final_url else ""
            run.meta["fingerprints"] = {
                "dom_simhash": features.dom_simhash,
                "favicon_hash": features.favicon_sha256,
            }
            if final_reg:
                run.meta["final_registrable_domain"] = final_reg
            run.redirect_chain = tuple(features.redirect_chain)
            # The deterministic injection detector runs first and on its own: an extractor timeout or
            # failure below can never discard its findings.
            added.extend(injection_evidence(self.d.injection, features.visible_text, features.title))
            if self.d.extractor is not None and self.llm_allowed():  # quarantined LLM extractor
                try:
                    extra = await asyncio.wait_for(
                        self.d.extractor.extract(features, run.verdict_id), self.d.extractor_timeout_s
                    )
                    # Agent output only ever adds risk-side evidence next to the deterministic evidence.
                    added.extend(risk_only(e) for e in extra)
                    route = getattr(extra, "route", "none")
                    if route != "none":
                        run.routes.add(route)
                except Exception as exc:  # noqa: BLE001 - extractor is optional
                    self.d.metrics.tool_errors.labels("extractor", type(exc).__name__[:40]).inc()
                    if isinstance(exc, TimeoutError):
                        self.llm_trip()
        run.evidence.extend(added)
        run.page_tier = True
        result = self._score(run)
        ms = self._observe("T2", t0)
        hard = ",".join(r.rule_id for r in result.fired_rules)
        if hard:
            summary += f"; hard rule {hard}"
        uncertain = not t2_should_exit(result, self.params) and not run.degraded_reasons
        if uncertain:
            self.d.metrics.escalations.labels("T2", "T3").inc()
            summary += (
                "; uncertain band, escalating to the investigator"
                if self.d.investigator is not None
                else "; uncertain band, T3 escalation recorded (investigator not enabled)"
            )
        run.trace.append(TraceStep("T2", summary, tuple(e.id for e in added), ms))
        if not (uncertain and self.d.investigator is not None and self.llm_allowed()):
            return await self._emit(sink, run, result, "T2", final=True)
        await self._emit(sink, run, result, "T2", final=False)
        return await self._t3(run, sink, result)

    # --- T3 --------------------------------------------------------------------------------

    async def _t3(self, run: _Run, sink: VerdictSink, prior: ArbiterResult) -> dict[str, Any]:
        """Investigator (ADR-001): sees evidence only, may add T3 evidence; the arbiter re-scores."""
        from falcon_core.agent.investigator import InvestigationCase
        from falcon_core.tools.provenance import ProvenanceContext

        if run.canonical is None:
            raise RuntimeError("T0 did not canonicalise")
        t0 = time.perf_counter()
        new: list[Evidence] = []
        summary = "Investigator did not run"
        steps: list[TraceStep] = []
        try:
            case = InvestigationCase(
                evidence=[to_contract_model(e) for e in prior.weighted_evidence],
                provenance=ProvenanceContext(
                    canonical_url=run.canonical.url,
                    redirect_chain=run.redirect_chain,
                    registrable_domains=frozenset({run.canonical.registrable} if run.canonical.registrable else ()),
                ),
                input_type="url",
                verdict_id=run.verdict_id,
                first_step=len(run.trace),
            )
            res = await asyncio.wait_for(self.d.investigator.run(case), self.d.investigator_timeout_s)
            new = [risk_only(to_scoring(e)) for e in res.new_evidence]
            if res.route != "none":
                run.routes.add(res.route)
            steps = [
                TraceStep(
                    s.name, s.summary, tuple(s.evidence_added or ()), s.ms, kind="llm" if s.kind == "llm" else "tool"
                )
                for s in res.trace
            ]
            summary = f"Investigator stopped ({res.stop_reason}) after {res.tool_calls} tool calls"
        except Exception as exc:  # noqa: BLE001 - T3 is best effort: keep the T2 result
            self.d.metrics.tool_errors.labels("investigator", type(exc).__name__[:40]).inc()
            if isinstance(exc, TimeoutError):
                self.llm_trip()
            summary = "Investigator unavailable; T2 result kept"
        run.evidence.extend(new)
        run.trace.extend(steps)
        run.trace.append(TraceStep("T3", summary, tuple(e.id for e in new), self._observe("T3", t0)))
        return await self._emit(sink, run, self._score(run), "T3", final=True)


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
