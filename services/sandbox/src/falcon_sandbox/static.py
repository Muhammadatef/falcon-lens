"""Static fallback: page features from the main document alone, read WITHOUT running any JavaScript.

When the browser render fails (timeout, a page that hangs or crashes the renderer) but the target did answer HTTP,
the document is still evidence. It is either the document the browser's own route handler had already received
(``captured``: same egress proxy, same per-hop SSRF re-validation, same size caps) or, if the browser never got that
far, a fresh bounded GET made through the same egress proxy with every hop re-validated (``fetched``).

The result is a half read by construction: ``network.partial`` and ``network.static_fallback`` are both set, there is
no screenshot, no favicon hash and no script-created DOM. The cascade treats it like a partial read, so it can never
be what clears a page (SCORING section 4), and cloaking comparison against it is inconclusive. Nothing is ever
submitted, typed or executed: the HTML is only tokenised.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from falcon_core.signals.page.features import (
    Favicon,
    Hop,
    NetworkSummary,
    ProfileFeatures,
)
from falcon_core.signals.page.hosts import host_of
from falcon_core.signals.page.simhash import dom_simhash

from .build import (
    apply_credential_page_rule,
    build_forms,
    build_js,
    build_static_post_targets,
    truncate_utf8,
)
from .policy import (
    MAIN_DOC_HARD_BYTES,
    MAIN_DOC_MAX_BYTES,
    MAX_REDIRECTS,
    RequestPolicy,
    classify_fetch_error,
    declared_length,
    proxy_refusal,
)
from .profiles import PROFILES
from .settings import Settings

#: Only this much of the document is tokenised (forms, brand claims and links come early; keeps CPU bounded).
STATIC_PARSE_MAX_BYTES = 1024 * 1024
#: One fresh GET never waits longer than this (it is also bounded by what is left of the visit budget).
STATIC_FETCH_MAX_S = 2.0
#: Do not start a fresh GET with less than this left.
STATIC_FETCH_MIN_S = 0.5
HTML_TYPES = ("text/html", "application/xhtml+xml")
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_SKIP_TEXT = frozenset({"script", "style", "noscript", "template", "head", "title"})
_MAX_TOKENS = 4000
_CHARSET = re.compile(rb"charset\s*=\s*[\"']?([A-Za-z0-9_\-]{2,30})", re.I)
_URL_LITERAL = re.compile(r"https?://[^\s'\"`<>\\)]{4,200}")
_FD = re.compile(r"\.value\b|FormData|serialize|URLSearchParams|passw|\botp\b|\bcvv\b|card|\bpin\b|emirates", re.I)


def _count(pattern: str, text: str, flags: int = 0) -> int:
    return len(re.findall(pattern, text, flags))


def js_indicators(js: str, *, meta_refresh: bool) -> dict[str, Any]:
    """Same counters the in-page script computes, over the inline script text (never executed)."""
    return {
        "eval_calls": _count(r"\beval\s*\(", js),
        "atob_calls": _count(r"\batob\s*\(", js),
        "from_char_code": _count(r"fromCharCode", js),
        "unescape_calls": _count(r"\bunescape\s*\(", js),
        "function_ctor": _count(r"new\s+Function\s*\(", js),
        "hex_escapes": _count(r"\\x[0-9a-fA-F]{2}", js),
        "unicode_escapes": _count(r"\\u[0-9a-fA-F]{4}", js),
        "long_base64_strings": _count(r"[A-Za-z0-9+/]{200,}={0,2}", js),
        "obfuscated_identifiers": _count(r"\b_0x[0-9a-f]{3,}\b", js),
        "document_write": _count(r"document\.write\s*\(", js),
        "debugger_statements": _count(r"\bdebugger\b", js),
        "contextmenu_block": _count(r"contextmenu", js),
        "f12_block": _count(r"keyCode\s*={2,3}\s*123|key\s*={2,3}\s*['\"]F12", js),
        "devtools_detect": _count(r"devtools|outerWidth\s*-\s*innerWidth|console\.clear\s*\(", js, re.I),
        "inline_script_bytes": len(js),
        "js_location_assignments": _count(
            r"(?:window\.|top\.|self\.)?location(?:\.href)?\s*=[^=]|location\.(?:replace|assign)\s*\(", js
        ),
        "meta_refresh": meta_refresh,
    }


@dataclass
class _Form:
    action: str
    method: str
    fields: list[dict[str, Any]] = field(default_factory=list)


class _Extractor(HTMLParser):
    """Collects the same descriptors as ``EXTRACT_JS`` from markup alone."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.title = ""
        self.lang = ""
        self.forms: list[_Form] = []
        self.loose: list[dict[str, Any]] = []
        self.scripts: list[str] = []
        self.struct: list[str] = []
        self.text: list[str] = []
        self.favicon = ""
        self.meta_refresh = False
        self._stack: list[str] = []
        self._form: _Form | None = None
        self._label_for: dict[str, str] = {}
        self._in_title = False
        self._in_script = False
        self._script_buf: list[str] = []
        self._label_buf: list[str] | None = None
        self._label_fields: list[dict[str, Any]] = []
        self._text_len = 0

    def _abs(self, url: str | None) -> str:
        if not url:
            return ""
        try:
            return urljoin(self.base, url.strip())
        except ValueError:
            return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        parent = self._stack[-1] if self._stack else ""
        if len(self.struct) < _MAX_TOKENS:
            self.struct.append(f"{len(self._stack)}:{tag}")
            self.struct.append(f"{parent}>{tag}")
            if tag == "input":
                self.struct.append("input:" + (a.get("type") or "text")[:12].lower())
        if tag == "html" and not self.lang:
            self.lang = a.get("lang", "")[:20]
        elif tag == "base" and a.get("href") and self.base:
            self.base = self._abs(a["href"]) or self.base
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            self.meta_refresh = True
        elif tag == "link" and not self.favicon and "icon" in a.get("rel", "").lower().split():
            self.favicon = self._abs(a.get("href"))
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and not a.get("src"):
            self._in_script = True
            self._script_buf = []
        elif tag == "form" and len(self.forms) < 20:
            self._form = _Form(self._abs(a.get("action")), (a.get("method") or "get")[:10])
        elif tag == "label":
            self._label_buf, self._label_fields = [], []
            if a.get("for"):
                self._label_for[a["for"]] = ""
        elif tag in ("input", "textarea", "select"):
            self._control(tag, a)
        if tag not in _VOID:
            self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def _control(self, tag: str, a: dict[str, str]) -> None:
        kind = "select" if tag == "select" else (a.get("type") or ("textarea" if tag == "textarea" else "text"))
        try:
            maxlength = int(a.get("maxlength") or 0)
        except ValueError:
            maxlength = 0
        desc: dict[str, Any] = {
            "type": kind[:20].lower(),
            "name": a.get("name", "")[:120],
            "id": a.get("id", "")[:120],
            "autocomplete": a.get("autocomplete", "")[:40],
            "placeholder": a.get("placeholder", "")[:120],
            "aria": a.get("aria-label", "")[:120],
            "label": "",
            "inputmode": a.get("inputmode", "")[:20],
            "maxlength": maxlength,
        }
        if self._label_buf is not None:
            self._label_fields.append(desc)
        if self._form is not None:
            if len(self._form.fields) < 60:
                self._form.fields.append(desc)
        elif tag != "select" and len(self.loose) < 60:
            self.loose.append(desc)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_script:
            self._in_script = False
            self.scripts.append("".join(self._script_buf))
        elif tag == "form":
            if self._form is not None:
                self.forms.append(self._form)
            self._form = None
        elif tag == "label" and self._label_buf is not None:
            text = " ".join("".join(self._label_buf).split())[:120]
            for d in self._label_fields:
                d["label"] = text
            self._label_buf = None
        while self._stack and tag not in _VOID:
            if self._stack.pop() == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._in_script:
            if sum(len(s) for s in self._script_buf) < 300_000:
                self._script_buf.append(data)
        elif self._stack and not (set(self._stack) & _SKIP_TEXT) and self._text_len < 20_000:
            self.text.append(data)
            self._text_len += len(data)
        if self._label_buf is not None:
            self._label_buf.append(data)


