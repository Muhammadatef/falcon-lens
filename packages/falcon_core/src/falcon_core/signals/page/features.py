"""Sandbox page-feature model: FEATURES ONLY, never raw HTML.

This is the response of ``POST /render``. ``extra="forbid"`` everywhere, so a stray raw-HTML field
cannot be added without a deliberate schema change. A JSON Schema is exported with
``RenderFeatures.model_json_schema()`` (proposed to L1 as ``contracts/page_features.schema.json``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProfileName = Literal["mobile_ar", "desktop_en"]
PROFILES: tuple[ProfileName, ...] = ("mobile_ar", "desktop_en")
MAX_VISIBLE_TEXT_BYTES = 4096


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hop(_M):
    url: str = Field(max_length=512)
    status: int | None = None


class FormFeature(_M):
    action_origin: str | None = Field(default=None, description="scheme://host[:port] of form action")
    action_cross_origin: bool = False
    action_exfil: bool = False
    action_exfil_category: str | None = None
    method: str = "get"
    field_kinds: list[str] = Field(default_factory=list)
    sensitive_kinds: list[str] = Field(default_factory=list)
    field_count: int = 0
    cred_form: bool = False


class PostTarget(_M):
    origin: str = Field(max_length=300)
    path: str = Field(default="", max_length=120, description="path only, query stripped")
    kind: Literal["form", "fetch", "xhr", "beacon", "script_literal", "other"]
    source: Literal["static", "dynamic"]
    cross_origin: bool = True
    exfil: bool = False
    exfil_category: str | None = None
    carries_form_data: bool = Field(
        default=False,
        description="the request carries the page's form-field values (or goes to a known relay); "
        "False = telemetry-style beacon with no form data",
    )
    basis: Literal["payload", "relay", "credential_page_rule"] | None = Field(
        default=None,
        description="why it carries form data: payload analysis, a known relay, or ONLY the credential-page rule "
        "(any cross-site script POST on a page with a password/OTP/card/ID input)",
    )


class BlockedRequest(_M):
    host: str = Field(max_length=253)
    reason: str = Field(max_length=40)
    resource_type: str = Field(default="", max_length=20)


class NetworkSummary(_M):
    requests: int = 0
    bytes: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    blocked: list[BlockedRequest] = Field(default_factory=list)
    blocked_total: int = 0
    non_get_sent: int = Field(default=0, description="non-GET/HEAD requests that left the sandbox; must be 0")
    non_get_blocked: int = 0
    size_cap_hit: bool = False
    redirect_limit_hit: bool = False
    # Timing/size of the main document (diagnostics + truncation evidence; numbers only, no content).
    doc_bytes: int = Field(default=0, description="bytes of the main document body kept")
    doc_fetch_ms: int | None = Field(default=None, description="ms to fetch the main document")
    dcl_ms: int | None = Field(default=None, description="ms from visit start to DOMContentLoaded")
    truncated: bool = Field(default=False, description="the main document was cut at the cap (still evidence)")
    partial: bool = Field(default=False, description="extracted before DOMContentLoaded/load finished")
    pending_hosts: list[str] = Field(default_factory=list, description="hosts still loading at the nav deadline")
    attempts: int = Field(
        default=1, description="browser renders tried (2 = one bounded retry after a transient failure)"
    )
    static_fallback: bool = Field(
        default=False,
        description="the browser failed after the target answered HTTP; features come from the main document read "
        "WITHOUT JavaScript (always also partial=true: a half read, never enough to clear a page)",
    )
    static_source: Literal["captured", "fetched"] | None = Field(
        default=None, description="static fallback input: the document the browser already received, or a fresh GET"
    )
    fallback_reason: str | None = Field(default=None, description="the browser error the fallback replaced")


class JsIndicators(_M):
    eval_calls: int = 0
    atob_calls: int = 0
    from_char_code: int = 0
    unescape_calls: int = 0
    function_ctor: int = 0
    hex_escapes: int = 0
    unicode_escapes: int = 0
    long_base64_strings: int = 0
    obfuscated_identifiers: int = 0
    document_write: int = 0
    debugger_statements: int = 0
    contextmenu_block: int = 0
    f12_block: int = 0
    devtools_detect: int = 0
    inline_script_bytes: int = 0
    js_location_assignments: int = 0
    meta_refresh: bool = False


class Favicon(_M):
    origin: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    phash: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")


class ProfileFeatures(_M):
    profile: ProfileName
    requested_url: str = Field(max_length=512)
    final_url: str | None = Field(default=None, max_length=512)
    status: int | None = None
    error: str | None = None
    timed_out: bool = False
    title: str = Field(default="", max_length=300)
    lang: str = Field(default="", max_length=20)
    redirect_chain: list[Hop] = Field(default_factory=list)
    client_navigations: list[str] = Field(default_factory=list, description="main-frame URLs after load")
    forms: list[FormFeature] = Field(default_factory=list)
    script_post_targets: list[PostTarget] = Field(default_factory=list)
    asset_origins: list[str] = Field(default_factory=list, description="third-party asset hosts")
    visible_text: str = Field(default="", description="<= 4 KB, UNTRUSTED: for the quarantined extractor only")
    favicon: Favicon = Field(default_factory=Favicon)
    screenshot_phash: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    screenshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dom_simhash: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    js: JsIndicators = Field(default_factory=JsIndicators)
    network: NetworkSummary = Field(default_factory=NetworkSummary)


class Cloaking(_M):
    diff: bool = False
    reasons: list[str] = Field(default_factory=list)
    simhash_distance: int | None = None
    text_similarity: float | None = None
    inconclusive: bool = Field(default=False, description="comparison skipped: a profile was read partially/cut")


class RenderFeatures(_M):
    url: str = Field(max_length=512)
    profiles: dict[ProfileName, ProfileFeatures]
    cloaking: Cloaking = Field(default_factory=Cloaking)
    elapsed_ms: int = 0
