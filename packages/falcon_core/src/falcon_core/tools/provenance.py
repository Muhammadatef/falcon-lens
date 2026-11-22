"""ProvenanceRule (contracts/tools.schema.json).

Every URL/domain argument MUST be the original canonical input, a hop in its observed redirect
chain, or a registrable domain derived from those. Anything else is rejected and counted as
injection evidence.

The cascade builds the context from its own observations (canonical URL, redirect hops seen by our
fetcher, registrable domains from the PSL-aware canonicaliser). Hops observed later by the
``expand_redirects`` tool are appended by the registry, since our own fetcher observed them.

Registrable-domain derivation: the cascade should pass ``registrable_domains`` computed with the
PSL. As a fallback, ``registrable_fn`` (default: a conservative heuristic) derives one per on-chain
host. Any derived value is always a suffix of an on-chain host, so an attacker cannot steer a tool
to an unrelated domain through this path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit, urlunsplit

RegistrableFn = Callable[[str], str | None]

_SECOND_LEVEL = frozenset({"co", "com", "gov", "ac", "org", "net", "edu", "mil", "sch", "ne", "or"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalise_host(host: str) -> str | None:
    h = host.strip().rstrip(".").lower()
    if not h or any(c in h for c in "/\\@ \t\n?#"):
        return None
    if h.startswith("[") and h.endswith("]"):
        return h
    try:
        h = h.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return h


def normalise_url(url: str) -> str | None:
    """Case-fold scheme and host, drop default port and fragment. Path and query stay exact."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return None
    has_userinfo = parts.username is not None or parts.password is not None
    userinfo = parts.netloc.rsplit("@", 1)[0] + "@" if has_userinfo else ""
    host = normalise_host(parts.hostname)
    if host is None:
        return None
    netloc = userinfo + host + (f":{port}" if port and port != _DEFAULT_PORTS[scheme] else "")
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def host_of(url: str) -> str | None:
    n = normalise_url(url)
    if n is None:
        return None
    return normalise_host(urlsplit(n).hostname or "")


def heuristic_registrable(host: str) -> str | None:
    """Conservative eTLD+1 guess: last two labels, or three for ``x.co.uk``-style ccTLDs."""
    labels = host.split(".")
    if len(labels) < 2 or host.startswith("["):
        return None
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


@dataclass(frozen=True, slots=True)
class ProvenanceContext:
    canonical_url: str | None
    redirect_chain: tuple[str, ...] = ()
    registrable_domains: frozenset[str] = frozenset()
    script_fingerprints: frozenset[str] = frozenset()
    registrable_fn: RegistrableFn | None = field(default=heuristic_registrable, compare=False)

    @property
    def urls(self) -> frozenset[str]:
        raw = ([self.canonical_url] if self.canonical_url else []) + list(self.redirect_chain)
        return frozenset(n for n in (normalise_url(u) for u in raw) if n)

    @property
    def domains(self) -> frozenset[str]:
        out: set[str] = set()
        for u in self.urls:
            h = host_of(u)
            if not h:
                continue
            out.add(h)
            if self.registrable_fn is not None:
                r = self.registrable_fn(h)
                if r and (h == r or h.endswith("." + r)):
                    out.add(r)
        for d in self.registrable_domains:
            n = normalise_host(d)
            if n:
                out.add(n)
        return frozenset(out)

    def allows_url(self, url: str) -> bool:
        n = normalise_url(url)
        return n is not None and n in self.urls

    def allows_domain(self, domain: str) -> bool:
        n = normalise_host(domain)
        return n is not None and n in self.domains

    def allows_fingerprint(self, fp: str) -> bool:
        return fp in self.script_fingerprints

    def with_hops(self, hops: Iterable[str]) -> ProvenanceContext:
        extra = tuple(h for h in hops if isinstance(h, str) and normalise_url(h))
        if not extra:
            return self
        return replace(self, redirect_chain=self.redirect_chain + extra)
