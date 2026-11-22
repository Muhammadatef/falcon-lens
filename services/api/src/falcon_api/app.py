"""Falcon Lens REST API v1: check endpoints, verdict lookup, SSE."""

import base64
import contextlib
import hmac
import ipaddress
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, File, Path, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.sse import EventSourceResponse, ServerSentEvent
from prometheus_client import Counter
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

from falcon_api.canon import canonicalize_url, sha256_hex
from falcon_api.jobs import Jobs, new_verdict_id, public_doc
from falcon_api.problem import PROBLEM_RESPONSES, Problem, install_handlers, problem_response
from falcon_api.store import PgVerdictStore, StoreUnavailableError, VerdictStore
from falcon_core import __version__
from falcon_core.config import Settings, get_settings
from falcon_core.contracts.verdict import Verdict
from falcon_core.service import create_app

log = logging.getLogger("falcon.api")

MAX_URL_BYTES = 4096
MAX_MESSAGE_BYTES = 8 * 1024
MAX_EMAIL_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_WAIT_S = 8.0
SSE_HEARTBEAT_S = 5.0
SSE_MAX_S = 120.0
_JSON_OVERHEAD = 64 * 1024
BODY_LIMITS = {
    "/v1/check/url": 32 * 1024,
    "/v1/check/message": 64 * 1024,
    "/v1/check/email": MAX_EMAIL_BYTES + _JSON_OVERHEAD,
    "/v1/check/image": MAX_IMAGE_BYTES + _JSON_OVERHEAD,
}
VERDICT_ID_RE = r"^vd_[0-9A-HJKMNP-TV-Z]{26}$"
_IDEM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_REQ_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
SOURCES = {"live", "replay", "synthetic", "fixture"}

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Integration key")


class UrlCheck(BaseModel):
    url: str = Field(min_length=1, description="URL to check (max 4 KB). Never fetched by the API.")


class MessageCheck(BaseModel):
    text: str = Field(min_length=1, description="Message text (max 8 KB UTF-8).")


class Accepted(BaseModel):
    verdict_id: str = Field(pattern=VERDICT_ID_RE)
    events_url: str
    status_url: str


def _accepted(verdict_id: str) -> dict[str, str]:
    return {
        "verdict_id": verdict_id,
        "events_url": f"/v1/verdicts/{verdict_id}/events",
        "status_url": f"/v1/verdicts/{verdict_id}",
    }


def client_ip(request: Request) -> str:
    """Peer address; X-Forwarded-For (last hop) is honoured only from a private/loopback peer."""
    peer = request.client.host if request.client else "unknown"
    try:
        trusted = ipaddress.ip_address(peer).is_private
    except ValueError:
        trusted = False
    if trusted:
        fwd = request.headers.get("x-forwarded-for", "")
        last = fwd.split(",")[-1].strip()
        if last:
            return last
    return peer


def _cors_origins(settings: Settings) -> list[str]:
    origins = [settings.fl_public_base_url.rstrip("/")]
    extra = os.environ.get("FL_CORS_EXTENSION_ORIGINS", "")  # e.g. chrome-extension://<id>
    origins += [o.strip() for o in extra.split(",") if o.strip()]
    return origins


