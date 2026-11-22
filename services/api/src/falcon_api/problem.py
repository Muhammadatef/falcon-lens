"""RFC 9457 problem+json helpers. Error bodies never echo submitted content."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("falcon.api")
PROBLEM_JSON = "application/problem+json"
TYPE_PREFIX = "urn:falcon-lens:problem:"


class ProblemDetail(BaseModel):
    """RFC 9457 problem details."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, str]] | None = None


class Problem(Exception):  # noqa: N818 - domain name
    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(title)
        self.status, self.slug, self.title = status, slug, title
        self.detail, self.headers, self.errors = detail, headers or {}, errors


def problem_response(request: Request, p: Problem) -> JSONResponse:
    body = ProblemDetail(
        type=TYPE_PREFIX + p.slug,
        title=p.title,
        status=p.status,
        detail=p.detail,
        instance=request.url.path,
        request_id=getattr(request.state, "request_id", None),
        errors=p.errors,
    ).model_dump(exclude_none=True)
    return JSONResponse(body, status_code=p.status, media_type=PROBLEM_JSON, headers=p.headers)


_TITLES = {404: "Not found", 405: "Method not allowed", 401: "Unauthorized", 403: "Forbidden"}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = _TITLES.get(exc.status_code, "HTTP error")
        slug = title.lower().replace(" ", "-") if exc.status_code in _TITLES else "http-error"
        return problem_response(request, Problem(exc.status_code, slug, title))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Only location + error type: never the submitted value.
        errors = [
            {"loc": ".".join(str(x) for x in e.get("loc", ())), "type": str(e.get("type", ""))} for e in exc.errors()
        ]
        return problem_response(request, Problem(422, "invalid-request", "Invalid request", errors=errors))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error: %s", type(exc).__name__)
        return problem_response(request, Problem(500, "internal", "Internal error"))


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ProblemDetail, "description": desc}
    for code, desc in {
        413: "Payload too large",
        415: "Unsupported media type",
        422: "Invalid request",
        429: "Rate limited",
        503: "Dependency unavailable",
    }.items()
}
