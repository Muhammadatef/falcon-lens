"""Shrinks shots/*.png to an adaptive palette so the committed set stays under 2 MB.

Run after render-shots.mjs:  uv run --no-project --with pillow python web/design/v2/quantize.py
Only rewrites the PNG files in web/design/v2/shots/. Exits 1 if the set is still over 2 MB.
"""
import sys
from pathlib import Path

from PIL import Image

shots = Path(__file__).parent / "shots"
total = 0
for path in sorted(shots.glob("*.png")):
    image = Image.open(path).convert("RGB")
    image.quantize(colors=40, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    total += path.stat().st_size
print(f"shots: {total / 1e6:.2f} MB")
sys.exit(0 if total < 2_000_000 else 1)