def decode_html(body: bytes, content_type: str = "") -> str:
    """Bytes to text without ever raising: header charset, then a meta charset, else UTF-8 with replacement."""
    enc = ""
    m = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_\-]{2,30})", content_type, re.I)
    if m:
        enc = m.group(1)
    elif (mm := _CHARSET.search(body[:4096])) is not None:
        enc = mm.group(1).decode("ascii", "ignore")
    for candidate in (enc, "utf-8"):
        if not candidate:
            continue
        with contextlib.suppress(LookupError, UnicodeDecodeError):
            return body.decode(candidate, errors="replace" if candidate == "utf-8" else "strict")
    return body.decode("utf-8", errors="replace")


def extract_static(html: str, base_url: str) -> dict[str, Any]:
    """The raw descriptor dict the browser path builds in-page, from markup only (nothing is executed)."""
    p = _Extractor(base_url)
    with contextlib.suppress(Exception):  # html.parser is lenient; any odd input just ends the read
        p.feed(html)
        p.close()
    forms = [{"action": f.action, "method": f.method, "fields": f.fields} for f in p.forms]
    if p.loose:
        forms.append({"action": "", "method": "get", "fields": p.loose})
    js = "\n".join(p.scripts)[:300_000]
    typed: list[dict[str, Any]] = []
    for pat, kind in (
        (r"""fetch\(\s*(['"`])([^'"`]+)\1\s*,\s*\{[^}]{0,300}method\s*:\s*['"`]POST""", "fetch"),
        (r"""\.open\(\s*['"`]POST['"`]\s*,\s*(['"`])([^'"`]+)\1""", "xhr"),
        (r"""sendBeacon\(\s*(['"`])([^'"`]+)\1""", "beacon"),
    ):
        for m in re.finditer(pat, js, re.I if kind != "beacon" else 0):
            url = urljoin(base_url, m.group(2))
            typed.append({"kind": kind, "url": url, "body": bool(_FD.search(js[m.start() : m.start() + 700]))})
    literals = list(dict.fromkeys(m.group(0) for m in _URL_LITERAL.finditer(js)))[:80]
    return {
        "title": " ".join(p.title.split())[:300],
        "lang": p.lang,
        "forms": forms,
        "js": js_indicators(js, meta_refresh=p.meta_refresh),
        "typed": typed,
        "literals": literals,
        "struct": p.struct,
        "text": " ".join("".join(p.text).split())[:20000],
        "favicon": p.favicon,
    }


