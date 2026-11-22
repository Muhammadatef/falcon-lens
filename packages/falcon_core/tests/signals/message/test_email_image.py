# ruff: noqa: E501
"""Email and image pipelines. Brand: Falcon Demo Bank only; links on example.test; placeholder numbers."""

import base64
import hashlib
import io
import struct
import zlib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

import pytest
import qrcode  # type: ignore[import-untyped]
from PIL import Image
from schema_helper import run_async, validate_evidence

from falcon_core.signals import REGISTRY
from falcon_core.signals.email.analyze import MAX_EMAIL_BYTES, MAX_PARTS, analyze_email
from falcon_core.signals.image.analyze import (
    MAX_IMAGE_BYTES,
    analyze_image,
    analyze_image_with_ocr,
    sniff,
)


def names(res: Any) -> set[str]:
    return {e.signal for e in res.evidence}


def get(res: Any, name: str) -> Any:
    return next(e for e in res.evidence if e.signal == name)


def mk(
    frm: str = "Falcon Demo Bank <alerts@falcon-demo-bank.test>",
    subject: str = "Hello",
    text: str | None = "hello",
    html: str | None = None,
    **hdrs: str,
) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "user@example.test", subject
    for k, v in hdrs.items():
        m[k.replace("_", "-")] = v
    if text is not None:
        m.set_content(text)
    if html is not None:
        m.add_alternative(html, subtype="html")
    return m


def qr_png(payload: str) -> bytes:
    img = qrcode.make(payload).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- email


def test_clean_email_has_no_risk_evidence() -> None:
    res = analyze_email(mk().as_bytes())
    assert not [
        e for e in res.evidence if e.signal.startswith("email.") and e.signal != "email.attachment"
    ]


def test_auth_fail_variants() -> None:
    m = mk(
        Authentication_Results="mx.example.test; spf=pass; dkim=fail (bad sig); dmarc=fail action=none"
    )
    ev = get(analyze_email(m.as_bytes()), "email.auth_fail")
    assert ev.observed["failures"] == ["dkim=fail", "dmarc=fail"]
    m = mk(Received_SPF="softfail (example.test: domain does not designate ...)")
    assert (
        "spf=softfail" in get(analyze_email(m.as_bytes()), "email.auth_fail").observed["failures"]
    )
    m = mk(ARC_Authentication_Results="i=1; mx.example.test; arc=fail")
    assert "arc=fail" in get(analyze_email(m.as_bytes()), "email.auth_fail").observed["failures"]
    ok = mk(Authentication_Results="mx.example.test; spf=pass; dkim=pass; dmarc=pass")
    assert "email.auth_fail" not in names(analyze_email(ok.as_bytes()))


def test_display_name_impersonation() -> None:
    bad = analyze_email(mk(frm="Falcon Demo Bank <help@mailer.example.test>").as_bytes())
    assert get(bad, "email.display_name_impersonation").observed["brands"] == ["falcon_demo_bank"]
    ar = analyze_email(mk(frm="بنك الصقر التجريبي <help@mailer.example.test>").as_bytes())
    assert "email.display_name_impersonation" in names(ar)
    ok = analyze_email(mk(frm="Falcon Demo Bank <a@falcon-demo-bank.test>").as_bytes())
    assert "email.display_name_impersonation" not in names(ok)


def test_reply_to_and_return_path_mismatch() -> None:
    res = analyze_email(
        mk(Reply_To="x@other.example.test", Return_Path="<b@bounce.example.test>").as_bytes()
    )
    assert "email.reply_to_mismatch" in names(res) and "email.return_path_mismatch" in names(res)
    same = analyze_email(mk(Reply_To="x@falcon-demo-bank.test").as_bytes())
    assert "email.reply_to_mismatch" not in names(same)


def test_link_text_vs_href_mismatch() -> None:
    html = (
        '<p>Visit <a href="https://evil.example.test/p">https://falcon-demo-bank.test/login</a></p>'
    )
    res = analyze_email(mk(html=html).as_bytes())
    ev = get(res, "email.link_text_mismatch")
    assert ev.observed["count"] == 1
    assert ("url", "https://evil.example.test/p") in {(c.kind, c.value) for c in res.children}
    fine = '<a href="https://falcon-demo-bank.test/a">https://falcon-demo-bank.test/b</a><a href="https://x.example.test">click here</a>'
    assert "email.link_text_mismatch" not in names(analyze_email(mk(html=fine).as_bytes()))


