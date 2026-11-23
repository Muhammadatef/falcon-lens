"""Display copy of a checked URL: the checked host, no userinfo, personal data redacted."""

from __future__ import annotations

from urllib.parse import unquote

from falcon_core.llm.redaction import redact
from falcon_core.signals.url.canonical import CanonicalURL, canonicalize


def display_url(url: str | CanonicalURL) -> str:
    """The copy of a checked URL that is stored, returned and shown: checked host kept, personal data removed.

    Built ONLY from the parsed ``CanonicalURL`` fields (scheme, host, port, path, query), never by re-parsing a
    string, so the host shown is exactly the host that was checked. Userinfo (user and password) is never
    copied. Path and query go through the same redaction as text sent to a cloud model (emails, UAE phones,
    Emirates ID, cards, IBAN), also when percent-encoded. The fragment is dropped (never sent to a server).
    """
    if isinstance(url, str) and "://" not in url:
        return redact(url[:512]).text
    c = canonicalize(url) if isinstance(url, str) else url
    if not c.ok or c.is_data_uri:
        raw = url if isinstance(url, str) else c.raw
        return redact(raw[:128]).text if not c.is_data_uri else "data:"
    host = f"[{c.host}]" if ":" in c.host else c.host
    port = f":{c.port}" if c.port else ""
    tail = c.path + (f"?{c.query}" if c.query else "")
    if tail:
        res = redact(tail)
        if "%" in tail:
            decoded = redact(unquote(tail))
            if decoded.redacted:
                res = decoded
        if res.redacted:
            tail = res.text
    return f"{c.scheme}://{host}{port}{tail}"
