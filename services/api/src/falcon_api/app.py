"""Falcon Lens REST API v1: check endpoints, verdict lookup, SSE."""

import asyncio
import base64
import contextlib
import ipaddress
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

import httpx
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

from falcon_api import history, integration, voice
from falcon_api.auth import (
    AuditLog,
    Authenticator,
    KeyStore,
    MemoryAuditLog,
    MemoryKeyStore,
    Principal,
    ip_digest,
    refuse_default_secrets,
)
from falcon_api.auth import StoreUnavailableError as AuthStoreUnavailableError
from falcon_api.canon import canonicalize_url, sha256_hex
from falcon_api.db import Db, MemorySubmissionStore, PgAuditLog, PgKeyStore, PgSubmissionStore, SubmissionStore
from falcon_api.intel import SentinelClient
from falcon_api.jobs import Jobs, new_verdict_id, public_doc
from falcon_api.problem import PROBLEM_RESPONSES, Problem, install_handlers, problem_response
from falcon_api.store import PgVerdictStore, StoreUnavailableError, VerdictStore
from falcon_api.webhooks import Dispatcher, parse_targets
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
SSE_SLOT_TTL_S = 330.0
MAX_STREAMS_PER_KEY = 5
MAX_STREAMS_PER_IP = 3
_JSON_OVERHEAD = 64 * 1024
BODY_LIMITS = {
    "/v1/check/url": 32 * 1024,
    "/v1/check/message": 64 * 1024,
    "/v1/check/email": MAX_EMAIL_BYTES + _JSON_OVERHEAD,
    "/v1/check/image": MAX_IMAGE_BYTES + _JSON_OVERHEAD,
    "/v1/reports": 16 * 1024,
    "/v1/feedback": 4 * 1024,
    "/v1/voice/utterance": 1024 * 1024 + _JSON_OVERHEAD,
}
VERDICT_ID_RE = r"^vd_[0-9A-HJKMNP-TV-Z]{26}$"
_IDEM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_REQ_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
SOURCES = {"live", "replay", "synthetic", "fixture"}

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Integration key (scopes: check, read, operator, intel). `Authorization: Bearer <key>` also works.",
)


ChannelLit = Literal["web", "extension", "api", "mcp", "voice"]
_CHANNEL_DESC = (
    "Optional: which client asks (web, extension, api, mcp, voice). Metadata for History, metrics and the Sentinel; "
    "it never changes the verdict. A repeated identical input answers from the cache with the first channel."
)


class UrlCheck(BaseModel):
    url: str = Field(min_length=1, description="URL to check (max 4 KB). Never fetched by the API.")
    channel: ChannelLit | None = Field(default=None, description=_CHANNEL_DESC)


class MessageCheck(BaseModel):
    text: str = Field(min_length=1, description="Message text (max 8 KB UTF-8).")
    channel: ChannelLit | None = Field(default=None, description=_CHANNEL_DESC)


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


CLIENT_IP_HEADER = "x-falcon-client-ip"


