"""Integration surface routes: reports, feedback, campaigns, incidents, operator actions, STIX, meta."""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import Depends, FastAPI, Header, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from ulid import ULID

from falcon_api.auth import Principal
from falcon_api.canon import canonicalize_url, sha256_hex
from falcon_api.db import SubmissionStore
from falcon_api.intel import (
    SentinelClient,
    campaign_of,
    is_campaign,
    merge_bundles,
    meta,
    paginate,
)
from falcon_api.problem import PROBLEM_RESPONSES, Problem
from falcon_core.config import Settings

EVENTS_STREAM = "fl:events"
BOARD_STREAM = "fl:board"
STREAM_MAX_S = 300.0
STREAM_HEARTBEAT_S = 10.0
MAX_TEXT_BYTES = 8 * 1024
INCIDENT_ID_RE = r"^inc_[0-9A-HJKMNP-TV-Z]{26}$"
ACTION_ID_RE = r"^act_[A-Za-z0-9_-]{1,64}$"
VERDICT_ID_RE = r"^vd_[0-9A-HJKMNP-TV-Z]{26}$"
STIX_MEDIA = "application/stix+json;version=2.1"


class ReportIn(BaseModel):
    kind: Literal["url", "message", "email", "phone", "other"] = Field(description="What is being reported.")
    text: str | None = Field(
        default=None,
        description="The reported URL or message. Hashed on receipt; kept only if consent_store_text is true.",
    )
    verdict_id: str | None = Field(default=None, pattern=VERDICT_ID_RE, description="Related verdict, if any.")
    script_fingerprint: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_.:-]{1,64}$", description="Script cluster id, if the client has one."
    )
    consent_store_text: bool = Field(default=False, description="Opt in to storing `text` (default: hashes only).")


class ReportAccepted(BaseModel):
    report_id: str
    status: Literal["received"] = "received"
    text_stored: bool


class FeedbackIn(BaseModel):
    verdict_id: str = Field(pattern=VERDICT_ID_RE)
    rating: Literal["correct", "false_alarm", "missed_scam", "unclear"]
    comment: str | None = Field(default=None, max_length=500, description="Stored only with consent_store_text.")
    consent_store_text: bool = False


class FeedbackAccepted(BaseModel):
    feedback_id: str
    status: Literal["received"] = "received"


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = Field(description="Opaque cursor for the next page; null on the last page.")


class Decision(BaseModel):
    incident_id: str
    action_id: str
    decision: Literal["approved", "rejected"]


class Meta(BaseModel):
    thresholds: dict[str, float] | None = Field(description="Verdict band thresholds from the arbiter params.")
    thresholds_draft: bool | None
    model_ids: dict[str, str]
    sovereign_mode: bool
    feeds: dict[str, bool]


@dataclass
class Ctx:
    settings: Settings
    state: dict[str, Any]
    submissions: Callable[[], SubmissionStore]
    sentinel: Callable[[], SentinelClient]
    require: Callable[[str], Callable[..., Awaitable[Principal]]]
    idem_begin: Callable[[Request, str], Awaitable[tuple[str | None, Response | None]]]
    idem_save: Callable[[str | None, str, int, dict[str, Any]], Awaitable[None]]
    source_for: Callable[[Request], str]
    known_verdict: Callable[[str], Awaitable[bool]]


def _event(kind: str, source: str, verdict_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_id": f"evt_{ULID()}",
        "type": kind,
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": source,
        "verdict_id": verdict_id,
        "payload": payload,
    }


