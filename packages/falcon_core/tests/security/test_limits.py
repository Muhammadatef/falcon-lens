"""Input limits: sizes, invalid UTF-8, MIME nesting and part counts, image decompression bombs."""

from __future__ import annotations

import struct
import time

from falcon_core.security import limits


def _png(w: int, h: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)


def _jpeg(w: int, h: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return b"\xff\xd8" + app0 + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00\xff\xd9"


def _webp_vp8x(w: int, h: int) -> bytes:
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


def test_size_caps_per_kind() -> None:
    assert limits.check_size("url", "https://a.example/" + "a" * 4000).ok
    assert limits.check_size("url", "https://a.example/" + "a" * 5000).reason == "too_large"
    assert limits.check_size("message", "م" * 4096).ok  # 8 KB of UTF-8 bytes
    assert not limits.check_size("message", "م" * 4097).ok
    assert not limits.check_size("email", b"x" * (2 * 1024 * 1024 + 1)).ok
    assert not limits.check_size("image", b"x" * (5 * 1024 * 1024 + 1)).ok


def test_decode_text_reports_invalid_utf8() -> None:
    assert limits.decode_text("مرحبا".encode()) == ("مرحبا", False)
    text, bad = limits.decode_text(b"ok \xff\xfe \xc3\x28 end")
    assert bad and text.startswith("ok ") and text.endswith(" end") and "�" in text


def _nested(depth: int) -> bytes:
    lines = ["Subject: x", "MIME-Version: 1.0"]
    for i in range(depth):
        lines += [f'Content-Type: multipart/mixed; boundary="b{i}"', "", f"--b{i}"]
    lines += ["Content-Type: text/plain", "", "hello"]
    lines += [f"--b{i}--" for i in reversed(range(depth))]
    return "\r\n".join(lines).encode()


def test_mime_depth() -> None:
    assert limits.check_mime(_nested(3)).ok
    assert limits.check_mime(_nested(8)).ok
    r = limits.check_mime(_nested(9))
    assert r.reason == "mime_too_deep" and r.detail and r.detail["depth"] == 9
    t0 = time.perf_counter()
    assert limits.check_mime(_nested(5000)).reason in ("mime_too_deep", "mime_too_many_parts")
    assert time.perf_counter() - t0 < 2.0


def test_mime_siblings_are_not_depth() -> None:
    parts = ["Subject: x", 'Content-Type: multipart/mixed; boundary="outer"', ""]
    for i in range(6):
        parts += ["--outer", f'Content-Type: multipart/alternative; boundary="in{i}"', "", f"--in{i}",
                  "Content-Type: text/plain", "", "t", f"--in{i}--"]  # fmt: skip
    parts += ["--outer--"]
    assert limits.check_mime("\r\n".join(parts).encode()).ok


def test_mime_part_count() -> None:
    lines = ["Subject: x", 'Content-Type: multipart/mixed; boundary="bx"', ""]
    for i in range(400):
        lines += ["--bx", "Content-Type: text/plain", "", f"p{i}"]
    lines += ["--bx--"]
    assert limits.check_mime("\r\n".join(lines).encode()).reason == "mime_too_many_parts"


def test_image_headers() -> None:
    assert limits.image_header(_png(64, 32)) == limits.ImageHeader("png", 64, 32)
    assert limits.image_header(_jpeg(640, 480)) == limits.ImageHeader("jpeg", 640, 480)
    assert limits.image_header(b"GIF89a" + struct.pack("<HH", 10, 20) + b"\x00") == limits.ImageHeader("gif", 10, 20)
    assert limits.image_header(_webp_vp8x(300, 200)) == limits.ImageHeader("webp", 300, 200)
    assert limits.image_header(b"not an image") is None


def test_decompression_bombs_rejected() -> None:
    assert limits.check_image(_png(64, 64)).ok
    assert limits.check_image(_jpeg(4000, 3000)).ok
    assert limits.check_image(_png(100_000, 100_000)).reason == "image_decompression_bomb"
    assert limits.check_image(_jpeg(65_000, 65_000)).reason == "image_decompression_bomb"
    assert limits.check_image(_png(20_000, 10)).reason == "image_decompression_bomb"  # one side too long
    assert limits.check_image(_webp_vp8x(16_000, 16_000)).reason == "image_decompression_bomb"
    assert limits.check_image(b"GIF89a\x00\x00\x00\x00").reason == "image_zero_dimension"
    assert limits.check_image(b"\x89PNG\r\n\x1a\n\x00\x00").reason == "image_unknown_format"


def test_jpeg_parser_is_bounded_on_garbage() -> None:
    assert limits.image_header(b"\xff\xd8" + b"\xff\xe1\x00\x02" * 200_000) is None
    assert limits.image_header(b"\xff\xd8\xff\xe1\x00\x00") is None
