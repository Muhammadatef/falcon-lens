from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import fakeredis
import httpx
from langgraph.types import RetryPolicy
from sentinel_core.events import parse_event
from sentinel_core.fixtures import generate
from sentinel_core.incidents import Sentinel

from falcon_core.tools.sentinel import ToolContext
from falcon_sentinel.consumer import STREAM, Consumer
from falcon_sentinel.db import IncidentCache, MemoryRepo, Repo
from falcon_sentinel.graph import Deps, TriageRunner
from falcon_sentinel.llm import LLMClient, StubLLM


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={})


@dataclass
class Env:
    redis: Any
    repo: Repo
    cache: IncidentCache
    ctx: ToolContext
    http_log: Recorder
    sentinel: Sentinel
    fx: Any

    def runner(self, llm: LLMClient | None = None, saver: Any = None, **kw: Any) -> TriageRunner:
        from langgraph.checkpoint.memory import InMemorySaver

        deps = Deps(
            llm=llm or StubLLM(),
            tools=self.ctx,
            retry=RetryPolicy(initial_interval=0.01, max_attempts=2, retry_on=(httpx.HTTPError,)),
            **kw,
        )
        return TriageRunner(deps, saver or InMemorySaver())

    def campaign_id(self) -> str:
        return next(i["incident_id"] for i in self.cache.all() if i["type"] == "campaign")


async def make_env(repo: Repo | None = None, redis: Any = None, load: bool = True) -> Env:
    fx = generate()
    repo = repo or MemoryRepo()
    redis = redis or fakeredis.FakeAsyncRedis(decode_responses=True)
    cache = IncidentCache(repo)
    rec = Recorder()
    http = httpx.AsyncClient(transport=httpx.MockTransport(rec.handler))
    ctx = ToolContext(incidents=cache, repo=repo, redis=redis, http=http, alertmanager_url="http://am.test:9093")
    sentinel = Sentinel(cache, vectors=fx.vectors)
    env = Env(redis, repo, cache, ctx, rec, sentinel, fx)
    if load:
        events = [parse_event(e) for e in fx.events]
        await repo.add_features(fx.events)
        sentinel.process(events)
        await cache.flush()
    return env


def make_consumer(env: Env, name: str = "c1", **kw: Any) -> Consumer:
    return Consumer(env.redis, env.repo, env.cache, env.sentinel, name, min_idle_ms=0, **kw)


async def publish(redis: Any, events: list[dict[str, Any]]) -> None:
    for e in events:
        await redis.xadd(STREAM, {"event": json.dumps(e)})
