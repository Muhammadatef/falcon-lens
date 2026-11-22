"""Sandbox configuration from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from falcon_core.security import GuardPolicy


def _csv(value: str) -> frozenset[str]:
    return frozenset(v.strip().lower() for v in value.split(",") if v.strip())


@dataclass(frozen=True)
class Settings:
    #: Egress proxy URL for all browser traffic ("" disables, for local dev only).
    proxy: str = ""
    #: Internal fixture hosts exempt from the SSRF name check (bypass the proxy, same network).
    allow_hosts: frozenset[str] = field(default_factory=frozenset)
    snapshot_dir: Path = Path("/data/snapshots")
    api_key: str = ""
    max_concurrent: int = 3
    recycle_after: int = 150

    @property
    def guard(self) -> GuardPolicy:
        return GuardPolicy(allow_hosts=self.allow_hosts)

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ
        allow = (
            ""
            if e.get("FL_ENV") == "production"
            else (e.get("FL_SSRF_ALLOW_HOSTS") or e.get("FL_SANDBOX_ALLOW_HOSTS", ""))
        )
        return cls(
            proxy=e.get("FL_SANDBOX_PROXY", ""),
            allow_hosts=_csv(allow),
            snapshot_dir=Path(e.get("FL_SNAPSHOT_DIR", "/data/snapshots")),
            api_key=e.get("FL_SANDBOX_TOKEN") or e.get("FL_SANDBOX_API_KEY", ""),
            max_concurrent=int(e.get("FL_SANDBOX_CONCURRENCY", "3")),
            recycle_after=int(e.get("FL_SANDBOX_RECYCLE_AFTER", "150")),
        )
