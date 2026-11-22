# ruff: noqa: E501
"""Email pipeline (deterministic): safe .eml parsing and header / link / attachment checks.

Safety: stdlib ``email`` with ``policy.default``; 2 MB cap before parsing; at most MAX_PARTS parts; no remote
content is ever fetched (HTML is parsed, never rendered; <img src> / <link> are ignored); attachments are
typed by magic bytes and hashed with sha256, never opened, decompressed or executed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Any

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.brands.registry import BrandRegistry, default_registry
from falcon_core.signals.image.analyze import analyze_image, sniff
from falcon_core.signals.message.analyze import analyze_message
from falcon_core.signals.message.extract import ChildInput, extract_urls
from falcon_core.signals.url.canonical import canonicalize, psl_split
from falcon_core.signals.url.textutil import compact, defang

MAX_EMAIL_BYTES = 2 * 1024 * 1024
MAX_PARTS = 50
MAX_BODY_CHARS = 200_000
MAX_LINKS = 50
MAX_ATTACHMENT_EVIDENCE = 10

SPEC = SignalSpec(
    name="email.analyze",
    family="email",
    tier="T1",
    input_types=("email",),
    timeout_ms=1500,
    network="none",
    emits=(
        "email.invalid",
        "email.auth_fail",
        "email.display_name_impersonation",
        "email.reply_to_mismatch",
        "email.return_path_mismatch",
        "email.link_text_mismatch",
        "email.attachment",
    ),
)

_AUTH = re.compile(r"\b(spf|dkim|dmarc|arc)\s*=\s*(fail|softfail|permerror|temperror)\b", re.I)
_SPF_HDR = re.compile(r"^\s*(fail|softfail|permerror)\b", re.I)
_RISKY_EXT = frozenset(
    [
        "exe",
        "scr",
        "bat",
        "cmd",
        "com",
        "js",
        "jse",
        "vbs",
        "vbe",
        "wsf",
        "ps1",
        "msi",
        "jar",
        "lnk",
        "hta",
        "iso",
        "img",
        "apk",
        "dll",
        "docm",
        "xlsm",
        "html",
        "htm",
        "svg",
    ]
)


@dataclass
class EmailAnalysis:
    evidence: list[Evidence] = field(default_factory=list)
    children: list[ChildInput] = field(default_factory=list)
    body_text: str = ""


class _Html(HTMLParser):
    """Text and <a href> collector. Never renders, never fetches."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, visible text)
        self._skip = 0
        self._href: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href") or None
            self._buf = []
        elif tag in ("br", "p", "div", "tr", "li"):
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            if len(self.links) < MAX_LINKS * 2:
                self.links.append((self._href.strip(), " ".join("".join(self._buf).split())))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.text.append(data)
        if self._href is not None:
            self._buf.append(data)


def _registrable(host_or_url: str) -> str | None:
    c = canonicalize(host_or_url)
    if not c.ok or not c.host:
        return None
    _s, dom, suf, _p = psl_split(c.host)
    return f"{dom}.{suf}".lower() if suf else c.host.lower()


def _addr(msg: EmailMessage, name: str) -> tuple[str, str]:
    """(display_name, addr_spec) of the first address in header ``name``; never raises."""
    try:
        hdr = msg[name]
        if hdr is None:
            return "", ""
        addrs = getattr(hdr, "addresses", ())
        if addrs:
            a = addrs[0]
            return str(a.display_name or ""), str(a.addr_spec or "").lower()
        s = str(hdr)
        m = re.search(r"[\w.+-]+@[\w.-]+", s)
        return "", (m.group(0).lower() if m else "")
    except Exception:  # noqa: BLE001 - malformed headers must not break analysis
        return "", ""


def _domain_of(addr: str) -> str | None:
    return _registrable(addr.rsplit("@", 1)[1]) if "@" in addr else None