def test_html_is_parsed_not_rendered_and_scripts_ignored() -> None:
    html = (
        "<html><head><title>t</title><style>x{}</style></head><body><script>alert(1)</script>"
        "<img src='https://tracker.example.test/p.gif'><p>عاجل ارسل رمز التحقق</p></body></html>"
    )
    res = analyze_email(mk(text=None, html=html).as_bytes())
    assert "alert" not in res.body_text and "رمز" in res.body_text
    assert "message.rule.otp_request" in names(res)
    assert all("tracker" not in c.value for c in res.children)  # remote content is not even a child


def test_body_goes_through_message_pipeline_and_h5_children() -> None:
    res = analyze_email(
        mk(subject="مخالفة مرورية", text="ادفع الان hxxps://pay.example[.]test/f").as_bytes()
    )
    assert {"message.rule.fine", "message.rule.payment"} <= names(res)
    assert ("url", "https://pay.example.test/f") in {(c.kind, c.value) for c in res.children}


def test_attachment_type_by_magic_and_hash_only() -> None:
    m = mk()
    exe = b"MZ\x90\x00" + b"\x00" * 60
    m.add_attachment(exe, maintype="application", subtype="pdf", filename="invoice.pdf.exe")
    m.add_attachment(
        b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="../../a.pdf"
    )
    res = analyze_email(m.as_bytes())
    atts = [e.observed for e in res.evidence if e.signal == "email.attachment"]
    assert atts[0]["detected_type"] == "exe" and atts[0]["declared_type"] == "application/pdf"
    assert atts[0]["risky"] and atts[0]["double_extension"]
    assert atts[0]["sha256"] == hashlib.sha256(exe).hexdigest()
    assert atts[1]["detected_type"] == "pdf" and atts[1]["name"] == "a.pdf" and not atts[1]["risky"]


def test_image_attachment_qr_becomes_child() -> None:
    m = mk()
    m.add_attachment(
        qr_png("https://qr.example.test/pay"), maintype="image", subtype="png", filename="q.png"
    )
    res = analyze_email(m.as_bytes())
    assert "image.qr_decoded" in names(res)
    assert ("url", "https://qr.example.test/pay") in {(c.kind, c.value) for c in res.children}


def test_oversized_and_malformed_emails() -> None:
    big = analyze_email(b"Subject: x\r\n\r\n" + b"A" * (MAX_EMAIL_BYTES + 1))
    assert get(big, "email.invalid").observed["reason"] == "too_large" and len(big.evidence) == 1
    assert analyze_email(b"").evidence is not None
    for junk in (
        b"\xff\xfe\x00garbage",
        b"From: \x00\x01\r\n\r\n\xc3\x28",
        b"Content-Type: multipart/mixed\r\n\r\nno boundary",
        b"From: =?utf-8?q?bad?=\r\nReply-To: <<<>>>\r\n\r\nx",
    ):
        res = analyze_email(junk)  # must not raise
        assert isinstance(res.evidence, list)


def test_too_many_parts_and_deep_nesting() -> None:
    m = mk()
    for i in range(MAX_PARTS + 5):
        m.add_attachment(b"x", maintype="application", subtype="octet-stream", filename=f"{i}.bin")
    assert get(analyze_email(m.as_bytes()), "email.invalid").observed["reason"] == "too_many_parts"
    nested = b"".join(
        b"Content-Type: multipart/mixed; boundary=b%d\r\n\r\n--b%d\r\n" % (i, i)
        for i in range(3000)
    )
    res = analyze_email(nested)  # RecursionError or part cap: either way no crash
    assert any(e.signal == "email.invalid" for e in res.evidence) or isinstance(res.children, list)


def test_email_evidence_validates_schema() -> None:
    m = mk(
        frm="Falcon Demo Bank <h@mailer.example.test>",
        Reply_To="r@other.example.test",
        Authentication_Results="x; spf=fail",
        html='<a href="https://a.example.test">https://b.example.test</a>',
    )
    m.add_attachment(b"MZ..", maintype="application", subtype="octet-stream", filename="a.exe")
    validate_evidence(analyze_email(m.as_bytes()).evidence)


