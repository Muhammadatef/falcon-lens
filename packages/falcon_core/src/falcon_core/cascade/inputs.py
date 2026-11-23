"""Message, email and image checks (docs/SCORING.md hard rule H5).

The deterministic analyzers (``signals.message`` / ``signals.email`` / ``signals.image``) produce rule
evidence and *child inputs*. Child URLs go through the URL cascade (headless: their verdicts are not
published) and come back as ``message.link_verdict`` / ``email.link_verdict`` evidence; a dangerous child
fires H5. The quarantined extractor then reads the (redacted, spotlighted) body and may add risk-only
evidence. Images without an OCR hook degrade honestly (``ocr_unavailable``): only QR payloads are judged.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from falcon_core.cascade.ai import AgentExtractorAdapter, injection_evidence, risk_only
from falcon_core.cascade.assemble import TraceStep, display_url
from falcon_core.cascade.evidence import dedupe, from_signal, make_evidence
from falcon_core.cascade.ids import new_verdict_id
from falcon_core.scoring.evidence import Evidence
from falcon_core.signals.email.analyze import analyze_email
from falcon_core.signals.image.analyze import analyze_image
from falcon_core.signals.message.analyze import analyze_message
from falcon_core.signals.message.extract import ChildInput
from falcon_core.signals.url.canonical import canonicalize
from falcon_core.signals.url.textutil import defang

if TYPE_CHECKING:
    from falcon_core.cascade.engine import Cascade, VerdictSink

log = logging.getLogger("falcon.cascade.inputs")

MAX_CHILD_URLS = 10
CHILD_CONCURRENCY = 5
CHILD_TIMEOUT_S = 30.0
TextKind = Literal["message", "email", "image"]


class _Collect:
    """Headless sink for child URL checks: keeps the docs, publishes nothing."""

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    async def emit(self, doc: dict[str, Any], meta: Any) -> None:
        self.docs.append(doc)


def fingerprint(kind: str, data: bytes) -> str:
    return hashlib.sha256(kind.encode() + b"\0" + data).hexdigest()


async def run_input(
    cascade: Cascade,
    verdict_id: str,
    input_type: TextKind,
    data: bytes,
    sink: VerdictSink,
    *,
    source: str = "live",
    input_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Run a message / email / image check and return the final verdict doc (also emitted to ``sink``)."""
    from falcon_core.cascade.engine import SinkError, _Run

    run = _Run(verdict_id=verdict_id, source=source, t_start=time.perf_counter(), input_type=input_type)
    run.fingerprint = input_fingerprint or fingerprint(input_type, data)
    tier: Literal["T1", "T2"] = "T1"
    try:
        t0 = time.perf_counter()
        body, children, ev = _analyse(cascade, run, input_type, data)
        run.evidence.extend(ev)
        run.trace.append(
            TraceStep("T1", f"{input_type} rules and {len(children)} child links extracted", tuple(e.id for e in ev),
                      int((time.perf_counter() - t0) * 1000))
        )  # fmt: skip
        await cascade._emit(sink, run, cascade._score(run), "T1", final=False)

        tier = "T2"
        t0 = time.perf_counter()
        link_ev = await _judge_children(cascade, run, input_type, children)
        run.evidence.extend(link_ev)
        run.trace.append(
            TraceStep("T2", f"{len(link_ev)} linked URLs checked through the URL pipeline",
                      tuple(e.id for e in link_ev), int((time.perf_counter() - t0) * 1000))
        )  # fmt: skip
        result = cascade._score(run)
        if body and not any(r.rule_id == "H5" for r in result.fired_rules):
            await _extract(cascade, run, input_type, body)
        run.page_tier = True
        return await cascade._emit(sink, run, cascade._score(run), tier, final=True)
    except SinkError:
        raise
    except Exception as exc:  # noqa: BLE001 - still end with one final verdict
        if run.final_emitted:
            raise
        log.exception("input pipeline failed", extra={"verdict_id": verdict_id})
        run.degraded_reasons.append(f"internal_error:{type(exc).__name__}")
        return await cascade._emit(sink, run, cascade._score(run), tier, final=True)


