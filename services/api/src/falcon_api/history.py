"""Read-only history of Investigator checks (`read` scope): `GET /v1/verdicts` and `GET /v1/verdicts/stream`.

Source of truth is the platform event bus `fl:events` (verdict.created / verdict.upgraded); each event names a
verdict whose final document is then loaded and reduced to a *summary*. A summary never carries raw input, URL
userinfo, paths, queries, evidence bodies or reasons text (docs/PRIVACY.md): for links only the defanged host, for
messages, emails and images nothing at all.
"""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

from falcon_api.auth import Principal
from falcon_api.jobs import Jobs
from falcon_api.problem import PROBLEM_RESPONSES, Problem
from falcon_api.store import StoreUnavailableError
from falcon_core.provenance import effective_source

EVENTS_STREAM = "fl:events"
HISTORY_EVENT_TYPES = frozenset({"verdict.created", "verdict.upgraded"})
STREAM_MAX_S = 300.0
STREAM_HEARTBEAT_S = 10.0
SCAN_BATCH = 200
SCAN_MAX = 2000  # events inspected per list call: bounds the work when filters match little
STREAM_ID_RE = re.compile(r"^\d{1,20}-\d{1,20}$")
_REASON_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
TIER_ORDER = ("T0", "T1", "T2", "T3")

InputTypeLit = Literal["url", "message", "email", "image"]
VerdictLit = Literal["dangerous", "suspicious", "no_warning_signs"]
TierLit = Literal["T0", "T1", "T2", "T3"]


class AgentActivity(BaseModel):
    """What the Investigator did for one check (derived counts only)."""

    tiers_run: list[TierLit] = Field(description="Cascade tiers executed, T0 up to `tier_reached`.")
    extractor_ran: bool = Field(description="The structured-extraction model contributed evidence.")
    investigator_ran: bool = Field(description="The T3 tool-using investigator ran.")
    tool_calls: int = Field(ge=0, description="Tool calls recorded in the sanitised trace.")
    llm_calls: int = Field(ge=0, description="Model calls recorded in the sanitised trace.")


class VerdictSummary(BaseModel):
    """One row of the operator history. No raw input and no personal data."""

    verdict_id: str
    created_at: str
    input_type: InputTypeLit
    display: str | None = Field(
        description="Defanged host for links (no userinfo, path or query); null for messages, emails and images."
    )
    verdict: VerdictLit
    risk_score: int = Field(ge=0, le=100)
    degraded: bool
    degraded_reasons: list[str]
    tier_reached: TierLit
    model_route: Literal["cloud", "local", "none"]
    source: Literal["live", "replay", "synthetic", "fixture"]
    channel: Literal["web", "extension", "api", "mcp", "voice"] | None = Field(
        default=None, description="Which client asked for the check; null when it did not say."
    )
    agent: AgentActivity


class VerdictPage(BaseModel):
    items: list[VerdictSummary]
    next_cursor: str | None = Field(description="Opaque cursor for the next page; null on the last page.")


def defanged_host(canonical_url: object) -> str | None:
    """`hxxps://user:pw@a[.]b/path?q` becomes `hxxps://a[.]b`: host only, userinfo and everything after dropped."""
    if not isinstance(canonical_url, str) or not canonical_url:
        return None
    live = canonical_url.strip().replace("[.]", ".").replace("[:]", ":")
    live = re.sub(r"^hxxp(s?)://", r"http\1://", live, flags=re.IGNORECASE)
    try:
        parts = urlsplit(live)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not host or len(host) > 253 or ":" in host:
        return None
    if not _HOST_RE.match(host):
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
        if not _HOST_RE.match(host):
            return None
    scheme = "hxxps" if parts.scheme == "https" else "hxxp"
    return f"{scheme}://{host.replace('.', '[.]')}"


def _host_of(url: Any) -> str:
    try:
        return urlsplit(str(url)).hostname or ""
    except ValueError:
        return ""


