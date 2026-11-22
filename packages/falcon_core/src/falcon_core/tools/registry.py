"""Investigator tool registry (contracts/tools.schema.json ``investigator_tools``).

Each tool has typed arguments (pydantic, extra keys forbidden), a time budget, and provenance-
checked URL/domain arguments. Implementations are injected (``ToolBackends``) so the registry can be
wired to the real signals and sandbox later; a tool without a backend is unavailable.

An ``Action`` from the LLM goes through: known tool -> available -> args schema -> provenance ->
registry ids (brand) -> call with budget. Tool output is normalised (``restamp``): new ids, tier T3,
arbiter-owned fields cleared. A provenance violation is rejected, adds an
``injection.tool_provenance`` evidence item and counts ``fl_tool_errors_total{reason=provenance}``
plus ``fl_injection_detected_total``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from falcon_core.contracts.evidence import Evidence
from falcon_core.llm import metrics as m
from falcon_core.tools.provenance import ProvenanceContext
from falcon_core.tools.util import IdFactory, defang, new_evidence_id, restamp

EvidenceList = Sequence[Evidence]


class Action(BaseModel):
    """contracts/tools.schema.json#/$defs/Action. Extra keys (e.g. "score") are rejected."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    why_evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    stop: bool = False


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DomainArgs(_Args):
    domain: str = Field(min_length=1, max_length=253)


class RenderArgs(_Args):
    url: str = Field(min_length=1, max_length=4096)
    profile: Literal["mobile_ar", "desktop_en"] = "mobile_ar"


class UrlArgs(_Args):
    url: str = Field(min_length=1, max_length=4096)


class CompareBrandArgs(_Args):
    brand_id: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    domain: str = Field(min_length=1, max_length=253)


class FingerprintArgs(_Args):
    fingerprint: str = Field(pattern=r"^[A-Za-z0-9_:\-]{4,128}$")


@dataclass(frozen=True, slots=True)
class ToolBackends:
    """Injected implementations. Each returns evidence only (never raw HTML or text)."""

    rdap_lookup: Callable[[str], Awaitable[EvidenceList]] | None = None
    cert_lookup: Callable[[str], Awaitable[EvidenceList]] | None = None
    render_page: Callable[[str, str], Awaitable[EvidenceList]] | None = None
    compare_brand: Callable[[str, str], Awaitable[EvidenceList]] | None = None
    search_similar_scripts: Callable[[str], Awaitable[EvidenceList]] | None = None
    check_reputation: Callable[[str], Awaitable[EvidenceList]] | None = None
    expand_redirects: Callable[[str], Awaitable[EvidenceList]] | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    args_model: type[_Args]
    budget_ms: int
    url_args: tuple[str, ...] = ()
    domain_args: tuple[str, ...] = ()
    args_doc: Mapping[str, str] = field(default_factory=dict)
    returns: str = ""


SPECS: dict[str, ToolSpec] = {
    s.name: s
    for s in (
        ToolSpec(
            "rdap_lookup",
            DomainArgs,
            2500,
            domain_args=("domain",),
            args_doc={"domain": "allowed domain"},
            returns="domain.age, domain.registrar",
        ),
        ToolSpec(
            "cert_lookup",
            DomainArgs,
            2500,
            domain_args=("domain",),
            args_doc={"domain": "allowed domain"},
            returns="domain.cert_age, domain.cert_issuer, domain.ct_siblings",
        ),
        ToolSpec(
            "render_page",
            RenderArgs,
            6000,
            url_args=("url",),
            args_doc={"url": "allowed url", "profile": "mobile_ar|desktop_en"},
            returns="page.*, visual.*",
        ),
        ToolSpec(
            "compare_brand",
            CompareBrandArgs,
            800,
            domain_args=("domain",),
            args_doc={"brand_id": "allowed brand id", "domain": "allowed domain"},
            returns="brand.domain_owned, brand.visual_similarity",
        ),
        ToolSpec(
            "search_similar_scripts",
            FingerprintArgs,
            800,
            args_doc={"fingerprint": "allowed fingerprint"},
            returns="message.nearest_scripts",
        ),
        ToolSpec(
            "check_reputation",
            UrlArgs,
            1500,
            url_args=("url",),
            args_doc={"url": "allowed url"},
            returns="rep.*",
        ),
        ToolSpec(
            "expand_redirects",
            UrlArgs,
            3000,
            url_args=("url",),
            args_doc={"url": "allowed url"},
            returns="url.redirect_chain",
        ),
    )
}

RejectReason = Literal[
    "unknown_tool", "unavailable", "bad_args", "provenance", "unknown_brand", "budget", "duplicate"
]
OutcomeStatus = Literal["ok", "rejected", "error", "timeout"]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    tool: str
    status: OutcomeStatus
    evidence: tuple[Evidence, ...] = ()
    reason: str | None = None
    ms: int = 0
    context: ProvenanceContext | None = None  # updated provenance (expand_redirects adds hops)


def _hops_from(evidence: EvidenceList) -> list[str]:
    hops: list[str] = []
    for ev in evidence:
        if ev.signal != "url.redirect_chain" or ev.error:
            continue
        obs = ev.observed
        seq = obs.get("chain") or obs.get("hops") if isinstance(obs, dict) else obs
        if isinstance(seq, list):
            for h in seq:
                if isinstance(h, str):
                    hops.append(h)
                elif isinstance(h, dict) and isinstance(h.get("url"), str):
                    hops.append(h["url"])
    return hops


