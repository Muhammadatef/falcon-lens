"""dnstwist-style look-alike generator over the brand registry (docs/design/HUNTER.md section 3).

Pure and deterministic: the same registry and hunt.yaml give the same names in the same order. No I/O and no
brand name in code: labels come from each brand's ``verified_domains`` in data/brands.yaml.

Kinds: typo (omission, repetition, transposition, adjacent-key replacement, hyphenation), homoglyph (one
letter replaced by a UTS #39 confusable, emitted as punycode), combosquat (label +/- "-" + word, both orders),
TLD swap. Typo and homoglyph only for labels of ``typo_min_label`` (5) characters or more; short labels
(du, rta, moi, dib) get combosquats and TLD swaps only. Any name whose registrable domain is a verified
domain of any brand is dropped.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache

from falcon_core.signals.brands.registry import Brand, BrandRegistry
from falcon_core.signals.url.skeleton import _table
from falcon_core.signals.url.squatting import COMBO_EN, COMBO_TRANSLIT

from .candidates import registrable
from .config import PERMUTATION_KINDS, PermutationConfig

_QWERTY = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")
_SCRIPT_ORDER = ("CYRILLIC SMALL LETTER", "GREEK SMALL LETTER", "LATIN SMALL LETTER")
_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


@dataclass(frozen=True)
class Permutation:
    name: str  # A-label registrable domain (punycode for homoglyphs)
    brand_id: str
    kind: str  # one of PERMUTATION_KINDS
    base: str  # the verified domain it was derived from


@lru_cache(maxsize=1)
def _adjacent() -> dict[str, str]:
    pos = {c: (r, i) for r, row in enumerate(_QWERTY) for i, c in enumerate(row)}
    out: dict[str, str] = {}
    for c, (r, i) in pos.items():
        near = []
        for dr in (-1, 0, 1):
            for di in (-1, 0, 1):
                if (dr, di) == (0, 0):
                    continue
                rr, ii = r + dr, i + di
                if 0 <= rr < len(_QWERTY) and 0 <= ii < len(_QWERTY[rr]):
                    near.append(_QWERTY[rr][ii])
        out[c] = "".join(sorted(near))
    return out


@lru_cache(maxsize=4)
def _homoglyphs(per_letter: int) -> dict[str, tuple[str, ...]]:
    """ASCII letter -> lowercase non-ASCII letters (Cyrillic, Greek, Latin extensions) whose UTS #39
    skeleton is that letter. Cyrillic first, then Greek, then Latin; lowest code point inside a script."""
    rev: dict[str, list[str]] = {}
    for src, dst in _table().items():
        if len(dst) != 1 or not ("a" <= dst <= "z") or ord(src) < 128:
            continue
        if not src.isalpha() or src != src.lower() or unicodedata.combining(src):
            continue
        name = unicodedata.name(src, "")
        if not name.startswith(_SCRIPT_ORDER):
            continue
        try:
            _ascii_label(src)
        except ValueError:
            continue
        rev.setdefault(dst, []).append(src)

    def order(ch: str) -> tuple[int, int]:
        name = unicodedata.name(ch, "")
        return next(i for i, s in enumerate(_SCRIPT_ORDER) if name.startswith(s)), ord(ch)

    return {k: tuple(sorted(v, key=order)[:per_letter]) for k, v in sorted(rev.items())}


def _ascii_label(label: str) -> str:
    """A-label of one DNS label (punycode for non-ASCII). Raises ValueError if not encodable."""
    if label.isascii():
        return label
    out = label.encode("idna").decode("ascii")
    if not out.startswith("xn--"):
        raise ValueError(label)
    return out


def _valid_label(label: str) -> bool:
    if not 1 <= len(label) <= 63 or label.startswith("-") or label.endswith("-"):
        return False
    if label.startswith("xn--"):
        return all(c in _ALNUM for c in label)
    return all(c in _ALNUM for c in label) and "--" not in label


def typos(label: str) -> Iterator[str]:
    """Omission, repetition, transposition, adjacent-key replacement, hyphenation (deterministic order)."""
    adj = _adjacent()
    n = len(label)
    for i in range(n):
        yield label[:i] + label[i + 1 :]
    for i in range(n):
        if label[i] != "-":
            yield label[:i] + label[i] + label[i:]
    for i in range(n - 1):
        if label[i] != label[i + 1]:
            yield label[:i] + label[i + 1] + label[i] + label[i + 2 :]
    for i, c in enumerate(label):
        for k in adj.get(c, ""):
            yield label[:i] + k + label[i + 1 :]
    for i in range(1, n):
        yield label[:i] + "-" + label[i:]


def homoglyphs(label: str, per_letter: int) -> Iterator[str]:
    table = _homoglyphs(per_letter)
    for i, c in enumerate(label):
        for g in table.get(c, ()):
            yield label[:i] + g + label[i + 1 :]


def combo_words(cfg: PermutationConfig) -> tuple[str, ...]:
    seen: list[str] = []
    for w in (*cfg.combo_priority, *COMBO_EN, *COMBO_TRANSLIT):
        w = w.lower()
        if w.isascii() and w.isalnum() and w not in seen:
            seen.append(w)
    return tuple(seen)


def combosquats(label: str, words: Iterable[str]) -> Iterator[str]:
    for w in words:
        yield f"{label}-{w}"
        yield f"{w}-{label}"
        yield f"{label}{w}"
        yield f"{w}{label}"


def _homes(brand: Brand, suffix: str, cfg: PermutationConfig) -> tuple[str, ...]:
    """Suffixes the typo / homoglyph / combosquat variants of one label are placed under."""
    if suffix in cfg.restricted_suffixes and not (brand.is_demo and cfg.keep_suffix_for_demo):
        return cfg.fallback_suffixes
    return (suffix,)


def _interleave(streams: dict[str, list[str]], cap: int) -> list[tuple[str, str]]:
    """Round-robin over the kinds (fixed order) so a cap never starves a kind."""
    out: list[tuple[str, str]] = []
    idx = dict.fromkeys(streams, 0)
    while len(out) < cap and any(idx[k] < len(v) for k, v in streams.items()):
        for k in PERMUTATION_KINDS:
            v = streams.get(k, [])
            if idx.get(k, 0) < len(v) and len(out) < cap:
                out.append((k, v[idx[k]]))
                idx[k] += 1
    return out


def permute_brand(brand: Brand, registry: BrandRegistry, cfg: PermutationConfig) -> list[Permutation]:
    """Deterministic, capped, de-duplicated look-alike names for one brand. Never a verified domain."""
    words = combo_words(cfg)
    streams: dict[str, list[str]] = {k: [] for k in PERMUTATION_KINDS}
    base_of: dict[str, str] = {}
    seen: set[str] = set()

    def add(kind: str, label: str, suffix: str, base: str) -> None:
        try:
            alabel = _ascii_label(label)
        except (ValueError, UnicodeError):
            return
        if not _valid_label(alabel):
            return
        name = f"{alabel}.{suffix}"
        reg = registrable(name)
        if not reg or reg != name or reg in seen or registry.is_official(reg):
            return
        seen.add(reg)
        base_of[reg] = base
        streams[kind].append(reg)

    for base, (label, suffix) in zip(brand.verified_domains, brand.domain_parts, strict=True):
        if not label or not suffix:
            continue
        homes = _homes(brand, suffix, cfg)
        long_enough = len(label) >= cfg.typo_min_label
        for home in homes:
            if long_enough:
                for t in typos(label):
                    add("typo", t, home, base)
                for h in homoglyphs(label, cfg.homoglyphs_per_letter):
                    add("homoglyph", h, home, base)
            for c in combosquats(label, words):
                add("combosquat", c, home, base)
        for tld in cfg.tlds:
            if tld != suffix:
                add("tld_swap", label, tld, base)
    return [
        Permutation(name, brand.brand_id, kind, base_of[name]) for kind, name in _interleave(streams, cfg.cap_per_brand)
    ]


def permute_registry(registry: BrandRegistry, cfg: PermutationConfig) -> list[Permutation]:
    """All brands, registry order. A name generated for two brands is kept once (first brand wins)."""
    out: list[Permutation] = []
    seen: set[str] = set()
    for b in registry.brands:
        for p in permute_brand(b, registry, cfg):
            if p.name not in seen:
                seen.add(p.name)
                out.append(p)
    return out
