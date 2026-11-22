"""Structured JSON logging carrying ``verdict_id`` / ``incident_id``.

Every string is sanitised before it is written: control characters (CR, LF, ESC, NUL ...)
and Unicode line separators are escaped, so attacker-controlled text (URLs, message
bodies) cannot forge extra log lines or ANSI sequences (log injection).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

verdict_id_var: ContextVar[str | None] = ContextVar("verdict_id", default=None)
incident_id_var: ContextVar[str | None] = ContextVar("incident_id", default=None)

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
# C0, DEL, C1, line/paragraph separators, bidi overrides (can visually reorder log text).
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
MAX_FIELD = 4000


def _escape(match: re.Match[str]) -> str:
    ch = match.group(0)
    return {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(ch, f"\\u{ord(ch):04x}")


def sanitize(value: str, limit: int = MAX_FIELD) -> str:
    """Escape control characters and cap the length."""
    out = _CONTROL.sub(_escape, value)
    return out if len(out) <= limit else out[:limit] + "...[truncated]"


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, dict):
        return {sanitize(str(k)): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return sanitize(str(value))


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        verdict_id = verdict_id_var.get()
        if verdict_id:
            data["verdict_id"] = verdict_id
        incident_id = incident_id_var.get()
        if incident_id:
            data["incident_id"] = incident_id
        for key, value in record.__dict__.items():  # `extra={"verdict_id": ...}` wins
            if key not in _STANDARD and not key.startswith("_"):
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        # json.dumps escapes C0 controls itself; sanitising first also neutralises
        # separators and bidi controls, which JSON leaves intact.
        return json.dumps(_clean(data), ensure_ascii=False)


def configure_logging(service: str, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
