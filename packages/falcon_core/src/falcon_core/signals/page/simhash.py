"""Structure-only DOM simhash (64-bit) over tag-structure tokens; text never contributes."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable

BITS = 64


def dom_simhash(tokens: Iterable[str]) -> str:
    """16-hex-char simhash of structure tokens (e.g. ``3:div``, ``form>input``)."""
    counts = Counter(tokens)
    if not counts:
        return "0" * (BITS // 4)
    acc = [0] * BITS
    for tok, n in counts.items():
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        weight = 1 + (n.bit_length() - 1)  # log-ish: repeated structure should not dominate
        for i in range(BITS):
            acc[i] += weight if (h >> i) & 1 else -weight
    out = 0
    for i in range(BITS):
        if acc[i] > 0:
            out |= 1 << i
    return f"{out:016x}"


def hamming_hex(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()
