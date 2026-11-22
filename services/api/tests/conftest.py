from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import fakeredis
import httpx
import pytest
from pydantic import SecretStr

from falcon_api.app import build_app
from falcon_api.jobs import channel, last_key
from falcon_core.config import Settings

SANDBOX_KEY = "test-sandbox-key"


class FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def get(self, verdict_id: str) -> dict[str, Any] | None:
        return self.docs.get(verdict_id)

    async def close(self) -> None:
        return None


def make_doc(verdict_id: str, *, final: bool, verdict: str = "suspicious") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "verdict_id": verdict_id,
        "input_type": "url",
        "verdict": verdict,
        "risk_score": 55,
        "calibrated_probability": 0.5,
        "evidence": [],
        "reasons": [],
        "actions": {
            "now": {"ar": [], "en": []},
            "if_already_acted": {"ar": [], "en": []},
            "report": {"ar": "", "en": ""},
        },
        "tier_reached": "T1" if final else "T0",
        "model_route": "none",
        "degraded": False,
        "final": final,
        "latency_ms": 10,
        "created_at": datetime.now(UTC).isoformat(),
        "screenshot_url": "http://internal/shot.png",
    }


async def publish(redis: Any, doc: dict[str, Any]) -> None:
    raw = json.dumps(doc)
    await redis.set(last_key(doc["verdict_id"]), raw, ex=600)
    await redis.publish(channel(doc["verdict_id"]), raw)


@pytest.fixture
def redis() -> Any:
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


def make_settings(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        fl_sandbox_api_key=SecretStr(SANDBOX_KEY),
        fl_public_base_url="https://app.example.test",
        **kw,
    )


@pytest.fixture
async def client(redis: Any, store: FakeStore) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(make_settings(fl_rate_limit_per_ip_per_min=100), redis=redis, store=store)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
