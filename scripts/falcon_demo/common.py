"""Shared plumbing: env, URLs, the API client and the Redis event sink.

What it does:
    Provides the pieces every demo command shares: `load_env` (reads .env, then lets process env override;
    only FL_, OLLAMA, COMPOSE_, REDIS and GRAFANA keys), `Endpoints` (local URLs from the port settings),
    `ApiClient` (calls POST /v1/check/url and /v1/check/message), and two Redis event sinks.

When to use it:
    Only as a library for the other falcon_demo modules; it has no command of its own.

Inputs:
    .env in the repo root and env vars such as FL_GATEWAY_PORT, FL_GRAFANA_PORT, FL_PROMETHEUS_PORT,
    FL_PHOENIX_PORT, FL_SANDBOX_API_KEY and FL_DEMO_REDIS_URL.

Outputs / side effects:
    The client sends HTTP requests to the gateway with header X-Falcon-Source: replay (TLS verification is
    skipped for localhost only). The sinks add entries to the Redis stream `fl:events`: through
    `docker compose exec redis redis-cli` by default, or directly if FL_DEMO_REDIS_URL is set.
    Secret values are never printed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_DIR = REPO_ROOT / "data" / "private"
EVENTS_STREAM = "fl:events"
EVENTS_MAXLEN = 100_000
SOURCE = "replay"  # the only source label this tooling ever sends (docs/OBSERVABILITY.md)
_ENV_PREFIXES = ("FL_", "OLLAMA", "COMPOSE_", "REDIS", "GRAFANA")


def load_env(env_file: Path | None = None, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """`.env` values, overridden by the process environment. Never logs values."""
    out: dict[str, str] = {}
    f = env_file if env_file is not None else REPO_ROOT / ".env"
    if f.is_file():
        for raw in f.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip().strip("'\"")
            out[k.strip()] = v
    src = environ if environ is not None else os.environ
    out.update({k: v for k, v in src.items() if k.startswith(_ENV_PREFIXES)})
    return out


def refang(url: str) -> str:
    """Corpus CSVs store defanged URLs (hxxps://example[.]ae); the API needs the real form."""
    u = url.strip().replace("[.]", ".").replace("[:]", ":")
    if u[:4].lower() == "hxxp":
        u = "http" + u[4:]
    return u


@dataclass(frozen=True)
class Endpoints:
    """Local URLs of the gateway, Grafana, Prometheus and Phoenix, built from the port settings."""

    gateway: str
    grafana: str
    prometheus: str
    phoenix: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Endpoints:
        """Build the endpoints from FL_GATEWAY_PORT, FL_GRAFANA_PORT, FL_PROMETHEUS_PORT, FL_PHOENIX_PORT."""
        gw = env.get("FL_GATEWAY_PORT") or "8443"
        return cls(
            gateway=f"https://localhost:{gw}",
            grafana=f"http://localhost:{env.get('FL_GRAFANA_PORT') or '3001'}",
            prometheus=f"http://localhost:{env.get('FL_PROMETHEUS_PORT') or '9090'}",
            phoenix=f"http://localhost:{env.get('FL_PHOENIX_PORT') or '6006'}",
        )


class ApiError(RuntimeError):
    """The API was unreachable or answered with an error status."""

    pass


class Throttled(ApiError):
    """The API answered 429; carries the Retry-After seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


class ApiClient:
    """Thin sync client for POST /v1/check/{url,message}. Every call carries X-Falcon-Source: replay."""

    def __init__(self, base_url: str, api_key: str | None, *, client: httpx.Client | None = None) -> None:
        local = base_url.startswith(("https://localhost", "https://127.0.0.1"))
        # Local CA gateway (tls internal): skip verification for localhost only.
        self._c = client or httpx.Client(base_url=base_url, timeout=30.0, verify=not local)
        self._key = api_key

    def _headers(self, idem: str | None) -> dict[str, str]:
        h = {"X-Falcon-Source": SOURCE}
        if self._key:
            h["X-API-Key"] = self._key
        if idem:
            h["Idempotency-Key"] = idem[:128]
        return h

    def _post(self, path: str, body: dict[str, Any], idem: str | None, wait: float) -> dict[str, Any]:
        try:
            r = self._c.post(path, json=body, params={"wait": wait} if wait else None, headers=self._headers(idem))
        except httpx.HTTPError as exc:
            raise ApiError(f"API unreachable: {type(exc).__name__}") from exc
        if r.status_code == 429:
            raise Throttled(float(r.headers.get("Retry-After", "5")))
        if r.status_code >= 400:
            raise ApiError(f"HTTP {r.status_code} from {path}")
        doc = r.json()
        return doc if isinstance(doc, dict) else {}

    def check_url(self, url: str, idem: str | None = None, wait: float = 0) -> dict[str, Any]:
        """Submit a URL for checking (POST /v1/check/url); returns the response JSON."""
        return self._post("/v1/check/url", {"url": url}, idem, wait)

    def check_message(self, text: str, idem: str | None = None, wait: float = 0) -> dict[str, Any]:
        """Submit message text for checking (POST /v1/check/message); returns the response JSON."""
        return self._post("/v1/check/message", {"text": text}, idem, wait)

    def healthy(self) -> bool:
        """True if GET /v1/version answers 200."""
        try:
            return self._c.get("/v1/version").status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._c.close()


class EventSink(Protocol):
    """Anything that can publish an event to the Redis stream fl:events."""

    def xadd_event(self, event: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


def xadd_command(event: dict[str, Any]) -> str:
    """One redis-cli line: XADD fl:events MAXLEN ~ N * event "<json>" (contract: field `event`)."""
    payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
    quoted = payload.replace("\\", "\\\\").replace('"', '\\"')
    return f'XADD {EVENTS_STREAM} MAXLEN ~ {EVENTS_MAXLEN} * event "{quoted}"\n'


class ComposeRedisSink:
    """Publishes through `docker compose exec redis redis-cli` (Redis is not published on the host)."""

    def __init__(self, compose: list[str] | None = None) -> None:
        cmd = (compose or ["docker", "compose", "--profile", "core"]) + ["exec", "-T", "redis", "redis-cli"]
        self._p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, cwd=REPO_ROOT
        )

    def xadd_event(self, event: dict[str, Any]) -> None:
        if self._p.stdin is None or self._p.poll() is not None:
            raise ApiError("redis-cli exited: is the stack up? (make up)")
        self._p.stdin.write(xadd_command(event))
        self._p.stdin.flush()

    def close(self) -> None:
        if self._p.stdin:
            self._p.stdin.close()
        self._p.wait(timeout=10)


class UrlRedisSink:
    """Direct connection (FL_DEMO_REDIS_URL host-reachable). Imports redis lazily."""

    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url)

    def xadd_event(self, event: dict[str, Any]) -> None:
        self._r.xadd(
            EVENTS_STREAM,
            {"event": json.dumps(event, sort_keys=True, separators=(",", ":"))},
            maxlen=EVENTS_MAXLEN,
            approximate=True,
        )

    def close(self) -> None:
        self._r.close()


def default_sink(env: Mapping[str, str]) -> EventSink:
    """UrlRedisSink if FL_DEMO_REDIS_URL is set, otherwise ComposeRedisSink."""
    url = env.get("FL_DEMO_REDIS_URL")
    return UrlRedisSink(url) if url else ComposeRedisSink()


Sleep = Callable[[float], None]


def retry_throttled[T](fn: Callable[[], T], sleep: Sleep = time.sleep, attempts: int = 6) -> T:
    """Honour Retry-After on 429 (the API limits per IP per minute)."""
    for i in range(attempts):
        try:
            return fn()
        except Throttled as exc:
            if i == attempts - 1:
                raise
            sleep(min(exc.retry_after, 65.0))
    raise AssertionError("unreachable")  # pragma: no cover