def _analyse(
    cascade: Cascade, run: Any, input_type: TextKind, data: bytes
) -> tuple[str, list[ChildInput], list[Evidence]]:
    reg = cascade.d.registry
    ev: list[Evidence] = []
    children: list[ChildInput] = []
    body = ""
    if input_type == "message":
        body = data.decode("utf-8", "replace")
    elif input_type == "email":
        mail = analyze_email(data, reg)
        ev += [from_signal(e) for e in mail.evidence]
        children += mail.children
        body = mail.body_text
    else:
        img = analyze_image(data)
        ev += [from_signal(e) for e in img.evidence]
        children += img.children
        if img.needs_ocr:
            run.degraded_reasons.append("ocr_unavailable")  # no OCR hook: only QR payloads were judged
    if body:
        msg = analyze_message(body, reg)
        ev += [from_signal(e) for e in msg.evidence]
        children += msg.children
        ev += injection_evidence(cascade.d.injection, body)
    return body, children, dedupe(ev)


def _canon_key(value: str) -> str:
    c = canonicalize(value)
    return c.url if c.ok else value


async def _judge_children(
    cascade: Cascade, run: Any, input_type: TextKind, children: list[ChildInput]
) -> list[Evidence]:
    """Check every distinct link up to ``MAX_CHILD_URLS``; more than that degrades the check (never ignored
    silently). Order independent: the first ``MAX_CHILD_URLS`` distinct links are all judged concurrently."""
    urls = list(dict.fromkeys(_canon_key(c.value) for c in children if c.kind == "url"))
    if len(urls) > MAX_CHILD_URLS:
        run.degraded_reasons.append("links_over_limit")
        urls = urls[:MAX_CHILD_URLS]
    if not urls:
        return []
    family: Literal["message", "email"] = "email" if input_type == "email" else "message"
    gate = asyncio.Semaphore(CHILD_CONCURRENCY)

    async def one(url: str) -> Evidence:
        sink = _Collect()
        try:
            async with gate:
                await asyncio.wait_for(cascade.run_url(new_verdict_id(), url, sink, source=run.source), CHILD_TIMEOUT_S)
            doc = sink.docs[-1]
            if doc["model_route"] != "none":
                run.routes.add(doc["model_route"])  # the parent verdict reports every agent call it relied on
            if doc["degraded"] and any(e["weight"] > 0 or e.get("hard_rule") for e in doc["evidence"]):
                # An unjudged link that already shows risk must not read as safe. A degraded link with no
                # risk evidence (e.g. a flaky enrichment signal on a clean URL) does not taint the parent.
                run.degraded_reasons.append("child_check_degraded")
            observed: dict[str, Any] = {
                "verdict": doc["verdict"],
                "url": defang(display_url(url))[:200],
                "child_degraded": bool(doc["degraded"]),
            }
            return make_evidence(f"{family}.link_verdict", family, observed, tier="T2", source="computed")
        except Exception as exc:  # noqa: BLE001 - an unjudged link is a degraded check, not a silent pass
            run.degraded_reasons.append("child_check_failed")
            return make_evidence(
                f"{family}.link_verdict", family, None, tier="T2", source="computed", confidence=0.0,
                error=type(exc).__name__[:40],
            )  # fmt: skip

    return list(await asyncio.gather(*(one(u) for u in urls)))


async def _extract(cascade: Cascade, run: Any, input_type: TextKind, body: str) -> None:
    ex = cascade.d.extractor
    if not isinstance(ex, AgentExtractorAdapter) or not cascade.llm_allowed():
        return
    kind = "message" if input_type != "email" else "email"
    try:
        ev = await asyncio.wait_for(ex.extract_text(kind, body, run.verdict_id), cascade.d.extractor_timeout_s)
        run.evidence.extend(risk_only(e) for e in ev)
        if ev.route != "none":
            run.routes.add(ev.route)
    except Exception as exc:  # noqa: BLE001 - extractor is optional
        cascade.d.metrics.tool_errors.labels("extractor", type(exc).__name__[:40]).inc()
        if isinstance(exc, TimeoutError):
            cascade.llm_trip()