def build_app(
    settings: Settings | None = None,
    *,
    redis: Redis | None = None,
    store: VerdictStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    state: dict[str, Any] = {"redis": redis, "store": store, "jobs": None}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if state["redis"] is None and settings.redis_url:
            state["redis"] = aioredis.from_url(settings.redis_url, decode_responses=True)
        if state["store"] is None and settings.database_url:
            state["store"] = PgVerdictStore(settings.database_url.get_secret_value())
        if state["redis"] is not None:
            state["jobs"] = Jobs(state["redis"], state["store"])
        yield
        if state["store"] is not None:
            await state["store"].close()
        if state["redis"] is not None:
            await state["redis"].aclose()

    deps: dict[str, str] = {}
    if settings.database_url:
        deps["postgres"] = settings.database_url.get_secret_value()
    if settings.redis_url:
        deps["redis"] = settings.redis_url
    app = create_app("api", deps=deps, lifespan=lifespan, title="Falcon Lens API")
    app.version = __version__
    app.description = (
        "REST v1 for Falcon Lens. Verdicts follow contracts/verdict.schema.json. Errors are "
        "RFC 9457 problem+json. Submitted content is never echoed back."
    )
    install_handlers(app)
    if state["redis"] is not None:  # injected (tests): no lifespan needed
        state["jobs"] = Jobs(state["redis"], state["store"])

    registry = app.state.registry
    rate_limited = Counter(
        "fl_rate_limited_total",
        "Requests rejected by the rate limiter",
        ["scope"],
        registry=registry,
    )
    enqueued = Counter("fl_api_jobs_enqueued_total", "Jobs put on fl:jobs", ["input_type"], registry=registry)

    def jobs() -> Jobs:
        j = state["jobs"]
        if j is None:
            raise Problem(503, "queue-unavailable", "Queue unavailable")
        return cast(Jobs, j)

    def authed(key: str | None) -> bool:
        secret = settings.fl_sandbox_api_key
        if secret is None or not key:
            return False
        return hmac.compare_digest(key.encode(), secret.get_secret_value().encode())

    def is_authed(request: Request) -> bool:
        key = request.headers.get("x-api-key")
        bearer = request.headers.get("authorization", "")
        if not key and bearer.lower().startswith("bearer "):
            key = bearer[7:]
        return authed(key)

    # ---- middleware (added last = outermost) ------------------------------------------------
    @app.middleware("http")
    async def guards(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id", "")
        request.state.request_id = rid if _REQ_ID_RE.match(rid) else f"req_{uuid.uuid4().hex[:16]}"
        path = request.url.path
        limit = BODY_LIMITS.get(path)
        if request.method == "POST" and limit is not None:
            length = request.headers.get("content-length")
            if length is None:
                resp: Response = problem_response(request, Problem(411, "length-required", "Content-Length required"))
            elif not length.isdigit() or int(length) > limit:
                resp = problem_response(request, Problem(413, "payload-too-large", "Payload too large"))
            else:
                resp = await _rate_limited_call(request, call_next)
        else:
            resp = await call_next(request)
        resp.headers["X-Request-ID"] = request.state.request_id
        return resp

    async def _rate_limited_call(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        per_min = settings.fl_rate_limit_per_ip_per_min
        r = state["redis"]
        if r is not None and per_min > 0:
            window = int(time.time() // 60)
            key = f"rl:ip:{client_ip(request)}:{window}"
            try:
                count = await r.incr(key)
                if count == 1:
                    await r.expire(key, 70)
            except RedisError:
                count = 0  # fail open on limiter errors; enqueue itself fails closed
                log.warning("rate limiter unavailable")
            if count > per_min:
                rate_limited.labels("ip").inc()
                retry = 60 - int(time.time() % 60)
                return problem_response(
                    request,
                    Problem(
                        429,
                        "rate-limited",
                        "Rate limit exceeded",
                        headers={"Retry-After": str(retry), "X-RateLimit-Limit": str(per_min)},
                    ),
                )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-API-Key", "Authorization"],
        expose_headers=["X-Request-ID", "Retry-After", "Idempotent-Replay"],
        max_age=600,
    )

    # ---- helpers ----------------------------------------------------------------------------
    async def idem_begin(request: Request, body_hash: str) -> tuple[str | None, Response | None]:
        key = request.headers.get("idempotency-key")
        if key is None:
            return None, None
        if not _IDEM_RE.match(key):
            raise Problem(422, "invalid-idempotency-key", "Invalid Idempotency-Key")
        rk = f"idem:{sha256_hex(client_ip(request))[:16]}:{request.url.path}:{key}"
        try:
            raw = await state["redis"].get(rk)
        except RedisError as exc:
            raise Problem(503, "queue-unavailable", "Queue unavailable") from exc
        if raw:
            saved = json.loads(raw)
            if saved["h"] != body_hash:
                raise Problem(422, "idempotency-key-reuse", "Idempotency-Key reused with a different body")
            return rk, JSONResponse(saved["body"], status_code=saved["status"], headers={"Idempotent-Replay": "true"})
        return rk, None

    async def idem_save(rk: str | None, body_hash: str, status: int, body: dict[str, Any]) -> None:
        if rk is not None:
            with contextlib.suppress(RedisError):
                await state["redis"].set(rk, json.dumps({"h": body_hash, "status": status, "body": body}), ex=86400)

    def source_for(request: Request) -> str:
        src = request.headers.get("x-falcon-source", "live")
        return src if src in SOURCES and is_authed(request) else "live"

    async def submit(
        request: Request,
        response: Response,
        wait: float,
        *,
        input_type: str,
        payload: dict[str, Any],
        fingerprint: str,
        blob_b64: str | None = None,
    ) -> Response:
        j = jobs()
        body_hash = fingerprint
        rk, replay = await idem_begin(request, body_hash)
        if replay is not None:
            return replay
        verdict_id, st = await j.enqueue(
            input_type=input_type,
            payload=payload,
            fingerprint=fingerprint,
            source=source_for(request),
            blob_b64=blob_b64,
        )
        if st == "queued":
            enqueued.labels(input_type).inc()
        accepted = _accepted(verdict_id)
        headers = {"Location": accepted["status_url"], "X-Verdict-State": st}
        authenticated = is_authed(request)
        doc = await j.latest(verdict_id) if st == "cached" else None
        if doc is None and wait > 0:
            deadline = time.monotonic() + min(wait, MAX_WAIT_S)
            best: dict[str, Any] | None = None
            async for d in j.watch(verdict_id):
                if d is not None:
                    best = d
                    if d.get("final"):
                        break
                if time.monotonic() >= deadline:
                    break
            doc = best
        if doc is not None:
            await j.note_final(doc)
            status = 200 if doc.get("final") else 202
            return JSONResponse(public_doc(doc, authenticated), status_code=status, headers=headers)
        await idem_save(rk, body_hash, 202, accepted)
        return JSONResponse(accepted, status_code=202, headers=headers)

    WaitQ = Annotated[
        float,
        Query(ge=0, description="Block up to N seconds (capped at 8) for the best verdict so far."),
    ]
    ApiKey = Annotated[str | None, Depends(api_key_header)]
    check_responses: dict[int | str, dict[str, Any]] = {
        **PROBLEM_RESPONSES,
        200: {"model": Verdict, "description": "Final verdict (cache hit or ?wait completed)."},
        202: {"model": Accepted, "description": "Accepted; or best partial verdict when ?wait."},
    }

    # ---- routes -----------------------------------------------------------------------------
    @app.get("/v1/version", tags=["meta"])
    async def version() -> dict[str, str]:
        return {"service": "falcon-api", "api": "v1", "env": settings.fl_env}

    @app.post(
        "/v1/check/url",
        tags=["check"],
        status_code=202,
        responses=check_responses,
        response_model=Accepted,
    )
    async def check_url(
        request: Request,
        response: Response,
        body: UrlCheck,
        _key: ApiKey = None,
        wait: WaitQ = 0,
    ) -> Response:
        if len(body.url.encode()) > MAX_URL_BYTES:
            raise Problem(413, "payload-too-large", "URL longer than 4 KB")
        try:
            canonical = canonicalize_url(body.url)
        except ValueError as exc:
            raise Problem(422, "invalid-url", "Not a checkable http(s) URL") from exc
        fp = sha256_hex("url\0" + canonical)
        return await submit(
            request,
            response,
            wait,
            input_type="url",
            payload={"url": body.url.strip(), "canonical_sha256": fp},
            fingerprint=fp,
        )

    @app.post(
        "/v1/check/message",
        tags=["check"],
        status_code=202,
        responses=check_responses,
        response_model=Accepted,
    )
    async def check_message(
        request: Request,
        response: Response,
        body: MessageCheck,
        _key: ApiKey = None,
        wait: WaitQ = 0,
    ) -> Response:
        raw = body.text.encode()
        if len(raw) > MAX_MESSAGE_BYTES:
            raise Problem(413, "payload-too-large", "Message longer than 8 KB")
        fp = sha256_hex(b"message\0" + raw)
        return await submit(
            request,
            response,
            wait,
            input_type="message",
            payload={"text": body.text, "sha256": fp},
            fingerprint=fp,
        )

    async def read_upload(file: UploadFile, limit: int) -> bytes:
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise Problem(413, "payload-too-large", f"File larger than {limit // (1024 * 1024)} MB")
        if not data:
            raise Problem(422, "empty-file", "Empty file")
        return data

    @app.post(
        "/v1/check/email",
        tags=["check"],
        status_code=202,
        responses=check_responses,
        response_model=Accepted,
    )
    async def check_email(
        request: Request,
        response: Response,
        file: Annotated[UploadFile, File(description=".eml file (max 2 MB)")],
        _key: ApiKey = None,
        wait: WaitQ = 0,
    ) -> Response:
        data = await read_upload(file, MAX_EMAIL_BYTES)
        if not (file.filename or "").lower().endswith(".eml") or not looks_like_eml(data):
            raise Problem(415, "unsupported-media-type", "Expected an RFC 5322 .eml file")
        fp = sha256_hex(b"email\0" + data)
        return await submit(
            request,
            response,
            wait,
            input_type="email",
            payload={"blob_key": "fl:blob:<verdict_id>", "size": len(data), "sha256": fp},
            fingerprint=fp,
            blob_b64=base64.b64encode(data).decode(),
        )

    @app.post(
        "/v1/check/image",
        tags=["check"],
        status_code=202,
        responses=check_responses,
        response_model=Accepted,
    )
    async def check_image(
        request: Request,
        response: Response,
        file: Annotated[UploadFile, File(description="PNG, JPEG or WebP (max 5 MB)")],
        _key: ApiKey = None,
        wait: WaitQ = 0,
    ) -> Response:
        data = await read_upload(file, MAX_IMAGE_BYTES)
        mime = sniff_image(data)
        if mime is None:
            raise Problem(415, "unsupported-media-type", "Expected a PNG, JPEG or WebP image")
        fp = sha256_hex(b"image\0" + data)
        return await submit(
            request,
            response,
            wait,
            input_type="image",
            payload={
                "blob_key": "fl:blob:<verdict_id>",
                "mime": mime,
                "size": len(data),
                "sha256": fp,
            },
            fingerprint=fp,
            blob_b64=base64.b64encode(data).decode(),
        )

    VerdictId = Annotated[str, Path(pattern=VERDICT_ID_RE)]

    @app.get(
        "/v1/verdicts/{verdict_id}",
        tags=["verdicts"],
        responses={
            **PROBLEM_RESPONSES,
            200: {"model": Verdict},
            202: {"model": Verdict, "description": "Not final yet: latest partial verdict."},
            404: {"description": "Unknown verdict id (problem+json)"},
        },
        response_model=Verdict,
    )
    async def get_verdict(request: Request, verdict_id: VerdictId, _key: ApiKey = None) -> Response:
        try:
            doc = await jobs().latest(verdict_id)
        except RedisError as exc:
            raise Problem(503, "queue-unavailable", "Queue unavailable") from exc
        if doc is None:
            raise Problem(404, "verdict-not-found", "Verdict not found")
        await jobs().note_final(doc)
        return JSONResponse(public_doc(doc, is_authed(request)), status_code=200 if doc.get("final") else 202)

    async def known_verdict(verdict_id: VerdictId) -> str:
        try:
            ok = await jobs().known(verdict_id)
        except (RedisError, StoreUnavailableError) as exc:
            raise Problem(503, "queue-unavailable", "Queue unavailable") from exc
        if not ok:
            raise Problem(404, "verdict-not-found", "Verdict not found")
        return verdict_id

    @app.get(
        "/v1/verdicts/{verdict_id}/events",
        tags=["verdicts"],
        response_class=EventSourceResponse,
        responses={**PROBLEM_RESPONSES, 404: {"description": "Unknown verdict id (problem+json)"}},
    )
    async def verdict_events(
        request: Request, verdict_id: Annotated[str, Depends(known_verdict)], _key: ApiKey = None
    ) -> AsyncIterator[ServerSentEvent]:
        """SSE stream of `event: verdict` messages (verdict JSON); closes after `final: true`."""
        authenticated = is_authed(request)
        j = jobs()
        started = last_hb = time.monotonic()
        n = 0
        yield ServerSentEvent(comment="stream open", retry=3000)
        async for doc in j.watch(verdict_id):
            now = time.monotonic()
            if doc is None:
                if now - started > SSE_MAX_S:
                    return
                if now - last_hb >= SSE_HEARTBEAT_S:
                    last_hb = now
                    yield ServerSentEvent(comment="heartbeat")
                continue
            await j.note_final(doc)
            yield ServerSentEvent(data=public_doc(doc, authenticated), event="verdict", id=f"{verdict_id}.{n}")
            n += 1
            last_hb = now

    return app


_EML_FIRST = re.compile(rb"^(From [^\r\n]*|[!-9;-~]{1,64}:[^\r\n]*)\r?\n")
_EML_HDR = re.compile(rb"(?im)^(from|to|subject|received|date|message-id|mime-version):")


def looks_like_eml(data: bytes) -> bool:
    head = data[:16384]
    return b"\x00" not in head and bool(_EML_FIRST.match(head)) and bool(_EML_HDR.search(head))


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


__all__ = ["build_app", "new_verdict_id"]
