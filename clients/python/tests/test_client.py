from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from falcon_lens_client import FalconLens, FalconLensError, verify_webhook  # noqa: E402

from falcon_api.webhooks import sign  # noqa: E402


def handler(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/v1/incidents":
        cur = req.url.params.get("cursor")
        return httpx.Response(200, json={"items": [{"incident_id": cur or "a"}], "next_cursor": None if cur else "c1"})
    if req.url.path == "/v1/check/url":
        assert req.headers["x-api-key"] == "k" and json.loads(req.content) == {"url": "http://x.test/"}
        return httpx.Response(202, json={"verdict_id": "vd_x"})
    return httpx.Response(401, json={"type": "urn:t", "title": "Unauthorized", "status": 401})


def test_client_calls_pagination_and_errors() -> None:
    with FalconLens("http://api", "k", transport=httpx.MockTransport(handler)) as fl:
        assert fl.check_url("http://x.test/")["verdict_id"] == "vd_x"
        assert [i["incident_id"] for i in fl.iter_incidents()] == ["a", "c1"]
        with pytest.raises(FalconLensError) as e:
            fl.meta()
        assert e.value.status == 401


def test_verify_webhook_matches_server_signature() -> None:
    body, ts = b"{}", 1_700_000_000
    h = {"X-Falcon-Timestamp": str(ts), "X-Falcon-Signature": sign("s", ts, body)}
    assert verify_webhook("s", h, body, now=ts + 5)
    assert not verify_webhook("s", h, body, now=ts + 400)
    assert not verify_webhook("x", h, body, now=ts)
