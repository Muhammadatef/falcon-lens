"""Wire models for the cascade: the ``fl:jobs`` job and the sandbox ``/render`` response.

``SandboxFeatures`` mirrors the response shape agreed with builder-sandbox (T-009). It ignores
unknown keys so the sandbox can add features without breaking the worker. Everything in it is
attacker-controlled: it is only ever turned into structured evidence, never shown raw.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from falcon_core.cascade.ids import is_verdict_id

Source = Literal["live", "replay", "synthetic", "fixture"]
CHANNELS = ("web", "extension", "api", "mcp", "voice", "hunt")
Channel = Literal["web", "extension", "api", "mcp", "voice", "hunt"]
InputType = Literal["url", "message", "email", "image"]
MAX_URL_BYTES = 4096
MAX_VISIBLE_TEXT = 4096


class CheckJob(BaseModel):
    """One check request read from the ``fl:jobs`` stream (docs/CONTRACTS.md, Internal messages).

    Stream fields (all strings): ``verdict_id``, ``input_type``, ``payload_json``, ``submitted_at``,
    ``source``. For ``url`` the payload is ``{"url", "canonical_sha256"}``; ``canonical_sha256`` is
    the API's keying fingerprint (``vc:``/``sf:``), not the worker's authoritative canonical form.
    """

    model_config = ConfigDict(extra="ignore")

    verdict_id: str
    input_type: InputType = "url"
    payload: dict[str, Any] = Field(default_factory=dict)
    source: Source = "live"
    channel: Channel | None = None
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("verdict_id")
    @classmethod
    def _vid(cls, v: str) -> str:
        if not is_verdict_id(v):
            raise ValueError("verdict_id must be vd_<ULID>")
        return v

    @property
    def url(self) -> str | None:
        v = self.payload.get("url")
        if not isinstance(v, str) or not v or len(v.encode("utf-8", "replace")) > MAX_URL_BYTES:
            return None
        return v

    @property
    def fingerprint(self) -> str | None:
        """The API's fingerprint (``canonical_sha256`` for URLs, ``sha256`` otherwise)."""
        for key in ("canonical_sha256", "sha256"):
            v = self.payload.get(key)
            if isinstance(v, str) and v:
                return v
        return None

    @classmethod
    def from_fields(cls, fields: Mapping[str, str]) -> CheckJob:
        """Parse raw stream fields. Raises ``ValueError`` on a malformed job."""
        raw_payload = fields.get("payload_json") or "{}"
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json is not JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("payload_json must be an object")
        data: dict[str, Any] = {
            "verdict_id": fields.get("verdict_id", ""),
            "input_type": fields.get("input_type", "url"),
            "payload": payload,
            "source": fields.get("source") or "live",
        }
        if fields.get("channel") in CHANNELS:  # unknown values are dropped, never fatal: it is metadata only
            data["channel"] = fields["channel"]
        if fields.get("submitted_at"):
            data["submitted_at"] = fields["submitted_at"]
        return cls.model_validate(data)

    def to_fields(self) -> dict[str, str]:
        """Inverse of ``from_fields`` (used by tests and replay tools)."""
        out = {
            "verdict_id": self.verdict_id,
            "input_type": self.input_type,
            "payload_json": json.dumps(self.payload, separators=(",", ":")),
            "submitted_at": self.submitted_at.isoformat(),
            "source": self.source,
        }
        if self.channel:
            out["channel"] = self.channel
        return out


class SandboxForm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Field descriptors. The sandbox sends strings (type/name/autocomplete hints) or small objects.
    fields: list[str | dict[str, Any]] = Field(default_factory=list)
    action_origin: str | None = None


class SandboxFeatures(BaseModel):
    """Response of sandbox ``POST /render`` (features only, never HTML)."""

    model_config = ConfigDict(extra="ignore")

    redirect_chain: list[str] = Field(default_factory=list)
    final_url: str | None = None
    title: str = ""
    forms: list[SandboxForm] = Field(default_factory=list)
    post_targets: list[str] = Field(default_factory=list)
    # Cross-origin POST targets that carry NO form-field data (telemetry, pixels): informational only.
    beacon_origins: list[str] = Field(default_factory=list)
    # Post origins that count only because of the credential-page rule (basis=credential_page_rule).
    credential_rule_origins: list[str] = Field(default_factory=list)
    hotlinked_origins: list[str] = Field(default_factory=list)
    visible_text: str = ""
    favicon_sha256: str | None = None
    favicon_phash: str | None = None
    screenshot_phash: str | None = None
    dom_simhash: str | None = None
    cloaking: dict[str, Any] = Field(default_factory=dict)
    # Sandbox-classified exfiltration targets: [{"origin", "category"}] (bot API, webhook, relay).
    exfil_targets: list[dict[str, Any]] = Field(default_factory=list)
    # Set by the sandbox when the visit failed (then there is no page to judge).
    error: str | None = None
    # The page WAS judged, but from less than all of it: the main document was cut at the size cap, or the
    # features were read before the page finished loading. Informational only (page.truncated, weight 0).
    truncated: bool = False
    partial: bool = False
    # The browser failed after the target answered HTTP, so the features come from the main document read WITHOUT
    # JavaScript (the sandbox also sets partial=true). Informational only (page.static_fallback, weight 0).
    static_fallback: bool = False

    @field_validator("visible_text")
    @classmethod
    def _cap_text(cls, v: str) -> str:
        return v[:MAX_VISIBLE_TEXT]

    @field_validator("title")
    @classmethod
    def _cap_title(cls, v: str) -> str:
        return v[:512]