def _decode_text(part: EmailMessage) -> str:
    raw = part.get_payload(decode=True)
    if not isinstance(raw, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw[: MAX_BODY_CHARS * 4].decode(charset, "replace")[:MAX_BODY_CHARS]
    except LookupError:
        return raw[: MAX_BODY_CHARS * 4].decode("utf-8", "replace")[:MAX_BODY_CHARS]


def sniff_attachment(data: bytes) -> str:
    """Coarse file type from magic bytes (the bytes are never parsed further)."""
    if (t := sniff(data)) is not None:
        return t
    head = data[:8]
    table = (
        (b"%PDF-", "pdf"),
        (b"PK\x03\x04", "zip"),
        (b"PK\x05\x06", "zip"),
        (b"MZ", "exe"),
        (b"\x7fELF", "elf"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole2"),
        (b"Rar!\x1a\x07", "rar"),
        (b"7z\xbc\xaf\x27\x1c", "7z"),
        (b"\x1f\x8b", "gzip"),
        (b"{\\rtf", "rtf"),
        (b"L\x00\x00\x00\x01\x14\x02\x00", "lnk"),
    )
    for magic, name in table:
        if head.startswith(magic) or data.startswith(magic):
            return name
    low = data[:512].lstrip().lower()
    if low.startswith((b"<!doctype html", b"<html", b"<script", b"<svg")):
        return "html"
    if data and all(b in b"\t\n\r" or 32 <= b < 127 or b >= 128 for b in data[:512]):
        return "text"
    return "unknown"


def _safe_name(name: str | None) -> str:
    n = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(c for c in n if c.isprintable())[:80]


def _invalid(reason: str) -> Evidence:
    return Evidence(
        signal="email.invalid",
        family="email",
        polarity="neutral",
        observed={"reason": reason},
        display={"en": "Email could not be processed safely", "ar": "تعذرت معالجة البريد بأمان"},
    )


def _auth_evidence(msg: EmailMessage) -> Evidence | None:
    fails: set[str] = set()
    for h in ("Authentication-Results", "ARC-Authentication-Results"):
        for v in msg.get_all(h, []):
            for am in _AUTH.finditer(str(v)):
                fails.add(f"{am.group(1).lower()}={am.group(2).lower()}")
    for v in msg.get_all("Received-SPF", []):
        if sm := _SPF_HDR.match(str(v)):
            fails.add(f"spf={sm.group(1).lower()}")
    if not fails:
        return None
    return Evidence(
        signal="email.auth_fail",
        family="email",
        observed={
            "failures": sorted(fails),
            "dkim_signature_present": msg["DKIM-Signature"] is not None,
        },
        display={
            "en": "Sender authentication failed (SPF/DKIM/DMARC)",
            "ar": "فشل التحقق من هوية المرسل",
        },
    )


def _impersonation(display: str, sender_domain: str | None, reg: BrandRegistry) -> Evidence | None:
    if not display:
        return None
    comp = compact(display)
    hit = []
    for b in reg.brands:
        named = any(t in comp for t in b.tokens_en if len(t) >= 4) or any(
            t in comp for t in b.tokens_ar
        )
        if named and not (
            sender_domain
            and reg.is_official(sender_domain)
            and reg.official_brand(sender_domain) is b
        ):
            hit.append(b.brand_id)
    if not hit:
        return None
    return Evidence(
        signal="email.display_name_impersonation",
        family="email",
        observed={
            "brands": hit[:5],
            "sender_domain": defang(sender_domain) if sender_domain else None,
        },
        display={
            "en": "Sender name claims a brand the address does not belong to",
            "ar": "اسم المرسل يدّعي جهة لا يتبع لها العنوان",
        },
    )


def _link_mismatches(links: list[tuple[str, str]]) -> tuple[list[dict[str, str]], list[ChildInput]]:
    bad: list[dict[str, str]] = []
    kids: list[ChildInput] = []
    for href, text in links:
        if not href.lower().startswith(("http://", "https://")):
            continue
        kids.append(ChildInput("url", href[:2048], None, "email.href"))
        shown = extract_urls(text)
        if not shown:
            continue
        a, b = _registrable(shown[0].value), _registrable(href)
        if a and b and a != b:
            bad.append({"text_domain": defang(a), "href_domain": defang(b)})
    return bad, kids


def analyze_email(data: bytes, reg: BrandRegistry | None = None) -> EmailAnalysis:
    reg = reg or default_registry()
    res = EmailAnalysis()
    if len(data) > MAX_EMAIL_BYTES:
        res.evidence.append(_invalid("too_large"))
        return res
    try:
        msg = message_from_bytes(data, policy=policy.default)
        if not isinstance(msg, EmailMessage):
            res.evidence.append(_invalid("parse_error"))
            return res
        parts: list[EmailMessage] = []
        for p in msg.walk():
            parts.append(p)
            if len(parts) > MAX_PARTS:
                res.evidence.append(_invalid("too_many_parts"))
                return res
    except Exception as exc:  # noqa: BLE001 - includes RecursionError on nested multiparts
        res.evidence.append(_invalid(f"parse_error:{type(exc).__name__}"))
        return res

    if (ev := _auth_evidence(msg)) is not None:
        res.evidence.append(ev)
    disp, from_addr = _addr(msg, "From")
    from_dom = _domain_of(from_addr)
    if (ev := _impersonation(disp, from_dom, reg)) is not None:
        res.evidence.append(ev)
    _rd, reply_addr = _addr(msg, "Reply-To")
    if (rd := _domain_of(reply_addr)) and from_dom and rd != from_dom:
        res.evidence.append(
            Evidence(
                signal="email.reply_to_mismatch",
                family="email",
                observed={"from_domain": defang(from_dom), "reply_to_domain": defang(rd)},
                display={
                    "en": "Replies go to a different domain than the sender",
                    "ar": "الردود تذهب إلى نطاق مختلف عن المرسل",
                },
            )
        )
    rp = (
        str(msg["Return-Path"] or "").strip("<> ").lower() if msg["Return-Path"] is not None else ""
    )
    if (rpd := _domain_of(rp)) and from_dom and rpd != from_dom:
        res.evidence.append(
            Evidence(
                signal="email.return_path_mismatch",
                family="email",
                polarity="neutral",
                observed={"from_domain": defang(from_dom), "return_path_domain": defang(rpd)},
                display={
                    "en": "Return-Path domain differs from sender",
                    "ar": "نطاق Return-Path يختلف عن المرسل",
                },
            )
        )

    plain = html_text = ""
    links: list[tuple[str, str]] = []
    n_att = 0
    for p in parts:
        if p.is_multipart():
            continue
        ctype = p.get_content_type()
        fname = p.get_filename()
        is_att = (
            p.get_content_disposition() == "attachment"
            or fname is not None
            or not ctype.startswith("text/")
        )
        if not is_att and ctype == "text/plain":
            plain += _decode_text(p) + "\n"
        elif not is_att and ctype == "text/html":
            parser = _Html()
            try:
                parser.feed(_decode_text(p))
                parser.close()
            except Exception:  # noqa: BLE001, S110 - broken HTML: keep what was collected
                pass
            html_text += "".join(parser.text) + "\n"
            links += parser.links
        else:
            payload = p.get_payload(decode=True)
            blob = payload if isinstance(payload, bytes) else b""
            kind = sniff_attachment(blob)
            name = _safe_name(fname)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            double_ext = name.count(".") >= 2 and ext in _RISKY_EXT
            n_att += 1
            if n_att <= MAX_ATTACHMENT_EVIDENCE:
                res.evidence.append(
                    Evidence(
                        signal="email.attachment",
                        family="email",
                        polarity="neutral",
                        observed={
                            "name": name,
                            "declared_type": ctype,
                            "detected_type": kind,
                            "size": len(blob),
                            "sha256": hashlib.sha256(blob).hexdigest(),
                            "risky": kind in ("exe", "elf", "lnk", "html", "ole2")
                            or ext in _RISKY_EXT
                            or double_ext,
                            "double_extension": double_ext,
                        },
                        display={
                            "en": "Attachment (type checked, not opened)",
                            "ar": "مرفق (تم فحص نوعه دون فتحه)",
                        },
                    )
                )
            if kind in ("png", "jpeg", "webp", "gif"):
                ia = analyze_image(blob)
                res.evidence += ia.evidence
                res.children += [
                    ChildInput(c.kind, c.value, None, "email.attachment_qr") for c in ia.children
                ]

    bad, kids = _link_mismatches(links)
    res.children += kids
    if bad:
        res.evidence.append(
            Evidence(
                signal="email.link_text_mismatch",
                family="email",
                observed={"mismatches": bad[:5], "count": len(bad)},
                display={
                    "en": "A link shows one address but goes to another",
                    "ar": "رابط يعرض عنوانا لكنه يؤدي إلى عنوان آخر",
                },
            )
        )

    res.body_text = (plain if plain.strip() else html_text)[:8192]
    subject = str(msg["Subject"] or "") if msg["Subject"] is not None else ""
    ma = analyze_message((subject + "\n" + res.body_text)[:8192], reg)
    res.evidence += ma.evidence
    res.children += [ChildInput(c.kind, c.value, None, "email.body") for c in ma.children]
    # de-duplicate children
    seen: set[tuple[str, str]] = set()
    uniq = []
    for c in res.children:
        if (c.kind, c.value) not in seen:
            seen.add((c.kind, c.value))
            uniq.append(c)
    res.children = uniq[:100]
    return res


@signal(SPEC)
def run_email(ctx: SignalContext) -> list[Evidence]:
    data: Any = getattr(ctx, "data", None)
    if not isinstance(data, bytes):
        return []
    return analyze_email(
        data,
        getattr(ctx, "brands", None)
        if isinstance(getattr(ctx, "brands", None), BrandRegistry)
        else None,
    ).evidence