class ToolRegistry:
    def __init__(
        self,
        backends: ToolBackends,
        *,
        brand_ids: frozenset[str] = frozenset(),
        metrics: m.MetricsSink | None = None,
        id_factory: IdFactory = new_evidence_id,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.backends = backends
        self.brand_ids = brand_ids
        self.metrics: m.MetricsSink = metrics or m.NullMetrics()
        self._ids = id_factory
        self._clock = clock

    def available(self) -> list[ToolSpec]:
        return [s for s in SPECS.values() if getattr(self.backends, s.name) is not None]

    def catalogue(self) -> list[dict[str, Any]]:
        """Tool list for the investigator prompt (trusted text built by us)."""
        return [
            {"tool": s.name, "args": dict(s.args_doc), "returns": s.returns}
            for s in self.available()
        ]

    def _violation(self, tool: str, arg: str, value: object) -> Evidence:
        self.metrics.inc(m.TOOL_ERRORS, tool=tool, reason="provenance")
        self.metrics.inc(m.INJECTION_DETECTED, source="tool_provenance")
        return Evidence(
            id=self._ids(),
            signal="injection.tool_provenance",
            family="injection",
            observed={"tool": tool, "arg": arg, "value": defang(str(value))[:200]},
            weight=0.0,
            polarity="risk",
            source="computed",
            tier="T3",
            confidence=1.0,
        )

    def _reject(self, tool: str, reason: RejectReason, ev: Sequence[Evidence] = ()) -> ToolOutcome:
        if reason != "provenance":
            self.metrics.inc(m.TOOL_ERRORS, tool=tool[:64], reason=reason)
        return ToolOutcome(tool=tool[:64], status="rejected", evidence=tuple(ev), reason=reason)

    def validate(self, action: Action, ctx: ProvenanceContext) -> _Args | ToolOutcome:
        """Return typed args, or a rejected outcome (with injection evidence on provenance)."""
        spec = SPECS.get(action.tool)
        if spec is None:
            return self._reject(action.tool, "unknown_tool")
        if getattr(self.backends, spec.name) is None:
            return self._reject(spec.name, "unavailable")
        try:
            args = spec.args_model.model_validate(action.args)
        except ValidationError:
            return self._reject(spec.name, "bad_args")
        for a in spec.url_args:
            value = getattr(args, a)
            if not ctx.allows_url(value):
                return self._reject(spec.name, "provenance", [self._violation(spec.name, a, value)])
        for a in spec.domain_args:
            value = getattr(args, a)
            if not ctx.allows_domain(value):
                return self._reject(spec.name, "provenance", [self._violation(spec.name, a, value)])
        if isinstance(args, CompareBrandArgs) and args.brand_id not in self.brand_ids:
            return self._reject(spec.name, "unknown_brand")
        if isinstance(args, FingerprintArgs) and not ctx.allows_fingerprint(args.fingerprint):
            return self._reject(
                spec.name,
                "provenance",
                [self._violation(spec.name, "fingerprint", args.fingerprint)],
            )
        return args

    def _invoke(self, name: str, args: _Args) -> Awaitable[EvidenceList]:
        b = self.backends
        if isinstance(args, CompareBrandArgs) and b.compare_brand:
            return b.compare_brand(args.brand_id, args.domain)
        if isinstance(args, RenderArgs) and b.render_page:
            return b.render_page(args.url, args.profile)
        if isinstance(args, FingerprintArgs) and b.search_similar_scripts:
            return b.search_similar_scripts(args.fingerprint)
        fn = getattr(b, name)
        value = args.domain if isinstance(args, DomainArgs) else getattr(args, "url")  # noqa: B009
        result: Awaitable[EvidenceList] = fn(value)
        return result

    async def execute(
        self, action: Action, ctx: ProvenanceContext, *, timeout_s: float | None = None
    ) -> ToolOutcome:
        checked = self.validate(action, ctx)
        if isinstance(checked, ToolOutcome):
            return checked
        spec = SPECS[action.tool]
        budget = spec.budget_ms / 1000
        if timeout_s is not None:
            budget = min(budget, timeout_s)
        if budget <= 0:
            return self._reject(spec.name, "budget")
        t0 = self._clock()
        try:
            raw = await asyncio.wait_for(self._invoke(spec.name, checked), timeout=budget)
        except TimeoutError:
            self.metrics.inc(m.TOOL_ERRORS, tool=spec.name, reason="timeout")
            return ToolOutcome(spec.name, "timeout", reason="timeout", ms=self._ms(t0))
        except Exception as exc:  # backend failure must not crash the investigation
            self.metrics.inc(m.TOOL_ERRORS, tool=spec.name, reason="error")
            return ToolOutcome(spec.name, "error", reason=type(exc).__name__, ms=self._ms(t0))
        raw_list = [e for e in raw if isinstance(e, Evidence)]
        new_ctx = ctx.with_hops(_hops_from(raw_list)) if spec.name == "expand_redirects" else ctx
        evidence = tuple(restamp(e, tier="T3", new_id=self._ids()) for e in raw_list[:16])
        return ToolOutcome(spec.name, "ok", evidence, ms=self._ms(t0), context=new_ctx)

    def _ms(self, t0: float) -> int:
        return max(0, int((self._clock() - t0) * 1000))
