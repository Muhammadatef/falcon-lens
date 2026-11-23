"""Model router: role -> cloud (Anthropic) or local (Ollama), with the safety envelope around it.

Every ``complete_json`` call:
1. picks the route: cloud when a key is set, sovereign mode is off and the role has a cloud model;
   otherwise local. Cloud error or timeout falls back to local, counting ``fl_llm_fallback_total``;
2. redacts PII in all text it sends (docs/PRIVACY.md) and spotlights untrusted text (nonce
   delimiters + ``^`` datamarking);
3. sends a stable, cacheable system prompt that carries a canary; any reply containing the canary
   is discarded and counted in ``fl_canary_leak_total``;
4. parses exactly one JSON object with the pydantic schema, retries once with a repair prompt, then
   returns the caller's template fallback;
5. accounts tokens and USD cost per call, and samples a fraction (``FL_SHADOW_RATE``) to the other
   route in the background to measure ``fl_route_agreement_ratio``.

The router returns typed data only. It never scores.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from opentelemetry.trace import Status as SpanStatus
from opentelemetry.trace import StatusCode
from pydantic import BaseModel

from falcon_core.llm import metrics as m
from falcon_core.llm.accounting import Usage, cost_usd
from falcon_core.llm.canary import leaks as canary_leaks
from falcon_core.llm.canary import new_canary
from falcon_core.llm.config import Role, Route, RouterConfig
from falcon_core.llm.parsing import ParseError, parse_model
from falcon_core.llm.providers import (
    AnthropicProvider,
    ChatTurn,
    OllamaProvider,
    Provider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)
from falcon_core.llm.redaction import redact
from falcon_core.llm.spotlight import UntrustedText, new_nonce, spotlight, spotlight_notice
from falcon_core.prompts import BASE_SYSTEM, CANARY_LINE, REPAIR_PROMPT, SCHEMA_LINE
from falcon_core.telemetry.tracing import llm_span, set_llm_usage

log = logging.getLogger("falcon_core.llm")

Status = Literal["ok", "repaired", "fallback", "failed"]
_MAX_REPAIR_ECHO = 2000


@dataclass(frozen=True, slots=True)
class JsonRequest[T: BaseModel]:
    role: Role
    task: str  # stable, trusted role instructions (part of the cached system prompt)
    schema: type[T]
    context: str = ""  # trusted structured context built by our code (e.g. evidence JSON)
    untrusted: Sequence[UntrustedText] = ()
    history: Sequence[ChatTurn] = ()  # earlier turns of a multi-step loop (already safe text)
    max_output_tokens: int = 512
    timeout_s: float | None = None  # overall cap for this call, fallback included
    validation_context: Mapping[str, Any] | None = None
    fallback: Callable[[], T] | None = None
    verdict_id: str | None = None
    allow_shadow: bool = True


@dataclass(frozen=True, slots=True)
class CallRecord:
    route: Route
    model: str
    usage: Usage
    cost_usd: float
    ms: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResult[T: BaseModel]:
    value: T | None
    status: Status
    route: Literal["cloud", "local", "none"]
    model: str | None
    usage: Usage
    cost_usd: float
    fell_back: bool = False
    canary_leak: bool = False
    error: str | None = None
    calls: tuple[CallRecord, ...] = ()
    redactions: Mapping[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "repaired") and self.value is not None


@dataclass(frozen=True, slots=True)
class ShadowSample:
    role: Role
    primary_route: Route
    shadow_route: Route
    agree: bool | None  # None = the shadow call failed
    verdict_id: str | None


ShadowHook = Callable[[ShadowSample], Awaitable[None]]


def _schema_json(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))


def _provider_name(route: str, model: str) -> str:
    """Coarse provider label for traces (``anthropic`` for the cloud route, ``ollama`` locally)."""
    return "anthropic" if route == "cloud" else "ollama"


class LLMRouter:
    def __init__(
        self,
        config: RouterConfig | None = None,
        *,
        cloud: Provider | None = None,
        local: Provider | None = None,
        metrics: m.MetricsSink | None = None,
        rng: random.Random | None = None,
        canary: str | None = None,
        shadow_hook: ShadowHook | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or RouterConfig.from_env()
        self.metrics: m.MetricsSink = metrics or m.default_metrics()
        self._cloud: Provider | None = None
        if self.config.cloud_enabled:
            self._cloud = cloud or AnthropicProvider(self.config.anthropic_api_key or "")
        self._local: Provider = local or OllamaProvider(self.config.ollama_base_url)
        self._rng = rng or random.Random()  # noqa: S311 - sampling, not security
        self.canary = canary or new_canary()
        self._shadow_hook = shadow_hook
        self._shadow_tasks: set[asyncio.Task[None]] = set()
        self._system_cache: dict[tuple[str, str], str] = {}
        self._clock = clock

    # --- routing -----------------------------------------------------------------------------

    def plan(self, role: Role) -> list[tuple[Route, str, Provider]]:
        """Ordered attempts for a role: cloud then local, or local only."""
        out: list[tuple[Route, str, Provider]] = []
        cloud_model = self.config.cloud_models.get(role)
        if self._cloud is not None and cloud_model:
            out.append(("cloud", cloud_model, self._cloud))
        out.append(("local", self.config.local_model_for(role), self._local))
        return out

    def primary_route(self, role: Role) -> Route:
        return self.plan(role)[0][0]

    def _timeout_for(self, route: Route) -> float:
        return self.config.cloud_timeout_s if route == "cloud" else self.config.local_timeout_s

    # --- prompt building ---------------------------------------------------------------------

    def system_prompt(self, task: str, schema: type[BaseModel]) -> str:
        key = (task, schema.__qualname__)
        cached = self._system_cache.get(key)
        if cached is None:
            cached = "\n\n".join(
                [
                    BASE_SYSTEM,
                    task,
                    SCHEMA_LINE.format(schema=_schema_json(schema)),
                    CANARY_LINE.format(canary=self.canary),
                ]
            )
            self._system_cache[key] = cached
        return cached

    def _user_turn(self, req: JsonRequest[Any]) -> tuple[str, dict[str, int]]:
        counts: dict[str, int] = {}

        def red(text: str) -> str:
            r = redact(text)
            for k, v in r.counts.items():
                counts[k] = counts.get(k, 0) + v
            return r.text

        parts: list[str] = []
        if req.untrusted:
            nonce = new_nonce()
            parts.append(spotlight_notice(nonce))
        if req.context:
            parts.append(red(req.context))
        if req.untrusted:
            for item in req.untrusted:
                parts.append(spotlight(UntrustedText(item.label, red(item.text)), nonce))
        parts.append("Reply with the JSON object only.")
        return "\n\n".join(parts), counts

    # --- canary ------------------------------------------------------------------------------

    def leaks_canary(self, text: str) -> bool:
        return canary_leaks(text, self.canary)

    # --- main entry --------------------------------------------------------------------------

    async def complete_json[T: BaseModel](self, req: JsonRequest[T]) -> LLMResult[T]:
        start = self._clock()
        deadline = start + req.timeout_s if req.timeout_s is not None else None
        system = self.system_prompt(req.task, req.schema)
        user, redactions = self._user_turn(req)
        turns = [*req.history, ChatTurn("user", user)]
        calls: list[CallRecord] = []
        fell_back = False

        resp: ProviderResponse | None = None
        used: tuple[Route, str, Provider] | None = None
        for route, model, provider in self.plan(req.role):
            r = await self._call(req, route, model, provider, system, turns, deadline, calls)
            if r is not None:
                resp, used = r, (route, model, provider)
                break
            if route == "cloud":
                fell_back = True
                self.metrics.inc(m.LLM_FALLBACK, role=req.role)

        if resp is None or used is None:
            return self._finish(req, "none", None, None, calls, fell_back, False, "all routes failed", redactions)

        route, model, provider = used
        if self.leaks_canary(resp.text):
            self.metrics.inc(m.CANARY_LEAK, role=req.role)
            log.warning(
                "canary leak",
                extra={"role": req.role, "route": route, "verdict_id": req.verdict_id},
            )
            return self._finish(req, route, model, None, calls, fell_back, True, "canary leak", redactions)

        try:
            value = parse_model(resp.text, req.schema, req.validation_context)
            result = self._finish(req, route, model, value, calls, fell_back, False, None, redactions)
            self._maybe_shadow(req, route, system, turns, value)
            return result
        except ParseError as first:
            repair_turns = [
                *turns,
                ChatTurn("assistant", resp.text[:_MAX_REPAIR_ECHO] or "(empty)"),
                ChatTurn("user", REPAIR_PROMPT.format(error=first.summary[:300])),
            ]
            r2 = await self._call(req, route, model, provider, system, repair_turns, deadline, calls)
            if r2 is None:
                return self._finish(req, route, model, None, calls, fell_back, False, first.summary, redactions)
            if self.leaks_canary(r2.text):
                self.metrics.inc(m.CANARY_LEAK, role=req.role)
                return self._finish(req, route, model, None, calls, fell_back, True, "canary leak", redactions)
            try:
                value = parse_model(r2.text, req.schema, req.validation_context)
            except ParseError as second:
                return self._finish(req, route, model, None, calls, fell_back, False, second.summary, redactions)
            return self._finish(req, route, model, value, calls, fell_back, False, None, redactions, repaired=True)

    async def _call(
        self,
        req: JsonRequest[Any],
        route: Route,
        model: str,
        provider: Provider,
        system: str,
        turns: Sequence[ChatTurn],
        deadline: float | None,
        calls: list[CallRecord],
    ) -> ProviderResponse | None:
        """One provider call inside an OpenInference LLM span: role, route, model, latency and
        token counts only. Prompts and outputs are never recorded (untrusted text)."""
        n = len(calls)
        with llm_span(
            model=model, role=req.role, verdict_id=req.verdict_id, provider=_provider_name(route, model)
        ) as sp:
            sp.set_attribute("fl.llm.route", route)
            resp = await self._call_inner(req, route, model, provider, system, turns, deadline, calls)
            if len(calls) > n:
                rec = calls[-1]
                sp.set_attribute("fl.latency_ms", rec.ms)
                if rec.error is None:
                    set_llm_usage(
                        sp,
                        input_tokens=rec.usage.prompt_tokens,
                        output_tokens=rec.usage.output_tokens,
                        cost_usd=rec.cost_usd or None,
                    )
                else:
                    sp.set_attribute("error.type", rec.error[:40])
                    sp.set_status(SpanStatus(StatusCode.ERROR))
            return resp

    async def _call_inner(
        self,
        req: JsonRequest[Any],
        route: Route,
        model: str,
        provider: Provider,
        system: str,
        turns: Sequence[ChatTurn],
        deadline: float | None,
        calls: list[CallRecord],
    ) -> ProviderResponse | None:
        timeout = self._timeout_for(route)
        if deadline is not None:
            timeout = min(timeout, deadline - self._clock())
        if timeout <= 0:
            calls.append(CallRecord(route, model, Usage(), 0.0, 0, "budget exhausted"))
            return None
        preq = ProviderRequest(
            model=model,
            system=system,
            turns=tuple(turns),
            max_tokens=max(1, req.max_output_tokens),
            timeout_s=timeout,
            cache_system=route == "cloud",
        )
        t0 = self._clock()
        try:
            resp = await asyncio.wait_for(provider.complete(preq), timeout=timeout)
        except (ProviderError, TimeoutError) as exc:
            kind = exc.kind if isinstance(exc, ProviderError) else "timeout"
            ms = int((self._clock() - t0) * 1000)
            calls.append(CallRecord(route, model, Usage(), 0.0, ms, kind))
            log.info(
                "llm call failed",
                extra={
                    "role": req.role,
                    "route": route,
                    "model": model,
                    "error": kind,
                    "verdict_id": req.verdict_id,
                },
            )
            return None
        ms = int((self._clock() - t0) * 1000)
        usd = cost_usd(route, model, resp.usage)
        calls.append(CallRecord(route, model, resp.usage, usd, ms))
        self.metrics.inc(
            m.LLM_TOKENS,
            resp.usage.prompt_tokens + resp.usage.output_tokens,
            model=model,
            role=req.role,
        )
        if usd:
            self.metrics.inc(m.LLM_COST, usd, model=model)
        log.info(
            "llm call",
            extra={
                "role": req.role,
                "route": route,
                "model": model,
                "ms": ms,
                "in_tokens": resp.usage.prompt_tokens,
                "out_tokens": resp.usage.output_tokens,
                "cost_usd": round(usd, 6),
                "verdict_id": req.verdict_id,
            },
        )
        return resp

    def _finish[T: BaseModel](
        self,
        req: JsonRequest[T],
        route: Route | Literal["none"] | None,
        model: str | None,
        value: T | None,
        calls: Sequence[CallRecord],
        fell_back: bool,
        canary_leak: bool,
        error: str | None,
        redactions: Mapping[str, int],
        repaired: bool = False,
    ) -> LLMResult[T]:
        usage = Usage()
        for c in calls:
            usage = usage + c.usage
        total_cost = sum(c.cost_usd for c in calls)
        status: Status
        if value is not None:
            status = "repaired" if repaired else "ok"
        elif req.fallback is not None:
            value = req.fallback()
            status = "fallback"
        else:
            status = "failed"
        return LLMResult(
            value=value,
            status=status,
            route="none" if route is None else route,
            model=model,
            usage=usage,
            cost_usd=total_cost,
            fell_back=fell_back,
            canary_leak=canary_leak,
            error=error,
            calls=tuple(calls),
            redactions=dict(redactions),
        )

    # --- shadow ------------------------------------------------------------------------------

    def _maybe_shadow(
        self,
        req: JsonRequest[Any],
        primary: Route,
        system: str,
        turns: Sequence[ChatTurn],
        value: BaseModel,
    ) -> None:
        if not req.allow_shadow or self.config.shadow_rate <= 0 or self._cloud is None:
            return  # sovereign / no key: never shadow to the cloud
        if self._rng.random() >= self.config.shadow_rate:
            return
        others = [p for p in self.plan(req.role) if p[0] != primary]
        if not others:
            return
        route, model, provider = others[0]
        task = asyncio.get_running_loop().create_task(
            self._shadow(req, primary, route, model, provider, system, turns, value)
        )
        self._shadow_tasks.add(task)
        task.add_done_callback(self._shadow_tasks.discard)

    async def _shadow(
        self,
        req: JsonRequest[Any],
        primary: Route,
        route: Route,
        model: str,
        provider: Provider,
        system: str,
        turns: Sequence[ChatTurn],
        value: BaseModel,
    ) -> None:
        calls: list[CallRecord] = []
        resp = await self._call(req, route, model, provider, system, turns, None, calls)
        agree: bool | None = None
        if resp is not None:
            if self.leaks_canary(resp.text):
                self.metrics.inc(m.CANARY_LEAK, role=req.role)
            else:
                try:
                    other = parse_model(resp.text, req.schema, req.validation_context)
                    agree = other.model_dump(mode="json") == value.model_dump(mode="json")
                except ParseError:
                    agree = False
        if agree is not None:
            self.metrics.observe(m.ROUTE_AGREEMENT, 1.0 if agree else 0.0, role=req.role)
        if self._shadow_hook is not None:
            await self._shadow_hook(ShadowSample(req.role, primary, route, agree, req.verdict_id))

    async def drain_shadow(self) -> None:
        """Wait for background shadow calls (tests, graceful shutdown)."""
        if self._shadow_tasks:
            await asyncio.gather(*list(self._shadow_tasks), return_exceptions=True)