def test_registered_email_signal() -> None:
    @dataclass
    class C:
        data: bytes
        text: str | None = None
        url: str | None = None
        input_type: str = "email"
        http: Any = None
        cache: Any = None
        mirror: Any = None
        clock: Any = None
        brands: Any = None

    spec, fn = REGISTRY["email.analyze"]
    assert spec.network == "none"
    out = run_async(fn(C(mk(Received_SPF="fail").as_bytes())))
    assert "email.auth_fail" in {e.signal for e in out}


# ---------------------------------------------------------------- image


def test_sniff_magic_bytes() -> None:
    assert sniff(qr_png("x")) == "png"
    assert sniff(b"\xff\xd8\xff\xe0abc") == "jpeg"
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert sniff(b"GIF89a....") == "gif"
    assert sniff(b"<svg></svg>") is None and sniff(b"") is None


def test_qr_url_decoded_as_child() -> None:
    res = analyze_image(qr_png("https://qr.example.test/pay?id=1"))
    assert res.kind == "png" and res.needs_ocr
    assert [(c.kind, c.value, c.source) for c in res.children] == [
        ("url", "https://qr.example.test/pay?id=1", "image.qr")
    ]
    ev = get(res, "image.qr_decoded")
    assert ev.observed["urls"] == ["hxxps://qr[.]example[.]test/pay?id=1"]  # defanged in evidence


def test_qr_non_url_payload_has_no_children() -> None:
    res = analyze_image(qr_png("hello world"))
    assert res.children == [] and "image.qr_decoded" in names(res)


def test_image_without_qr() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="JPEG")
    res = analyze_image(buf.getvalue())
    assert res.kind == "jpeg" and res.evidence == [] and res.needs_ocr


def test_invalid_images() -> None:
    assert get(analyze_image(b"not an image"), "image.invalid").observed["reason"] == "bad_magic"
    assert (
        get(analyze_image(b"\x89PNG\r\n\x1a\n" + b"junk"), "image.invalid").observed["reason"]
        == "decode_error"
    )
    huge = b"\x89PNG\r\n\x1a\n" + b"0" * MAX_IMAGE_BYTES
    assert get(analyze_image(huge), "image.invalid").observed["reason"] == "too_large"
    # PNG claiming JPEG-ish bytes is caught by magic; a GIF header over PNG data is a format mismatch
    assert "image.invalid" in names(analyze_image(b"GIF89a" + qr_png("x")))


def _png_header_only(w: int, h: int) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + chunk(b"IEND", b"")
    )


def test_decompression_bomb_rejected_without_decoding() -> None:
    res = analyze_image(_png_header_only(60000, 60000))  # 3.6 gigapixels in a ~100 byte file
    assert get(res, "image.invalid").observed["reason"] == "pixel_limit" and not res.needs_ocr
    assert Image.MAX_IMAGE_PIXELS != 25_000_000  # global limit restored


async def test_ocr_hook_is_only_called_for_valid_images() -> None:
    calls: list[int] = []

    async def ocr(b: bytes) -> str | None:
        calls.append(len(b))
        return "نص مستخرج"

    res, text = await analyze_image_with_ocr(qr_png("x"), ocr)
    assert text == "نص مستخرج" and res.needs_ocr and len(calls) == 1
    _res, text = await analyze_image_with_ocr(b"nope", ocr)
    assert text is None and len(calls) == 1
    _res, text = await analyze_image_with_ocr(qr_png("x"), None)
    assert text is None


def test_image_evidence_validates_schema() -> None:
    validate_evidence(
        analyze_image(qr_png("https://qr.example.test/")).evidence + analyze_image(b"x").evidence
    )


def test_base64_payload_roundtrip_in_email_is_decoded_only_for_hashing() -> None:
    raw = b"%PDF-1.7 " + b"x" * 100
    eml = (
        b"From: a@example.test\r\nSubject: s\r\nContent-Type: application/pdf; name=a.pdf\r\n"
        b"Content-Disposition: attachment; filename=a.pdf\r\nContent-Transfer-Encoding: base64\r\n\r\n"
        + base64.encodebytes(raw)
    )
    att = get(analyze_email(eml), "email.attachment").observed
    assert att["sha256"] == hashlib.sha256(raw).hexdigest() and att["detected_type"] == "pdf"


@pytest.mark.parametrize("n", [1])
def test_pillow_global_limit_untouched(n: int) -> None:
    before = Image.MAX_IMAGE_PIXELS
    analyze_image(qr_png("x"))
    assert before == Image.MAX_IMAGE_PIXELS