def summarize(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Reduce a verdict document to a `VerdictSummary` dict; None when the document is not a usable verdict."""
    try:
        evidence = [e for e in doc.get("evidence") or [] if isinstance(e, dict)]
        trace = [s for s in doc.get("trace") or [] if isinstance(s, dict)]
        reached = doc["tier_reached"]
        tiers = list(TIER_ORDER[: TIER_ORDER.index(reached) + 1])
        names = [str(s.get("name") or "") for s in trace]
        sources = [str(e.get("source") or "") for e in evidence]
        extractor = "llm:extractor" in sources or any(n.startswith("extractor") for n in names)
        investigator = "llm:investigator" in sources or any(n.startswith("investigator") for n in names)
        reasons = [r for r in doc.get("degraded_reasons") or [] if isinstance(r, str) and _REASON_CODE_RE.match(r)]
        out = {
            "verdict_id": str(doc["verdict_id"]),
            "created_at": str(doc["created_at"]),
            "input_type": doc["input_type"],
            "display": defanged_host(doc.get("canonical_url")) if doc["input_type"] == "url" else None,
            "verdict": doc["verdict"],
            "risk_score": int(doc["risk_score"]),
            "degraded": bool(doc["degraded"]),
            "degraded_reasons": reasons[:8],
            "tier_reached": reached,
            "model_route": doc["model_route"],
            "source": effective_source(str(doc.get("source") or "live"), [_host_of(doc.get("canonical_url"))]),
            "channel": doc.get("channel"),
            "agent": {
                "tiers_run": tiers,
                "extractor_ran": extractor,
                "investigator_ran": investigator,
                "tool_calls": sum(1 for s in trace if s.get("kind") == "tool"),
                "llm_calls": sum(1 for s in trace if s.get("kind") == "llm"),
            },
        }
        return VerdictSummary.model_validate(out).model_dump(mode="json")
    except (KeyError, ValueError, TypeError):
        return None


def _event_of(fields: dict[str, Any]) -> dict[str, Any] | None:
    try:
        ev = json.loads(fields.get("event", ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(ev, dict) or ev.get("type") not in HISTORY_EVENT_TYPES:
        return None
    return ev if isinstance(ev.get("verdict_id"), str) else None


def register(
    app: FastAPI,
    *,
    get_redis: Callable[[], Redis | None],
    get_jobs: Callable[[], Jobs],
    require: Callable[[str], Callable[..., Awaitable[Principal]]],
    stream_acquire: Callable[[Request], None],
    stream_release: Callable[[Request], None],
    count: Callable[[str], Awaitable[int]],
    client_ip: Callable[[Request], str],
    per_ip_per_min: int = 60,
) -> None:
    ReadScope = Depends(require("read"))

    async def ip_gate(request: Request) -> None:
        """Per-address limit on top of the per-key one (the gateway forwards X-Falcon-Client-IP)."""
        bucket = f"rl:hist:{client_ip(request)}:{int(time.time() // 60)}"
        if per_ip_per_min > 0 and await count(bucket) > per_ip_per_min:
            raise Problem(
                429,
                "rate-limited",
                "Rate limit exceeded",
                headers={"Retry-After": str(60 - int(time.time() % 60)), "X-RateLimit-Limit": str(per_ip_per_min)},
            )

    def redis_or_503() -> Redis:
        r = get_redis()
        if r is None:
            raise Problem(503, "queue-unavailable", "Queue unavailable")
        return r

    async def load_summary(ev: dict[str, Any]) -> dict[str, Any] | None:
        try:
            doc = await get_jobs().latest(str(ev["verdict_id"]))
        except (RedisError, StoreUnavailableError):
            return None
        return summarize(doc) if doc else None

    @app.get(
        "/v1/verdicts",
        tags=["verdicts"],
        response_model=VerdictPage,
        responses=PROBLEM_RESPONSES,
        dependencies=[Depends(ip_gate)],
    )
    async def list_verdicts(
        _p: Annotated[Principal, ReadScope],
        cursor: Annotated[str | None, Query(max_length=64, description="Opaque cursor from `next_cursor`.")] = None,
        limit: Annotated[int, Query(ge=1, le=100, description="Page size.")] = 25,
        verdict: VerdictLit | None = None,
        input_type: InputTypeLit | None = None,
    ) -> dict[str, Any]:
        """History of Investigator checks (read scope), newest first. Summaries only: no raw input, no personal data."""
        if cursor is not None and not STREAM_ID_RE.match(cursor):
            raise Problem(422, "invalid-cursor", "Invalid cursor")
        r = redis_or_503()
        upper = f"({cursor}" if cursor else "+"
        rows: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        scanned = 0
        try:
            while len(rows) <= limit and scanned < SCAN_MAX:
                batch: Any = await r.xrevrange(EVENTS_STREAM, max=upper, min="-", count=SCAN_BATCH)
                if not batch:
                    break
                for sid, fields in batch:
                    scanned += 1
                    upper = f"({sid}"
                    ev = _event_of(fields)
                    if ev is None or ev["verdict_id"] in seen:
                        continue
                    raw_payload = ev.get("payload")
                    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
                    if verdict and payload.get("verdict") != verdict:
                        continue
                    if input_type and payload.get("input_type") != input_type:
                        continue
                    summary = await load_summary(ev)
                    if summary is None:
                        continue
                    seen.add(ev["verdict_id"])
                    rows.append((sid, summary))
                    if len(rows) > limit:
                        break
        except RedisError as exc:
            raise Problem(503, "queue-unavailable", "Queue unavailable") from exc
        page = rows[:limit]
        return {"items": [s for _, s in page], "next_cursor": page[-1][0] if len(rows) > limit else None}

    @app.get(
        "/v1/verdicts/stream",
        tags=["verdicts"],
        response_class=EventSourceResponse,
        responses=PROBLEM_RESPONSES,
        dependencies=[Depends(ip_gate)],
    )
    async def verdicts_stream(
        request: Request,
        _p: Annotated[Principal, ReadScope],
        _gate: Annotated[None, Depends(stream_acquire)],
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> AsyncIterator[ServerSentEvent]:
        """SSE: `event: verdict`, data = one `VerdictSummary`. Bounded to 5 minutes; reconnect with Last-Event-ID."""
        try:
            r = redis_or_503()
            if last_event_id and STREAM_ID_RE.match(last_event_id):
                last = last_event_id
            else:
                try:
                    tail: Any = await r.xrevrange(EVENTS_STREAM, count=1)
                except RedisError as exc:
                    raise Problem(503, "queue-unavailable", "Queue unavailable") from exc
                last = tail[0][0] if tail else "0-0"
            started = last_hb = time.monotonic()
            seen: set[str] = set()
            yield ServerSentEvent(comment="stream open", retry=3000)
            while time.monotonic() - started < STREAM_MAX_S:
                if await request.is_disconnected():
                    return
                try:
                    res: Any = await r.xread({EVENTS_STREAM: last}, block=1000, count=50)
                except RedisError:
                    await asyncio.sleep(1)
                    res = []
                emitted = False
                for _name, entries in res or []:
                    for sid, fields in entries:
                        last = sid
                        ev = _event_of(fields)
                        if ev is None or ev["verdict_id"] in seen:
                            continue
                        summary = await load_summary(ev)
                        if summary is None:
                            continue
                        if len(seen) > 500:
                            seen.clear()
                        seen.add(ev["verdict_id"])
                        yield ServerSentEvent(data=summary, event="verdict", id=sid)
                        emitted = True
                now = time.monotonic()
                if emitted:
                    last_hb = now
                elif now - last_hb >= STREAM_HEARTBEAT_S:
                    last_hb = now
                    yield ServerSentEvent(comment="heartbeat")
        finally:
            stream_release(request)


__all__ = ["AgentActivity", "VerdictPage", "VerdictSummary", "defanged_host", "register", "summarize"]
