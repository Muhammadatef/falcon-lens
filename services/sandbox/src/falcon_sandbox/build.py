"""Turn the sandbox's raw DOM/network extraction into classified features (pure, testable)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from falcon_core.signals.page.features import (
    MAX_VISIBLE_TEXT_BYTES,
    FormFeature,
    JsIndicators,
    PostTarget,
)
from falcon_core.signals.page.hosts import host_of, same_site

from .classify import SENSITIVE_KINDS, FieldKind, classify_field
from .exfil import classify_post_target


def origin_of(url: str) -> str | None:
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    return f"{p.scheme}://{p.hostname.lower()}{port}"


def path_only(url: str) -> str:
    try:
        return urlsplit(url).path[:120]
    except ValueError:
        return ""


def truncate_utf8(text: str, max_bytes: int = MAX_VISIBLE_TEXT_BYTES) -> str:
    """Collapse whitespace and cut to ``max_bytes`` of UTF-8 without splitting a character."""
    collapsed = " ".join(text.split())
    return collapsed.encode()[:max_bytes].decode("utf-8", errors="ignore")


def build_forms(raw_forms: Iterable[Mapping[str, Any]], page_url: str) -> list[FormFeature]:
    page_host = host_of(page_url)
    out: list[FormFeature] = []
    for raw in raw_forms:
        kinds = [classify_field(f) for f in raw.get("fields", [])]
        visible = [k for k, f in zip(kinds, raw.get("fields", []), strict=True) if f.get("type") != "hidden"]
        sensitive = sorted({k.value for k in visible if k in SENSITIVE_KINDS})
        action = str(raw.get("action") or "")
        action_origin = origin_of(action) if action else None
        cross = bool(action_origin) and not same_site(host_of(action), page_host)
        cls = classify_post_target(action) if action_origin else None
        out.append(
            FormFeature(
                action_origin=action_origin,
                action_cross_origin=cross,
                action_exfil=bool(cls and cls.exfil),
                action_exfil_category=cls.category if cls else None,
                method=str(raw.get("method") or "get").lower()[:10],
                field_kinds=sorted({k.value for k in visible if k is not FieldKind.OTHER}),
                sensitive_kinds=sensitive,
                field_count=len(visible),
                cred_form=bool(sensitive),
            )
        )
    return out


def build_static_post_targets(
    typed: Sequence[Mapping[str, str]], literals: Iterable[str], page_url: str
) -> list[PostTarget]:
    """Targets found by reading inline script text (``typed``: kind+url) plus URL literals that
    match a known exfil channel (``literals``). Literal URLs that are not exfil are ignored."""
    page_host = host_of(page_url)
    seen: set[tuple[str, str, str]] = set()
    out: list[PostTarget] = []

    def add(url: str, kind: str, source: str) -> None:
        origin = origin_of(url)
        if origin is None:
            return
        key = (origin, path_only(url), kind)
        if key in seen:
            return
        seen.add(key)
        cls = classify_post_target(url)
        out.append(
            PostTarget(
                origin=origin,
                path=path_only(url),
                kind=kind,
                source=source,
                cross_origin=not same_site(host_of(url), page_host),
                exfil=cls.exfil,
                exfil_category=cls.category,
            )
        )

    for t in typed:
        add(t["url"], t["kind"], "static")
    for url in literals:
        if classify_post_target(url).exfil:
            add(url, "script_literal", "static")
    return out[:40]


def build_dynamic_post_target(url: str, resource_type: str, page_url: str) -> PostTarget | None:
    origin = origin_of(url)
    if origin is None:
        return None
    kind = {"fetch": "fetch", "xhr": "xhr", "ping": "beacon", "document": "form"}.get(resource_type, "other")
    cls = classify_post_target(url)
    return PostTarget(
        origin=origin,
        path=path_only(url),
        kind=kind,
        source="dynamic",
        cross_origin=not same_site(host_of(url), host_of(page_url)),
        exfil=cls.exfil,
        exfil_category=cls.category,
    )


def build_js(raw: Mapping[str, Any]) -> JsIndicators:
    fields = set(JsIndicators.model_fields)
    return JsIndicators(**{k: v for k, v in raw.items() if k in fields})


def js_obfuscation_indicators(js: JsIndicators) -> list[str]:
    """Names of obfuscation / anti-inspection indicators that fire (thresholds are conservative)."""
    ind: list[str] = []
    if js.eval_calls and (js.atob_calls or js.unescape_calls or js.from_char_code):
        ind.append("eval_of_decoded")
    elif js.eval_calls >= 3:
        ind.append("eval_heavy")
    if js.function_ctor:
        ind.append("function_constructor")
    if js.hex_escapes + js.unicode_escapes >= 30:
        ind.append("escape_density")
    if js.long_base64_strings:
        ind.append("long_base64_blob")
    if js.obfuscated_identifiers >= 5:
        ind.append("obfuscator_identifiers")
    if js.document_write and (js.unescape_calls or js.atob_calls):
        ind.append("document_write_decoded")
    if js.debugger_statements:
        ind.append("anti_debugger")
    if js.contextmenu_block:
        ind.append("block_contextmenu")
    if js.f12_block or js.devtools_detect:
        ind.append("devtools_detection")
    return ind
