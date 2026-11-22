# ruff: noqa: E501
"""URL canonicalisation + registrable-domain extraction (PSL incl. private section). Pure/offline, never raises."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import unquote

import tldextract

from falcon_core.signals.url.textutil import BIDI_CHARS, ZERO_WIDTH_CHARS, scripts_in

DEFAULT_PORTS = {"http": 80, "https": 443, "ftp": 21, "ws": 80, "wss": 443}
MAX_URL_LEN = 8192

# Known free-hosting / tunnel suffixes (evidence url.free_host_or_tunnel). The PSL private section is
# also consulted (tldextract is_private); this list covers tunnels the PSL snapshot may lack.
FREE_HOST_SUFFIXES = frozenset(
    {
        "ngrok-free.app",
        "ngrok-free.dev",
        "ngrok.io",
        "ngrok.app",
        "ngrok.dev",
        "trycloudflare.com",
        "loca.lt",
        "localtunnel.me",
        "serveo.net",
        "localhost.run",
        "lhr.life",
        "pinggy.link",
        "pinggy.io",
        "workers.dev",
        "pages.dev",
        "github.io",
        "gitlab.io",
        "netlify.app",
        "vercel.app",
        "herokuapp.com",
        "web.app",
        "firebaseapp.com",
        "glitch.me",
        "repl.co",
        "replit.app",
        "replit.dev",
        "blogspot.com",
        "weebly.com",
        "wixsite.com",
        "000webhostapp.com",
        "infinityfreeapp.com",
        "rf.gd",
        "epizy.com",
        "onrender.com",
        "fly.dev",
        "railway.app",
        "surge.sh",
        "duckdns.org",
        "no-ip.org",
        "no-ip.biz",
        "ddns.net",
        "hopto.org",
        "zapto.org",
        "servebeer.com",
        "myftp.org",
        "webflow.io",
        "framer.app",
        "carrd.co",
        "sites.google.com",
        "linkpc.net",
        "bubbleapps.io",
        "godaddysites.com",
        "square.site",
        "azurewebsites.net",
        "cloudfront.net",
        "r2.dev",
        "ipfs.io",
        "dweb.link",
        "w3spaces.com",
    }
)

URL_SHORTENERS = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "is.gd",
        "ow.ly",
        "buff.ly",
        "cutt.ly",
        "rb.gy",
        "shorturl.at",
        "t.ly",
        "rebrand.ly",
        "tiny.cc",
        "s.id",
        "v.gd",
        "bl.ink",
        "lnkd.in",
        "wa.me",
        "qr.ae",
        "short.io",
    }
)

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True, cache_dir=None)
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_DOT_VARIANTS = str.maketrans({"。": ".", "．": ".", "｡": "."})
_UNRESERVED = re.compile(r"%(?:2[dDeE]|3[0-9]|4[1-9A-Fa-f]|5[0-9Aa]|5[Ff]|6[1-9A-Fa-f]|7[0-9Aa]|7[Ee])")


@dataclass(frozen=True)
class CanonicalURL:
    raw: str
    scheme: str = ""
    userinfo: str | None = None
    host: str = ""  # unicode, lowercased, trailing dot stripped
    host_ascii: str = ""  # punycode (A-label) form
    host_raw_case: str = ""  # host as written (case kept; for I/l tricks), invisibles removed
    port: int | None = None  # None when absent or default
    path: str = ""  # normalised (dot segments removed, unreserved %-decoded)
    query: str = ""
    fragment: str = ""
    path_decoded: str = ""  # fully percent-decoded (up to 3 rounds)
    query_decoded: str = ""
    is_ip: bool = False
    ip: str | None = None  # dotted-quad / IPv6 canonical text
    ip_obfuscated: bool = False  # decimal/octal/hex/short forms
    is_data_uri: bool = False
    has_bidi: bool = False
    has_zero_width: bool = False
    invisible_in_host: bool = False
    double_encoded: bool = False
    invalid_port: bool = False
    labels: tuple[str, ...] = ()
    subdomain: str = ""  # PSL subdomain part (may be "")
    domain_label: str = ""  # first label of the registrable domain (tenant name for private suffixes)
    suffix: str = ""
    registrable: str = ""  # domain_label + "." + suffix
    is_private_suffix: bool = False
    scripts: frozenset[str] = field(default_factory=frozenset)
    ok: bool = True

    @property
    def subdomain_labels(self) -> list[str]:
        return [x for x in self.subdomain.split(".") if x]

    @property
    def url(self) -> str:
        if self.is_data_uri:
            return self.raw[:128]
        auth = (self.userinfo + "@" if self.userinfo is not None else "") + (
            f"[{self.host_ascii}]" if ":" in self.host_ascii else self.host_ascii
        )
        port = f":{self.port}" if self.port else ""
        q = f"?{self.query}" if self.query else ""
        f = f"#{self.fragment}" if self.fragment else ""
        return f"{self.scheme}://{auth}{port}{self.path or '/'}{q}{f}"


def _punycode_decode_label(label: str) -> str:
    if label.startswith("xn--"):
        try:
            return label[4:].encode("ascii").decode("punycode")
        except (UnicodeError, ValueError):
            return label
    return label


def _punycode_encode_label(label: str) -> str:
    if label.isascii():
        return label
    try:
        return "xn--" + label.encode("punycode").decode("ascii")
    except (UnicodeError, ValueError):
        return label


def _parse_ipv4_part(p: str) -> int | None:
    try:
        if p.lower().startswith("0x"):
            return int(p[2:] or "0", 16)
        if len(p) > 1 and p.startswith("0"):
            return int(p, 8)
        return int(p, 10) if p.isdigit() else None
    except ValueError:
        return None


def parse_ipv4(host: str) -> tuple[str, bool] | None:
    """inet_aton-style parse (1-4 parts; decimal/octal/hex). Returns (dotted quad, obfuscated?) or None."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or any(p == "" for p in parts):
        return None
    nums = [_parse_ipv4_part(p) for p in parts]
    if any(n is None for n in nums):
        return None
    ints = [n for n in nums if n is not None]
    for n in ints[:-1]:
        if n > 255:
            return None
    if ints[-1] >= 256 ** (5 - len(ints)):
        return None
    value = 0
    for n in ints[:-1]:
        value = (value << 8) | n
    value = (value << (8 * (5 - len(ints)))) | ints[-1]
    quad = ".".join(str((value >> s) & 255) for s in (24, 16, 8, 0))
    canonical_form = len(parts) == 4 and all(p.isdigit() and (p == "0" or not p.startswith("0")) for p in parts)
    return quad, not canonical_form


