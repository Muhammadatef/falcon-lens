"""Sandbox configuration from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from falcon_core.security import GuardPolicy

ALLOWLIST_ENVS = frozenset({"local", "demo", "ci"})


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
    max_concurrent: int = 6
    recycle_after: int = 150

    @property
    def guard(self) -> GuardPolicy:
        return GuardPolicy(allow_hosts=self.allow_hosts)

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ
        # Fail closed: only these environments honour the fixture allow-list; anything else
        # (production, staging, unset, typos) ignores it.
        allow = e.get("FL_SSRF_ALLOW_HOSTS", "") if e.get("FL_ENV") in ALLOWLIST_ENVS else ""
        return cls(
            proxy=e.get("FL_SANDBOX_PROXY", ""),
            allow_hosts=_csv(allow),
            snapshot_dir=Path(e.get("FL_SNAPSHOT_DIR", "/data/snapshots")),
            api_key=e.get("FL_SANDBOX_TOKEN", "").strip(),
            max_concurrent=int(e.get("FL_SANDBOX_CONCURRENCY", "6")),
            recycle_after=int(e.get("FL_SANDBOX_RECYCLE_AFTER", "150")),
        )
