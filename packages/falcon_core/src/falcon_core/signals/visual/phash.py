"""64-bit perceptual hash (pHash, DCT-based) over a 32x32 grayscale grid.

Pure Python so ``falcon_core`` needs no imaging dependency; the sandbox resizes the image with
Pillow and hands the 32x32 luminance grid here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

N = 32
_K = 8  # low-frequency block size -> 64 bits
_COS = [[math.cos(math.pi * (2 * x + 1) * u / (2 * N)) for x in range(N)] for u in range(_K)]


def phash_from_gray32(rows: Sequence[Sequence[float]]) -> str:
    """pHash (16 hex chars) of a 32x32 grid of luminance values."""
    if len(rows) != N or any(len(r) != N for r in rows):
        raise ValueError("expected a 32x32 grid")
    # separable DCT, keeping only the first 8 frequencies per axis
    tmp = [[sum(rows[y][x] * _COS[u][x] for x in range(N)) for u in range(_K)] for y in range(N)]
    dct = [[sum(tmp[y][u] * _COS[v][y] for y in range(N)) for u in range(_K)] for v in range(_K)]
    flat = [dct[v][u] for v in range(_K) for u in range(_K)]
    median = sorted(flat[1:])[len(flat[1:]) // 2]  # exclude the DC term from the median
    bits = 0
    for i, val in enumerate(flat):
        if val > median:
            bits |= 1 << i
    return f"{bits:016x}"


def hamming64(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()
