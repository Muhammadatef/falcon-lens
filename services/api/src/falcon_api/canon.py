"""Simple URL canonicalisation used only for keying (cache, single-flight).

The worker re-canonicalises authoritatively; this must merely be stable and cheap.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from urllib.parse import urlsplit

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_BAD = re.compile(r"[\x00-\x20\x7f]")
_DEFAULT_PORT = {"http": 80, "https": 443}


def canonicalize_url(raw: str) -> str:
    """Return a canonical http(s) URL, or raise ValueError."""
    s = raw.strip()
    if _BAD.search(s):
        raise ValueError("whitespace or control characters")
    if not _SCHEME.match(s):
        if "://" in s or s.lower().startswith(("javascript:", "data:", "file:", "mailto:")):
            raise ValueError("unsupported scheme")
        s = "http://" + s
    parts = urlsplit(s)
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORT:
        raise ValueError("unsupported scheme")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise ValueError("missing host")
    with contextlib.suppress(UnicodeError):
        host = host.encode("idna").decode("ascii")
    port = parts.port  # may raise ValueError
    netloc = f"[{host}]" if ":" in host else host
    if port and port != _DEFAULT_PORT[scheme]:
        netloc += f":{port}"
    path = parts.path or "/"
    return f"{scheme}://{netloc}{path}" + (f"?{parts.query}" if parts.query else "")


def sha256_hex(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()
