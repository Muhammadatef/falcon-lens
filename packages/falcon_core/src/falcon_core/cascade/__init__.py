"""Investigator cascade T0-T3 (ADR-001, docs/SCORING.md)."""

from falcon_core.cascade.assemble import TraceStep, VerdictInvariantError, build_verdict, reissue
from falcon_core.cascade.engine import (
    CallbackSink,
    Cascade,
    CascadeDeps,
    NullCache,
    VerdictCache,
    VerdictSink,
    url_sha256,
)
from falcon_core.cascade.ids import new_event_id, new_verdict_id
from falcon_core.cascade.metrics import CascadeMetrics
from falcon_core.cascade.models import CheckJob, SandboxFeatures, SandboxForm
from falcon_core.cascade.ports import (
    Extractor,
    FeedHit,
    FeedMirror,
    HttpSandboxClient,
    NullFeedMirror,
    SandboxClient,
    SandboxError,
    StubSandboxClient,
)

__all__ = [
    "CallbackSink",
    "Cascade",
    "CascadeDeps",
    "CascadeMetrics",
    "CheckJob",
    "Extractor",
    "FeedHit",
    "FeedMirror",
    "HttpSandboxClient",
    "NullCache",
    "NullFeedMirror",
    "SandboxClient",
    "SandboxError",
    "SandboxFeatures",
    "SandboxForm",
    "StubSandboxClient",
    "TraceStep",
    "VerdictCache",
    "VerdictInvariantError",
    "VerdictSink",
    "build_verdict",
    "new_event_id",
    "new_verdict_id",
    "reissue",
    "url_sha256",
]
