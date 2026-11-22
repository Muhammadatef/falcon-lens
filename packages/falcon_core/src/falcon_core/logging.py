"""Compatibility shim: the implementation lives in ``falcon_core.telemetry.logging``."""

from falcon_core.telemetry.logging import (
    JsonFormatter,
    configure_logging,
    incident_id_var,
    sanitize,
    verdict_id_var,
)

__all__ = ["JsonFormatter", "configure_logging", "incident_id_var", "sanitize", "verdict_id_var"]