def _normalize_path(path: str) -> str:
    path = _UNRESERVED.sub(lambda m: chr(int(m.group(0)[1:], 16)), path)
    out: list[str] = []
    segs = path.split("/")
    for i, seg in enumerate(segs):
        if seg == ".":
            if i == len(segs) - 1:
                out.append("")
            continue
        if seg == "..":
            if len(out) > 1:
                out.pop()
            if i == len(segs) - 1:
                out.append("")
            continue
        out.append(seg)
    res = "/".join(out)
    return res if res.startswith("/") or not res else "/" + res


def _full_decode(s: str) -> tuple[str, bool]:
    cur, rounds = s, 0
    for _ in range(3):
        nxt = unquote(cur)
        if nxt == cur:
            break
        cur, rounds = nxt, rounds + 1
    return cur, rounds > 1


def psl_split(host_ascii: str) -> tuple[str, str, str, bool]:
    """(subdomain, domain label, suffix, is_private_suffix) for an A-label host, PSL incl. private section."""
    ext = _EXTRACT(host_ascii)
    sub, dom, suf = ext.subdomain, ext.domain, ext.suffix
    if not suf and "." in host_ascii:
        # tldextract reports no suffix for TLDs outside the PSL (.test, .example, ...):
        # fall back to the default "*" rule (last label is the suffix).
        parts = host_ascii.split(".")
        suf, dom, sub = parts[-1], parts[-2], ".".join(parts[:-2])
    return sub, dom, suf, bool(ext.is_private)


@lru_cache(maxsize=4096)
def canonicalize(raw: str) -> CanonicalURL:
    try:
        return _canonicalize(raw)
    except Exception:  # noqa: BLE001 - never raise on hostile input
        return CanonicalURL(raw=raw[:512], ok=False)


