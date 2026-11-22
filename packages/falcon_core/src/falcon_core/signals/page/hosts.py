"""Small host helpers (no PSL dependency; the signals-url branch owns the full PSL logic)."""

from __future__ import annotations

from urllib.parse import urlsplit

# Multi-label public suffixes relevant to UAE/GCC and common targets. Heuristic, see DECISIONS.md.
_TWO_LABEL_SUFFIXES = frozenset(
    {
        "gov.ae", "co.ae", "com.ae", "net.ae", "org.ae", "ac.ae", "sch.ae", "ae.org",
        "gov.sa", "com.sa", "co.uk", "org.uk", "gov.uk", "com.au", "co.in", "com.br",
    }
)  # fmt: skip


def registrable_domain(host: str) -> str:
    """Approximate eTLD+1 for ``host`` (lower-cased, no port)."""
    host = host.lower().strip(".")
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def same_site(a: str, b: str) -> bool:
    """True if two hosts share a registrable domain."""
    return bool(a) and bool(b) and registrable_domain(a) == registrable_domain(b)