@dataclass
class DocCapture:
    """The final main document the browser's route handler received (filled in-flight, even if the visit is later
    cancelled). Only an http(s) document that passed the SSRF policy and was not a proxy refusal is ever stored."""

    body: bytes | None = None
    url: str = ""
    status: int = 0
    content_type: str = ""
    truncated: bool = False
    hops: list[Hop] = field(default_factory=list)
    requests: int = 0
    doc_blocked: bool = False  # a top-level navigation was refused by policy: never read statically


def static_profile_features(
    profile: str,
    requested_url: str,
    *,
    final_url: str,
    status: int,
    body: bytes,
    content_type: str,
    hops: list[Hop],
    source: str,
    fallback_reason: str | None,
    attempts: int,
    truncated: bool,
    requests: int = 1,
) -> ProfileFeatures:
    cut = body[:STATIC_PARSE_MAX_BYTES]
    raw = extract_static(decode_html(cut, content_type), final_url)
    feats = ProfileFeatures(profile=profile, requested_url=requested_url[:512])
    feats.final_url = final_url[:512]
    feats.status = status
    feats.title = str(raw["title"])[:300]
    feats.lang = str(raw["lang"])[:20]
    feats.visible_text = truncate_utf8(str(raw["text"]))
    feats.forms = build_forms(raw["forms"], final_url)
    feats.js = build_js(raw["js"])
    feats.script_post_targets = build_static_post_targets(raw["typed"], raw["literals"], final_url)
    apply_credential_page_rule(feats)
    feats.dom_simhash = dom_simhash(raw["struct"])
    feats.favicon = Favicon()  # nothing is fetched beyond the one document
    feats.redirect_chain = [*hops, Hop(url=final_url[:512], status=status)]
    feats.network = NetworkSummary(
        requests=requests,
        bytes=len(body),
        by_type={"document": requests},
        doc_bytes=len(body),
        truncated=truncated or len(body) > STATIC_PARSE_MAX_BYTES,
        partial=True,
        attempts=attempts,
        static_fallback=True,
        static_source=source,
        fallback_reason=(fallback_reason or "")[:60] or None,
    )
    return feats


