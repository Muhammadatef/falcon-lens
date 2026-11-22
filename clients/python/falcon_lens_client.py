"""Falcon Lens REST v1 client (typed, httpx). Single file: copy it into your project.

    from falcon_lens_client import FalconLens
    with FalconLens("https://localhost:8443", api_key="...") as fl:
        verdict = fl.check_url("hxxp://example[.]test/login", wait=8)

Ready to connect, not connected: this client is generic and implies no integration with any agency.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator, Mapping
from types import TracebackType
from typing import Any, Self

import httpx

REPLAY_WINDOW_S = 300


class FalconLensError(Exception):
    """RFC 9457 problem+json returned by the API."""

    def __init__(self, status: int, title: str, type_: str = "", detail: str | None = None) -> None:
        super().__init__(f"{status} {title}" + (f": {detail}" if detail else ""))
        self.status, self.title, self.type, self.detail = status, title, type_, detail


def _raise(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        p = r.json()
        raise FalconLensError(r.status_code, p.get("title", "error"), p.get("type", ""), p.get("detail"))
    except ValueError:
        raise FalconLensError(r.status_code, r.reason_phrase) from None


def verify_webhook(secret: str, headers: Mapping[str, str], body: bytes, *, now: float | None = None) -> bool:
    """Check `X-Falcon-Signature` (HMAC-SHA256 over `<timestamp>.<body>`) and the 5-minute replay window."""
    low = {k.lower(): v for k, v in headers.items()}
    ts, sig = low.get("x-falcon-timestamp", ""), low.get("x-falcon-signature", "")
    if not ts.isdigit() or abs((now if now is not None else time.time()) - int(ts)) > REPLAY_WINDOW_S:
        return False
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig.encode(), f"v1={mac}".encode())


class FalconLens:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        timeout: float = 20.0,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, verify=verify, transport=transport
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: type[BaseException] | BaseException | TracebackType | None) -> None:
        self._http.close()

    def _json(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        r = self._http.request(method, path, **kw)
        _raise(r)
        out = r.json()
        return out if isinstance(out, dict) else {"result": out}

    # checks (202 = accepted or partial verdict; 200 = final)
    def check_url(self, url: str, *, wait: float = 0, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._json(
            "POST", "/v1/check/url", json={"url": url}, params={"wait": wait}, headers=_idem(idempotency_key)
        )

    def check_message(self, text: str, *, wait: float = 0, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._json(
            "POST", "/v1/check/message", json={"text": text}, params={"wait": wait}, headers=_idem(idempotency_key)
        )

    def check_email(self, eml: bytes, *, wait: float = 0) -> dict[str, Any]:
        return self._json(
            "POST", "/v1/check/email", files={"file": ("message.eml", eml, "message/rfc822")}, params={"wait": wait}
        )

    def get_verdict(self, verdict_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/verdicts/{verdict_id}")

    # intake
    def submit_report(
        self, kind: str, text: str | None = None, *, verdict_id: str | None = None, consent_store_text: bool = False
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"kind": kind, "consent_store_text": consent_store_text}
        if text:
            body["text"] = text
        if verdict_id:
            body["verdict_id"] = verdict_id
        return self._json("POST", "/v1/reports", json=body)

    def submit_feedback(self, verdict_id: str, rating: str, comment: str | None = None) -> dict[str, Any]:
        return self._json("POST", "/v1/feedback", json={"verdict_id": verdict_id, "rating": rating, "comment": comment})

    # read
    def campaigns(self, *, limit: int = 25, cursor: str | None = None) -> dict[str, Any]:
        return self._json("GET", "/v1/campaigns", params=_page(limit, cursor))

    def incidents(self, *, limit: int = 25, cursor: str | None = None, **filters: str) -> dict[str, Any]:
        return self._json("GET", "/v1/incidents", params={**_page(limit, cursor), **filters})

    def incident(self, incident_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/incidents/{incident_id}")

    def iter_incidents(self, **filters: str) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            page = self.incidents(cursor=cursor, **filters)
            yield from page["items"]
            cursor = page["next_cursor"]
            if not cursor:
                return

    def stix(self, incident_id: str | None = None) -> dict[str, Any]:
        return self._json("GET", "/v1/intel/stix", params={"incident_id": incident_id} if incident_id else None)

    def meta(self) -> dict[str, Any]:
        return self._json("GET", "/v1/meta")

    # operator scope
    def approve(self, incident_id: str, action_id: str) -> dict[str, Any]:
        return self._json("POST", f"/v1/incidents/{incident_id}/actions/{action_id}/approve")

    def reject(self, incident_id: str, action_id: str) -> dict[str, Any]:
        return self._json("POST", f"/v1/incidents/{incident_id}/actions/{action_id}/reject")


def _idem(key: str | None) -> dict[str, str] | None:
    return {"Idempotency-Key": key} if key else None


def _page(limit: int, cursor: str | None) -> dict[str, Any]:
    return {"limit": limit, **({"cursor": cursor} if cursor else {})}