def client_ip(request: Request) -> str:
    """Real caller address.

    The gateway (Caddy) computes the visitor from Cf-Connecting-Ip / trusted proxies and sends it in
    X-Falcon-Client-IP (client-sent copies are overwritten there). That header is honoured only when
    the TCP peer is a private/loopback address (the gateway or web container on the internal network).
    Any other peer is used as-is; X-Forwarded-For and CF headers are never read.
    """
    peer = request.client.host if request.client else "unknown"
    try:
        trusted = ipaddress.ip_address(peer).is_private
    except ValueError:
        trusted = False
    if trusted:
        raw = request.headers.get(CLIENT_IP_HEADER, "").strip()
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            pass
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
    keystore: KeyStore | None = None,
    audit: AuditLog | None = None,
    submissions: SubmissionStore | None = None,
    sentinel: SentinelClient | None = None,
    webhook_transport: httpx.AsyncBaseTransport | None = None,
    stt_router: voice.SttRouter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    state: dict[str, Any] = {
        "redis": redis,
        "store": store,
        "jobs": None,
        "keystore": keystore,
        "audit": audit,
        "submissions": submissions,
        "sentinel": sentinel,
        "auth": None,
        "ready": False,
        "db": None,
        "webhook_task": None,
    }
    pepper = settings.fl_api_key_pepper.get_secret_value() if settings.fl_api_key_pepper else None
    refuse_default_secrets(
        settings.fl_env,
        {
            "FL_API_KEY_PEPPER": pepper,
            "FL_OPERATOR_KEY": settings.fl_operator_key.get_secret_value() if settings.fl_operator_key else None,
            "FL_WEBHOOK_SECRET": settings.fl_webhook_secret.get_secret_value() if settings.fl_webhook_secret else None,
            "FL_MCP_SERVICE_KEY": os.environ.get("FL_MCP_SERVICE_KEY"),
        },
    )

    def secret(v: Any) -> str | None:
        return v.get_secret_value() if v is not None else None

    if settings.database_url and (keystore is None or audit is None or submissions is None):
        state["db"] = Db(settings.database_url.get_secret_value())
    db0: Db | None = state["db"]
    if state["keystore"] is None:
        state["keystore"] = PgKeyStore(db0) if db0 else MemoryKeyStore()
    if state["audit"] is None:
        state["audit"] = PgAuditLog(db0) if db0 else MemoryAuditLog()
    if state["submissions"] is None:
        state["submissions"] = PgSubmissionStore(db0) if db0 else MemorySubmissionStore()

    async def ensure_auth() -> Authenticator | None:
        """Build the authenticator and seed configured keys once (works with and without lifespan)."""
        if state["ready"]:
            return cast("Authenticator | None", state["auth"])
        async with state_lock:
            if state["ready"]:
                return cast("Authenticator | None", state["auth"])
            if state["db"] is not None:
                await state["db"].init()
            if pepper is None:
                log.warning("FL_API_KEY_PEPPER unset: API keys disabled")
                state["ready"] = True
                return None
            await state["keystore"].init()
            auth = Authenticator(state["keystore"], pepper)
            seeds = [
                ("sandbox", secret(settings.fl_sandbox_api_key), ["check"], 30, "public sandbox key (check only)"),
                (
                    "operator",
                    secret(settings.fl_operator_key),
                    ["read", "operator"],
                    120,
                    "operator (read + approve/reject)",
                ),
                ("mcp-service", os.environ.get("FL_MCP_SERVICE_KEY"), ["check", "read"], 120, "MCP service key"),
            ]
            for key_id, key, scopes, rate, label in seeds:
                if key:
                    await auth.seed(key_id, key, scopes, rate, label)
            state["auth"] = auth
            state["ready"] = True
            return auth

    state_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if state["redis"] is None and settings.redis_url:
            state["redis"] = aioredis.from_url(settings.redis_url, decode_responses=True, max_connections=64)
        if state["store"] is None and settings.database_url:
            state["store"] = PgVerdictStore(settings.database_url.get_secret_value())
        if state["redis"] is not None:
            state["jobs"] = Jobs(state["redis"], state["store"])
        try:
            await ensure_auth()
        except AuthStoreUnavailableError:
            log.warning("key store unavailable at startup; will retry on first request")
        targets = parse_targets(os.environ.get("FL_WEBHOOK_TARGETS"))
        wh_secret = secret(settings.fl_webhook_secret)
        if targets and wh_secret and state["redis"] is not None:
            disp = Dispatcher(
                state["redis"], targets, wh_secret, app.state.registry,
                transport=webhook_transport, card_loader=load_card,
            )  # fmt: skip
            state["webhook_task"] = asyncio.create_task(disp.run())
        yield
        if state["webhook_task"] is not None:
            state["webhook_task"].cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state["webhook_task"]
        if state["sentinel"] is not None:
            await state["sentinel"].close()
        if state["db"] is not None:
            await state["db"].close()
        if state["store"] is not None:
            await state["store"].close()
        if state["redis"] is not None:
            await state["redis"].aclose()

    async def load_card(card: dict[str, Any]) -> dict[str, Any]:
        """Webhook payload: the campaign projection of the incident behind a board card."""
        from falcon_api.intel import campaign_of

        try:
            return campaign_of(await get_sentinel().incident(str(card["incident_id"])))
        except (Problem, KeyError):
            return card

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

    def presented_key(request: Request) -> str | None:
        key = request.headers.get("x-api-key")
        bearer = request.headers.get("authorization", "")
        if not key and bearer.lower().startswith("bearer "):
            key = bearer[7:].strip()
        return key or None

    def principal_of(request: Request) -> Principal | None:
        p = getattr(request.state, "principal", None)
        return p if isinstance(p, Principal) else None

    def is_authed(request: Request) -> bool:
        return principal_of(request) is not None

    # ---- concurrent SSE caps (in-process; one API replica) -----------------------------------
    slots: dict[str, dict[str, float]] = {}
    app.state.stream_slots = slots  # exposed for tests and diagnostics

    def slot_bucket(request: Request) -> tuple[str, int]:
        p = principal_of(request)
        return (f"key:{p.key_id}", MAX_STREAMS_PER_KEY) if p else (f"ip:{client_ip(request)}", MAX_STREAMS_PER_IP)

    def stream_acquire(request: Request) -> None:
        bucket, cap = slot_bucket(request)
        now = time.monotonic()
        held = slots.setdefault(bucket, {})
        for tok, exp in list(held.items()):  # a slot whose stream never started expires on its own
            if exp < now:
                del held[tok]
        if len(held) >= cap:
            rate_limited.labels("stream").inc()
            raise Problem(
                429,
                "too-many-streams",
                "Too many concurrent streams",
                headers={"Retry-After": "5", "X-RateLimit-Limit": str(cap)},
            )
        tok = uuid.uuid4().hex
        held[tok] = now + SSE_SLOT_TTL_S
        request.state.stream_slot = (bucket, tok)

    def stream_release(request: Request) -> None:
        slot = getattr(request.state, "stream_slot", None)
        if slot:
            slots.get(slot[0], {}).pop(slot[1], None)
            request.state.stream_slot = None

    def stream_gate(request: Request) -> None:
        stream_acquire(request)

    def get_sentinel() -> SentinelClient:
        if state["sentinel"] is None:
            base = os.environ.get("FL_SENTINEL_URL", "http://sentinel:8000")
            state["sentinel"] = SentinelClient(base, secret(settings.fl_operator_key))
        return cast(SentinelClient, state["sentinel"])

    def get_submissions() -> SubmissionStore:
        return cast(SubmissionStore, state["submissions"])

    def require(scope: str) -> Callable[..., Awaitable[Principal]]:
        async def dep(request: Request, _key: Annotated[str | None, Depends(api_key_header)] = None) -> Principal:
            p = principal_of(request)
            if p is None:
                raise Problem(
                    401, "unauthorized", "API key required", headers={"WWW-Authenticate": 'Bearer realm="falcon-lens"'}
                )
            if scope not in p.scopes:
                raise Problem(403, "forbidden", "Key lacks the required scope", detail=f"required scope: {scope}")
            return p

        return dep

    LIMITED_ANON = frozenset(BODY_LIMITS)

    async def audit_call(request: Request, status: int, principal: Principal | None, note: str | None = None) -> None:
        sink: AuditLog | None = state["audit"]
        if sink is None:
            return
        entry = {
            "at": datetime.now(UTC),
            "key_id": principal.key_id if principal else None,
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "request_id": request.state.request_id,
            "ip_digest": ip_digest(pepper or "", client_ip(request)),
            "note": note,
        }
        try:
            await sink.append(entry)
        except Exception:  # noqa: BLE001 - auditing must never take the API down, but it must be loud
            log.error("audit append failed")

    def rate_response(request: Request, limit: int, scope: str) -> Response:
        rate_limited.labels(scope).inc()
        retry = 60 - int(time.time() % 60)
        return problem_response(
            request,
            Problem(
                429,
                "rate-limited",
                "Rate limit exceeded",
                headers={"Retry-After": str(retry), "X-RateLimit-Limit": str(limit)},
            ),
        )

    async def count(key: str) -> int:
        r = state["redis"]
        if r is None:
            return 0
        try:
            n = int(await r.incr(key))
            if n == 1:
                await r.expire(key, 70)
        except RedisError:
            log.warning("rate limiter unavailable")  # fail open on limiter errors; enqueue itself fails closed
            return 0
        return n

    # ---- middleware (added last = outermost) ------------------------------------------------
    @app.middleware("http")
    async def guards(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id", "")
        request.state.request_id = rid if _REQ_ID_RE.match(rid) else f"req_{uuid.uuid4().hex[:16]}"
        request.state.principal = None
        path = request.url.path
        principal: Principal | None = None
        resp: Response | None = None
        key = presented_key(request) if path.startswith("/v1/") else None
        if key:
            try:
                auth = await ensure_auth()
                principal = await auth.authenticate(key) if auth else None
            except AuthStoreUnavailableError:
                resp = problem_response(request, Problem(503, "auth-unavailable", "Key store unavailable"))
            else:
                if principal is None and await count(f"rl:badkey:{client_ip(request)}:{int(time.time() // 60)}") > 10:
                    resp = rate_response(request, 10, "badkey")
                elif principal is None:
                    resp = problem_response(
                        request,
                        Problem(401, "unauthorized", "Invalid API key", headers={"WWW-Authenticate": "Bearer"}),
                    )
                    await audit_call(request, 401, None, "invalid key")
        request.state.principal = principal
        if resp is None:
            resp = await _guarded(request, call_next, principal)
        resp.headers["X-Request-ID"] = request.state.request_id
        if principal is not None:
            await audit_call(request, resp.status_code, principal)
        return resp

    async def _guarded(
        request: Request, call_next: Callable[[Request], Awaitable[Response]], p: Principal | None
    ) -> Response:
        path = request.url.path
        limit = BODY_LIMITS.get(path)
        if request.method == "POST" and limit is not None:
            length = request.headers.get("content-length")
            if length is None:
                return problem_response(request, Problem(411, "length-required", "Content-Length required"))
            if not length.isdigit() or int(length) > limit:
                return problem_response(request, Problem(413, "payload-too-large", "Payload too large"))
        if p is not None and path.startswith("/v1/"):
            if request.method == "POST" and path.startswith("/v1/check/") and "check" not in p.scopes:
                return problem_response(request, Problem(403, "forbidden", "Key lacks the required scope"))
            if (
                p.rate_limit_per_min > 0
                and await count(f"rl:key:{p.key_id}:{int(time.time() // 60)}") > p.rate_limit_per_min
            ):
                return rate_response(request, p.rate_limit_per_min, "key")
        elif request.method == "POST" and path in LIMITED_ANON:
            per_min = settings.fl_rate_limit_per_ip_per_min
            if per_min > 0 and await count(f"rl:ip:{client_ip(request)}:{int(time.time() // 60)}") > per_min:
                return rate_response(request, per_min, "ip")
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
        channel: str | None = None,
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
            channel=channel,
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
            channel=body.channel,
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
            channel=body.channel,
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

    # Registered before `/v1/verdicts/{verdict_id}` so that `/v1/verdicts/stream` is not read as an id.
    history.register(
        app,
        get_redis=lambda: cast("Redis | None", state["redis"]),
        get_jobs=jobs,
        require=require,
        stream_acquire=stream_acquire,
        stream_release=stream_release,
        count=count,
        client_ip=client_ip,
    )

    voice.register(
        app,
        require=require,
        count=count,
        client_ip=client_ip,
        registry=registry,
        router_factory=(lambda: stt_router) if stt_router else None,
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
        request: Request,
        verdict_id: Annotated[str, Depends(known_verdict)],
        _gate: Annotated[None, Depends(stream_gate)],
        _key: ApiKey = None,
    ) -> AsyncIterator[ServerSentEvent]:
        """SSE stream of `event: verdict` messages (verdict JSON); closes after `final: true`."""
        try:
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
        finally:
            stream_release(request)

    async def verdict_known(verdict_id: str) -> bool:
        try:
            return bool(await jobs().known(verdict_id))
        except (RedisError, StoreUnavailableError) as exc:
            raise Problem(503, "queue-unavailable", "Queue unavailable") from exc

    integration.register(
        app,
        integration.Ctx(
            settings=settings,
            state=state,
            submissions=get_submissions,
            sentinel=get_sentinel,
            require=require,
            idem_begin=idem_begin,
            idem_save=idem_save,
            source_for=source_for,
            known_verdict=verdict_known,
            stream_acquire=stream_acquire,
            stream_release=stream_release,
        ),
    )
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