def _canonicalize(raw: str) -> CanonicalURL:
    s = (raw or "")[:MAX_URL_LEN].strip()
    decoded_for_flags = unquote(s)
    has_bidi = any(c in BIDI_CHARS for c in s) or any(c in BIDI_CHARS for c in decoded_for_flags)
    has_zw = any(c in ZERO_WIDTH_CHARS for c in s) or any(c in ZERO_WIDTH_CHARS for c in decoded_for_flags)

    if s.lower().startswith("data:"):
        return CanonicalURL(raw=s[:512], scheme="data", is_data_uri=True, has_bidi=has_bidi, has_zero_width=has_zw)

    m = _SCHEME_RE.match(s)
    if m and not re.match(r"^[A-Za-z0-9.\-]+:\d+(/|$)", s):  # "host:8080/x" is not a scheme
        scheme = m.group(1).lower()
        rest = s[m.end() :]
    else:
        scheme, rest = "http", s
    rest = rest.replace("\\", "/")
    rest = rest.lstrip("/") if rest.startswith("//") or scheme in DEFAULT_PORTS else rest

    cut = len(rest)
    for ch in "/?#":
        i = rest.find(ch)
        if i != -1:
            cut = min(cut, i)
    authority, tail = rest[:cut], rest[cut:]
    fragment = query = ""
    if "#" in tail:
        tail, fragment = tail.split("#", 1)
    if "?" in tail:
        tail, query = tail.split("?", 1)

    userinfo: str | None = None
    if "@" in authority:
        userinfo, authority = authority.rsplit("@", 1)
        userinfo = unquote(userinfo)

    port: int | None = None
    invalid_port = False
    host_part = authority
    if host_part.startswith("["):
        end = host_part.find("]")
        hostname = host_part[1:end] if end != -1 else host_part[1:]
        after = host_part[end + 1 :] if end != -1 else ""
        port_s = after[1:] if after.startswith(":") else ""
    elif ":" in host_part:
        hostname, port_s = host_part.rsplit(":", 1)
    else:
        hostname, port_s = host_part, ""
    if port_s:
        if port_s.isdigit() and int(port_s) < 65536:
            p = int(port_s)
            port = None if DEFAULT_PORTS.get(scheme) == p else p
        else:
            invalid_port = True

    hostname = unquote(hostname)
    invisible_in_host = any(c in BIDI_CHARS or c in ZERO_WIDTH_CHARS for c in hostname)
    if invisible_in_host:
        hostname = "".join(c for c in hostname if c not in BIDI_CHARS and c not in ZERO_WIDTH_CHARS)
    hostname = hostname.translate(_DOT_VARIANTS).rstrip(".")
    host_raw_case = unicodedata.normalize("NFKC", hostname)
    host = host_raw_case.casefold() if not hostname.startswith("[") else host_raw_case.lower()
    labels_u = tuple(_punycode_decode_label(x) for x in host.split(".")) if host else ()
    host_u = ".".join(labels_u)
    host_ascii = ".".join(_punycode_encode_label(x) for x in labels_u)

    is_ip = False
    ip: str | None = None
    obf = False
    if ":" in host_u:  # IPv6 literal
        is_ip, ip = True, host_u
    else:
        v4 = parse_ipv4(host_u)
        if v4:
            is_ip, (ip, obf) = True, v4

    path = _normalize_path(tail)
    path_dec, dbl_p = _full_decode(tail)
    query_dec, dbl_q = _full_decode(query)

    subdomain = domain_label = suffix = registrable = ""
    private = False
    if host_u and not is_ip:
        e_sub, e_dom, e_suf, private = psl_split(host_ascii)
        subdomain = ".".join(_punycode_decode_label(x) for x in e_sub.split(".") if x)
        domain_label = _punycode_decode_label(e_dom)
        suffix = ".".join(_punycode_decode_label(x) for x in e_suf.split(".") if x)
        registrable = f"{domain_label}.{suffix}" if suffix else domain_label

    scripts = frozenset(scripts_in(host_u)) if host_u and not is_ip else frozenset()
    return CanonicalURL(
        raw=s[:512],
        scheme=scheme,
        userinfo=userinfo,
        host=host_u,
        host_ascii=host_ascii,
        host_raw_case=host_raw_case,
        port=port,
        path=path,
        query=query,
        fragment=fragment,
        path_decoded=path_dec,
        query_decoded=query_dec,
        is_ip=is_ip,
        ip=ip,
        ip_obfuscated=obf,
        has_bidi=has_bidi,
        has_zero_width=has_zw,
        invisible_in_host=invisible_in_host,
        double_encoded=dbl_p or dbl_q,
        invalid_port=invalid_port,
        labels=labels_u,
        subdomain=subdomain,
        domain_label=domain_label,
        suffix=suffix,
        registrable=registrable,
        is_private_suffix=private,
        scripts=scripts,
        ok=bool(host_u),
    )


def free_host_suffix(c: CanonicalURL) -> str | None:
    """Return the matching free-host/tunnel suffix (PSL private section or known list), else None."""
    if not c.suffix or c.is_ip:
        return None
    if c.suffix in FREE_HOST_SUFFIXES:
        return c.suffix
    for fh in FREE_HOST_SUFFIXES:
        if c.host == fh or c.host.endswith("." + fh):
            return fh
    return c.suffix if c.is_private_suffix else None