def is_html(content_type: str, body: bytes) -> bool:
    ct = content_type.lower().split(";")[0].strip()
    if ct:
        return ct in HTML_TYPES
    head = body[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<title"))


@dataclass
class FetchedDoc:
    body: bytes
    url: str
    status: int
    content_type: str
    truncated: bool
    hops: list[Hop]
    requests: int


class StaticFetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def fetch_main_document(
    settings: Settings, policy: RequestPolicy, url: str, profile: str, budget_s: float
) -> FetchedDoc:
    """One bounded, passive GET chain for the main document: through the egress proxy (except allow-listed fixture
    hosts, as in the browser), no JavaScript, redirects followed by hand so EVERY hop passes the SSRF policy, body
    read in a stream and cut at the size cap. Raises ``StaticFetchError`` with a stable code on any failure."""
    prof = PROFILES[profile]
    headers = {
        "User-Agent": prof["user_agent"],
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "ar-AE,ar;q=0.9,en;q=0.5" if profile == "mobile_ar" else "en-US,en;q=0.9",
    }
    proxied = bool(settings.proxy)
    clients: dict[bool, httpx.AsyncClient] = {}

    def client_for(host: str) -> httpx.AsyncClient:
        via = proxied and host not in settings.allow_hosts
        if via not in clients:
            clients[via] = httpx.AsyncClient(
                proxy=settings.proxy if via else None,
                follow_redirects=False,
                verify=True,
                trust_env=False,
                headers=headers,
                timeout=httpx.Timeout(max(0.3, budget_s)),
            )
        return clients[via]

    hops: list[Hop] = []
    target = url
    requests = 0
    try:
        async with asyncio.timeout(budget_s):
            while True:
                d = policy.decide(target, "GET", "document", len(hops))
                if not d.allow:
                    raise StaticFetchError(f"blocked_by_policy:{d.reason}"[:60])
                host = host_of(target) or ""
                requests += 1
                try:
                    async with client_for(host).stream("GET", target) as resp:
                        declared = declared_length(dict(resp.headers))
                        if declared is not None and declared > MAIN_DOC_HARD_BYTES:
                            raise StaticFetchError("size_cap")
                        location = resp.headers.get("location")
                        if 300 <= resp.status_code < 400 and location:
                            hops.append(Hop(url=target[:512], status=resp.status_code))
                            if len(hops) > MAX_REDIRECTS:
                                raise StaticFetchError("too_many_redirects")
                            target = urljoin(target, location)
                            continue
                        chunks: list[bytes] = []
                        size = 0
                        cut = False
                        async for chunk in resp.aiter_bytes():
                            size += len(chunk)
                            chunks.append(chunk)
                            if size > STATIC_PARSE_MAX_BYTES:
                                cut = True  # enough to judge; the rest is never read
                                break
                        body = b"".join(chunks)[:MAIN_DOC_MAX_BYTES]
                        via = proxied and host not in settings.allow_hosts
                        refusal = proxy_refusal(resp.status_code, dict(resp.headers), len(body), via)
                        if refusal:
                            raise StaticFetchError(refusal)
                        ctype = resp.headers.get("content-type", "")
                        return FetchedDoc(body, target, resp.status_code, ctype, cut, hops, requests)
                except httpx.TimeoutException as exc:
                    raise StaticFetchError("timeout") from exc
                except httpx.HTTPError as exc:
                    raise StaticFetchError(classify_fetch_error(f"{type(exc).__name__} {exc}")) from exc
    except TimeoutError as exc:
        raise StaticFetchError("timeout") from exc
    finally:
        for c in clients.values():
            with contextlib.suppress(Exception):
                await c.aclose()
