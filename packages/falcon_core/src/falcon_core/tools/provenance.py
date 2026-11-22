"""ProvenanceRule (contracts/tools.schema.json).

Every URL/domain argument MUST be the original canonical input, a hop in its observed redirect
chain, or a registrable domain derived from those. Anything else is rejected and counted as
injection evidence.

How a model-supplied argument is checked:
1. **Gate.** The raw argument must be printable ASCII with no whitespace, control characters or
   backslash. Non-ASCII hosts (``ß``, full-width letters, ideographic dots, zero-width characters)
   are rejected outright; an on-chain IDN host is always available in its ASCII (A-label) form
   and through the investigator's target refs, so nothing legitimate is lost. This also avoids any
   IDNA2003-vs-UTS46 disagreement about what a Unicode host "means".
2. **Canonicalise** with the same canonicaliser as the URL signals
   (``falcon_core.signals.url.canonical.canonicalize``): lower-cased A-label host, trailing dot
   stripped, default port dropped, dot segments and unreserved escapes normalised, fragment dropped.
3. **Compare** with the canonical form of every on-chain value.
4. **Forward only the on-chain canonical value** (``resolve_url`` / ``resolve_domain``), never the
   model's string.

Registrable domains come from the PSL (``psl_split``, private section included). So for
``evil-demo.github.io`` the registrable domain is ``evil-demo.github.io`` and ``github.io`` (a
public suffix) is never allowed. Values the cascade passes in ``registrable_domains`` are added
too. There is no heuristic parent-domain guess.

The cascade builds the context from its own observations: the canonical URL, redirect hops seen
by our fetcher, and registrable domains from the canonicaliser. Hops observed later by the
``expand_redirects`` tool are appended by the registry, because our own fetcher observed them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cached_property

from falcon_core.signals.url.canonical import CanonicalURL, canonicalize, psl_split


def _gate(value: str) -> bool:
    """Printable ASCII only: no whitespace, control characters, backslash or non-ASCII forms."""
    return bool(value) and value.isascii() and all(0x21 <= ord(c) <= 0x7E for c in value) and "\\" not in value


def _key(c: CanonicalURL) -> str:
    auth = (c.userinfo + "@" if c.userinfo is not None else "") + (
        f"[{c.host_ascii}]" if ":" in c.host_ascii else c.host_ascii
    )
    port = f":{c.port}" if c.port else ""
    q = f"?{c.query}" if c.query else ""
    return f"{c.scheme}://{auth}{port}{c.path or '/'}{q}"


def _usable(c: CanonicalURL) -> bool:
    return c.ok and c.scheme in ("http", "https") and not c.is_data_uri and not c.invalid_port


def canonical_url(url: str) -> str | None:
    """Canonical comparison/forwarding form of a *model-supplied* http(s) URL, or None.

    Gated first (printable ASCII only); then the URL-signal canonicaliser; fragment dropped.
    """
    if not _gate(url) or "://" not in url:
        return None
    c = canonicalize(url)
    if not _usable(c) or c.has_zero_width or c.has_bidi or c.invisible_in_host:
        return None
    return _key(c)


def canonical_host(domain: str) -> str | None:
    """Canonical A-label host for a bare domain argument, or None."""
    if not _gate(domain) or any(ch in domain for ch in "/?#@:[]"):
        return None
    c = canonicalize(f"http://{domain}/")
    if not c.ok or c.is_ip or c.invisible_in_host or not c.host_ascii:
        return None
    return c.host_ascii


def registrable_of(host_ascii: str) -> str | None:
    """PSL registrable domain (A-label), private section included; None for IPs/bare suffixes."""
    if not host_ascii or host_ascii.startswith("[") or "." not in host_ascii:
        return None
    _sub, dom, suf, _private = psl_split(host_ascii)
    if not dom or not suf:
        return None
    return f"{dom}.{suf}"


def _host_of_canonical(url: str) -> str | None:
    c = canonicalize(url)
    return c.host_ascii if c.ok and not c.is_ip else None


@dataclass(frozen=True)
class ProvenanceContext:
    canonical_url: str | None
    redirect_chain: tuple[str, ...] = ()
    registrable_domains: frozenset[str] = frozenset()
    script_fingerprints: frozenset[str] = frozenset()

    @cached_property
    def url_list(self) -> tuple[str, ...]:
        """Canonical on-chain URLs in chain order (canonical input first). Trusted inputs: no gate."""
        raw = ([self.canonical_url] if self.canonical_url else []) + list(self.redirect_chain)
        out: list[str] = []
        for u in raw:
            c = canonicalize(u)
            if _usable(c):
                k = _key(c)
                if k not in out:
                    out.append(k)
        return tuple(out)

    @cached_property
    def domain_list(self) -> tuple[str, ...]:
        """On-chain hosts, then their PSL registrable domains, then cascade-supplied ones."""
        hosts = [h for h in (_host_of_canonical(u) for u in self.url_list) if h]
        regs = [r for r in (registrable_of(h) for h in hosts) if r]
        given = [h for h in (canonical_host(d) for d in sorted(self.registrable_domains)) if h]
        return tuple(dict.fromkeys(hosts + regs + given))

    @property
    def urls(self) -> frozenset[str]:
        return frozenset(self.url_list)

    @property
    def domains(self) -> frozenset[str]:
        return frozenset(self.domain_list)

    def resolve_url(self, url: str) -> str | None:
        """The on-chain canonical URL the argument designates, or None (provenance violation)."""
        if url in self.urls:  # exact on-chain value (e.g. a resolved target ref)
            return url
        n = canonical_url(url)
        return n if n is not None and n in self.urls else None

    def resolve_domain(self, domain: str) -> str | None:
        if domain in self.domains:
            return domain
        n = canonical_host(domain)
        return n if n is not None and n in self.domains else None

    def allows_url(self, url: str) -> bool:
        return self.resolve_url(url) is not None

    def allows_domain(self, domain: str) -> bool:
        return self.resolve_domain(domain) is not None

    def allows_fingerprint(self, fp: str) -> bool:
        return fp in self.script_fingerprints

    def with_hops(self, hops: Iterable[str]) -> ProvenanceContext:
        extra = tuple(h for h in hops if isinstance(h, str) and _usable(canonicalize(h)))
        if not extra:
            return self
        return replace(self, redirect_chain=self.redirect_chain + extra)


def normalise_url(url: str) -> str | None:
    """Backwards-compatible alias for ``canonical_url``."""
    return canonical_url(url)


def normalise_host(host: str) -> str | None:
    """Backwards-compatible alias for ``canonical_host``."""
    return canonical_host(host)
