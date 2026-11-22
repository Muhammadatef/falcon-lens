"""Generate the invented Falcon Demo Bank logo and favicon (deterministic). Needs Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "sites" / "official" / "assets"


def falcon(size: int) -> Image.Image:
    im = Image.new("RGB", (size, size), (14, 52, 96))
    d = ImageDraw.Draw(im)
    s = size / 64
    d.polygon(
        [(8 * s, 40 * s), (32 * s, 8 * s), (56 * s, 40 * s), (32 * s, 30 * s)], fill=(240, 180, 40)
    )
    d.polygon(
        [(20 * s, 46 * s), (32 * s, 30 * s), (44 * s, 46 * s), (32 * s, 56 * s)],
        fill=(255, 255, 255),
    )
    d.ellipse([29 * s, 20 * s, 35 * s, 26 * s], fill=(14, 52, 96))
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    falcon(64).save(OUT / "favicon.png", optimize=True)
    falcon(160).save(OUT / "logo.png", optimize=True)
