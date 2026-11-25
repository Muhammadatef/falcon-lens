#!/usr/bin/env python3
# ruff: noqa: E501, S603, S607
"""Read a saved .key and count, per slide, the builds and the slide links Keynote holds.

    uv run --no-project --with cramjam python submission/build/keynote_report.py <deck.key>

A .key is a zip of IWA files: Snappy-compressed chunks (a 0x00 byte, a three-byte length, raw Snappy data) holding
protobuf messages. This does not decode the messages; it counts the effect identifiers ("apple:..." strings) that a
build or a transition stores, and the "?slideid=" link targets, in each slide's file. That is enough to confirm that
the import kept the motion and the links; it is a structural check, not a playback test.
"""

from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter

import cramjam


def iwa_bytes(raw: bytes) -> bytes:
    out, i = bytearray(), 0
    while i + 4 <= len(raw):
        size = int.from_bytes(raw[i + 1 : i + 4], "little")
        out += bytes(cramjam.snappy.decompress_raw(raw[i + 4 : i + 4 + size]))
        i += 4 + size
    return bytes(out)


def natural(name: str) -> list[int | str]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def main() -> int:
    path = sys.argv[1]
    total_fx: Counter[str] = Counter()
    rows = []
    with zipfile.ZipFile(path) as zf:
        names = sorted(
            (
                n
                for n in zf.namelist()
                if re.search(r"Index/Slide[^/]*\.iwa$", n) and "Template" not in n and "Master" not in n
            ),
            key=natural,
        )
        for name in names:
            data = iwa_bytes(zf.read(name))
            fx = Counter(m.decode() for m in re.findall(rb"apple:[a-zA-Z0-9_.-]+", data))
            links = len(re.findall(rb"\?slideid=", data))
            rows.append((name, fx, links))
            total_fx += fx
    for name, fx, links in rows:
        print(f"{name:<34} effects {sum(fx.values()):>3}  links {links:>2}  {dict(fx)}")
    print(
        f"slides {len(rows)}; effect records {sum(total_fx.values())}: {dict(total_fx)}; slide links {sum(r[2] for r in rows)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