def register(app: FastAPI, c: Ctx) -> None:
    def redis_of() -> Redis | None:
        return cast("Redis | None", c.state["redis"])

    async def emit(ev: dict[str, Any]) -> None:
        r: Redis | None = redis_of()
        if r is None:
            raise Problem(503, "queue-unavailable", "Queue unavailable")
        try:
            await r.xadd(EVENTS_STREAM, {"event": json.dumps(ev)}, maxlen=100_000, approximate=True)
        except RedisError as exc:
            raise Problem(503, "queue-unavailable", "Queue unavailable") from exc

    Cursor = Annotated[str | None, Query(max_length=512, description="Opaque cursor from `next_cursor`.")]
    Limit = Annotated[int, Query(ge=1, le=100, description="Page size.")]
    Read = Depends(c.require("read"))
    Operator = Depends(c.require("operator"))
    Intel = Depends(c.require("intel"))

    # ---- citizen intake -----------------------------------------------------------------------
    @app.post(
        "/v1/reports", tags=["intake"], status_code=202, response_model=ReportAccepted, responses=PROBLEM_RESPONSES
    )
    async def submit_report(request: Request, body: ReportIn) -> Response:
        """Citizen report intake. Stores hashes only unless `consent_store_text` is true."""
        raw = (body.text or "").encode()
        if len(raw) > MAX_TEXT_BYTES:
            raise Problem(413, "payload-too-large", "Text longer than 8 KB")
        if not raw and body.verdict_id is None:
            raise Problem(422, "invalid-request", "Provide `text` or `verdict_id`")
        content_hash: str | None = None
        if raw:
            if body.kind == "url":
                try:
                    content_hash = sha256_hex("url\0" + canonicalize_url(body.text or ""))
                except ValueError as exc:
                    raise Problem(422, "invalid-url", "Not a checkable http(s) URL") from exc
            else:
                content_hash = sha256_hex(f"{body.kind}\0".encode() + raw)
        idem_hash = sha256_hex(f"report\0{body.kind}\0{content_hash}\0{body.verdict_id}")
        rk, replay = await c.idem_begin(request, idem_hash)
        if replay is not None:
            return replay
        source = c.source_for(request)
        rid = f"rpt_{ULID()}"
        stored = bool(body.consent_store_text and body.text)
        await c.submissions().add(
            {
                "submission_id": rid,
                "kind": "report",
                "input_kind": body.kind,
                "verdict_id": body.verdict_id,
                "content_sha256": content_hash,
                "opt_in_text": body.text if stored else None,
                "source": source,
                "created_at": datetime.now(UTC),
            }
        )
        payload: dict[str, Any] = {"report_id": rid, "kind": body.kind}
        if body.verdict_id:
            payload["verdict_id"] = body.verdict_id
        if content_hash:
            payload["content_sha256"] = content_hash
        if body.script_fingerprint:
            payload["script_fingerprint"] = body.script_fingerprint
        await emit(_event("report.submitted", source, body.verdict_id, payload))
        out = ReportAccepted(report_id=rid, text_stored=stored).model_dump()
        await c.idem_save(rk, idem_hash, 202, out)
        return JSONResponse(out, status_code=202)

    @app.post(
        "/v1/feedback", tags=["intake"], status_code=202, response_model=FeedbackAccepted, responses=PROBLEM_RESPONSES
    )
    async def submit_feedback(request: Request, body: FeedbackIn) -> Response:
        """Feedback on a verdict (was it right?). Comment text is stored only with consent."""
        if not await c.known_verdict(body.verdict_id):
            raise Problem(404, "verdict-not-found", "Verdict not found")
        idem_hash = sha256_hex(f"feedback\0{body.verdict_id}\0{body.rating}")
        rk, replay = await c.idem_begin(request, idem_hash)
        if replay is not None:
            return replay
        source = c.source_for(request)
        fid = f"fbk_{ULID()}"
        stored = bool(body.consent_store_text and body.comment)
        await c.submissions().add(
            {
                "submission_id": fid,
                "kind": "feedback",
                "verdict_id": body.verdict_id,
                "content_sha256": sha256_hex(f"comment\0{body.comment}") if body.comment else None,
                "rating": body.rating,
                "opt_in_text": body.comment if stored else None,
                "source": source,
                "created_at": datetime.now(UTC),
            }
        )
        await emit(
            _event(
                "feedback.submitted",
                source,
                body.verdict_id,
                {"feedback_id": fid, "verdict_id": body.verdict_id, "kind": "feedback", "signal": body.rating},
            )
        )
        out = FeedbackAccepted(feedback_id=fid).model_dump()
        await c.idem_save(rk, idem_hash, 202, out)
        return JSONResponse(out, status_code=202)

    # ---- streams (Redis stream fl:board) -------------------------------------------------------
    async def board_stream(
        request: Request,
        last_event_id: str | None,
        project: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]],
        event: str,
    ) -> AsyncIterator[ServerSentEvent]:
        r: Redis | None = redis_of()
        if r is None:
            raise Problem(503, "queue-unavailable", "Queue unavailable")
        last = last_event_id if last_event_id and _is_stream_id(last_event_id) else "$"
        started = last_hb = time.monotonic()
        yield ServerSentEvent(comment="stream open", retry=3000)
        while time.monotonic() - started < STREAM_MAX_S:
            try:
                res: Any = await r.xread({BOARD_STREAM: last}, block=1000, count=20)
            except RedisError:
                await asyncio.sleep(1)
                continue
            for _name, entries in res or []:
                for sid, fields in entries:
                    last = sid
                    try:
                        card = json.loads(fields.get("data", "{}"))
                        doc = await project(card)
                    except (ValueError, TypeError, Problem):
                        continue
                    if doc is not None:
                        yield ServerSentEvent(data=doc, event=event, id=sid)
                        last_hb = time.monotonic()
            if time.monotonic() - last_hb >= STREAM_HEARTBEAT_S:
                last_hb = time.monotonic()
                yield ServerSentEvent(comment="heartbeat")

    async def full_incident(card: dict[str, Any]) -> dict[str, Any] | None:
        iid = card.get("incident_id")
        if not isinstance(iid, str):
            return None
        return await c.sentinel().incident(iid)

    async def project_campaign(card: dict[str, Any]) -> dict[str, Any] | None:
        inc = await full_incident(card)
        return campaign_of(inc) if inc and is_campaign(inc) else None

    @app.get(
        "/v1/campaigns/stream", tags=["campaigns"], response_class=EventSourceResponse, responses=PROBLEM_RESPONSES
    )
    async def campaigns_stream(
        request: Request,
        _p: Annotated[Principal, Read],
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> AsyncIterator[ServerSentEvent]:
        """SSE: `event: campaign`, data = one campaign object (contracts/campaign.schema.json)."""
        async for e in board_stream(request, last_event_id, project_campaign, "campaign"):
            yield e

    @app.get(
        "/v1/incidents/stream", tags=["incidents"], response_class=EventSourceResponse, responses=PROBLEM_RESPONSES
    )
    async def incidents_stream(
        request: Request,
        _p: Annotated[Principal, Read],
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> AsyncIterator[ServerSentEvent]:
        """SSE: `event: incident`, data = one Incident (contracts/incident.schema.json)."""
        async for e in board_stream(request, last_event_id, full_incident, "incident"):
            yield e

    # ---- campaigns / incidents ----------------------------------------------------------------
    @app.get("/v1/campaigns", tags=["campaigns"], response_model=Page, responses=PROBLEM_RESPONSES)
    async def list_campaigns(
        _p: Annotated[Principal, Read], cursor: Cursor = None, limit: Limit = 25
    ) -> dict[str, Any]:
        """Campaign cards (incidents of type campaign / kit_reuse), newest first."""
        cards = [campaign_of(i) for i in await c.sentinel().incidents() if is_campaign(i)]
        return paginate(cards, id_key="campaign_id", cursor=cursor, limit=limit, ts_key="last_seen")

    @app.get("/v1/incidents", tags=["incidents"], response_model=Page, responses=PROBLEM_RESPONSES)
    async def list_incidents(
        _p: Annotated[Principal, Read],
        cursor: Cursor = None,
        limit: Limit = 25,
        status: Annotated[str | None, Query(max_length=32)] = None,
        severity: Annotated[str | None, Query(max_length=16)] = None,
        type: Annotated[str | None, Query(max_length=32)] = None,  # noqa: A002
    ) -> dict[str, Any]:
        """Incidents (contracts/incident.schema.json), newest first, cursor-paginated."""
        rows = [
            i
            for i in await c.sentinel().incidents()
            if status in (None, i.get("status"))
            and severity in (None, i.get("severity"))
            and type in (None, i.get("type"))
        ]
        return paginate(rows, id_key="incident_id", cursor=cursor, limit=limit)

    IncidentId = Annotated[str, Path(pattern=INCIDENT_ID_RE)]
    ActionId = Annotated[str, Path(pattern=ACTION_ID_RE)]

    @app.get("/v1/incidents/{incident_id}", tags=["incidents"], responses=PROBLEM_RESPONSES)
    async def get_incident(incident_id: IncidentId, _p: Annotated[Principal, Read]) -> dict[str, Any]:
        """One incident (contracts/incident.schema.json)."""
        return await c.sentinel().incident(incident_id)

    async def decide(incident_id: str, action_id: str, approve: bool) -> dict[str, Any]:
        out = await c.sentinel().decide(incident_id, action_id, approve)
        return {
            "incident_id": incident_id,
            "action_id": action_id,
            "decision": out.get("decision", "approved" if approve else "rejected"),
        }

    @app.post(
        "/v1/incidents/{incident_id}/actions/{action_id}/approve",
        tags=["operator"],
        response_model=Decision,
        responses=PROBLEM_RESPONSES,
    )
    async def approve_action(
        incident_id: IncidentId, action_id: ActionId, _p: Annotated[Principal, Operator]
    ) -> dict[str, Any]:
        """Approve a held external action (operator scope). The Sentinel never acts on its own."""
        return await decide(incident_id, action_id, True)

    @app.post(
        "/v1/incidents/{incident_id}/actions/{action_id}/reject",
        tags=["operator"],
        response_model=Decision,
        responses=PROBLEM_RESPONSES,
    )
    async def reject_action(
        incident_id: IncidentId, action_id: ActionId, _p: Annotated[Principal, Operator]
    ) -> dict[str, Any]:
        """Reject a held external action (operator scope)."""
        return await decide(incident_id, action_id, False)

    # ---- intel / meta -------------------------------------------------------------------------
    @app.get(
        "/v1/intel/stix",
        tags=["intel"],
        responses={**PROBLEM_RESPONSES, 200: {"content": {STIX_MEDIA: {}}, "description": "STIX 2.1 bundle"}},
    )
    async def intel_stix(
        _p: Annotated[Principal, Intel],
        incident_id: Annotated[str | None, Query(pattern=INCIDENT_ID_RE)] = None,
        status: Annotated[str | None, Query(max_length=32)] = None,
    ) -> Response:
        """STIX 2.1 bundle of defanged indicators for one incident or all (optionally by status)."""
        if incident_id:
            rows = [await c.sentinel().incident(incident_id)]
        else:
            rows = [i for i in await c.sentinel().incidents() if status in (None, i.get("status"))]
        return Response(json.dumps(merge_bundles(rows)), media_type=STIX_MEDIA)

    @app.get("/v1/meta", tags=["meta"], response_model=Meta)
    async def get_meta() -> dict[str, Any]:
        """Public runtime facts for UIs: verdict band thresholds, model ids, sovereign mode, enabled feeds."""
        return meta(c.settings)


def _is_stream_id(v: str) -> bool:
    a, _, b = v.partition("-")
    return a.isdigit() and (b == "" or b.isdigit())
