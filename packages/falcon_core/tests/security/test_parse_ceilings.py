"""Fail-closed parsing, round 2: the unscanned middle, encodings, hard ceilings, data: URIs.

Fixtures only: invented brand "Falcon Demo Bank", reserved hosts (``.example``).
"""

from __future__ import annotations

import asyncio
import base64
import quopri
from email.message import EmailMessage

import pytest

from falcon_core.cascade.evidence import from_signal
from falcon_core.cascade.inputs import run_input
from falcon_core.scoring import ArbiterContext, score
from falcon_core.signals.email.analyze import MAX_EMAIL_BYTES, analyze_email
from falcon_core.signals.limits import HARD_MAX_EMAIL_BYTES, HARD_MAX_MESSAGE_CHARS, InputTooLarge
from falcon_core.signals.message.analyze import analyze_message

LINK = "https://falcon-demo-bank-verify.example/login"
RANK = {"no_warning_signs": 0, "suspicious": 1, "dangerous": 2}
HDR = b"From: Falcon Demo Bank <alerts@falcon-demo-bank-verify.example>\r\nSubject: Notice\r\nMIME-Version: 1.0\r\n"
PADLINE = b"x" * 76 + b"\r\n"
CORE = f"Falcon Demo Bank: urgent, verify at {LINK}\nSend the OTP code\n"


def _links(data: bytes) -> set[str]:
    return {c.value for c in analyze_email(data).children if c.kind == "url"}


def _urls(text: str) -> set[str]:
    return {c.value for c in analyze_message(text).children if c.kind == "url"}


def _msg_rank(text: str) -> int:
    res = analyze_message(text)
    r = score([from_signal(e) for e in res.evidence], None, ArbiterContext(input_type="message"))
    return RANK[r.verdict]


def _email_rank(data: bytes) -> tuple[int, set[str]]:
    res = analyze_email(data)
    ev = [from_signal(e) for e in res.evidence] + [from_signal(e) for e in analyze_message(res.body_text).evidence]
    r = score(ev, None, ArbiterContext(input_type="email"))
    return RANK[r.verdict], {c.value for c in res.children if c.kind == "url"}


def _single(body: bytes, cte: str | None) -> bytes:
    h = HDR + b"Content-Type: text/plain\r\n"
    if cte:
        h += b"Content-Transfer-Encoding: " + cte.encode() + b"\r\n"
    return h + b"\r\n" + body


def _encode(body: bytes, cte: str | None) -> bytes:
    if cte == "base64":
        return base64.encodebytes(body)
    if cte == "quoted-printable":
        return quopri.encodestring(body)
    return body


@pytest.mark.parametrize("cte", [None, "base64", "quoted-printable"])
@pytest.mark.parametrize(("before", "after"), [(70_000, 70_000), (70_000, 400_000), (2_200_000, 400_000)])
def test_link_in_the_middle_of_large_padding_is_judged(cte: str | None, before: int, after: int) -> None:
    body = PADLINE * (before // 78) + b"\r\npay at " + LINK.encode() + b" now\r\n" + PADLINE * (after // 78)
    data = _single(_encode(body, cte), cte)
    assert LINK in _links(data)
    flagged = any(e.signal == "email.limit_exceeded" for e in analyze_email(data).evidence)
    assert flagged == (len(data) > MAX_EMAIL_BYTES)


@pytest.mark.parametrize("cte", ["base64", "quoted-printable", None])
def test_link_in_a_late_encoded_part_after_2mb_padding(cte: str | None) -> None:
    late = _encode(f"pay at {LINK}\r\n".encode(), cte)
    ctehdr = f"Content-Transfer-Encoding: {cte}\r\n".encode() if cte else b""
    data = (
        HDR
        + b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n--B\r\nContent-Type: text/plain\r\n\r\n'
        + PADLINE * (2_200_000 // 78)
        + b"\r\n--B\r\nContent-Type: text/plain\r\n"
        + ctehdr
        + b"\r\n"
        + late
        + b"\r\n--B--\r\n"
    )
    assert LINK in _links(data)


def test_link_in_a_base64_block_of_an_unparseable_email() -> None:
    nested = b"".join(b"Content-Type: multipart/mixed; boundary=b%d\r\n\r\n--b%d\r\n" % (i, i) for i in range(3000))
    data = HDR + nested + b"\r\n" + base64.encodebytes(f"pay at {LINK}".encode()) + b"\r\n"
    assert LINK in _links(data)


def test_qp_soft_break_split_link_is_rejoined() -> None:
    body = b"pay at https://falcon-demo-bank-verify.exa=\r\nmple/login now\r\n"
    assert LINK in _links(_single(body, "quoted-printable"))


def test_link_split_inside_angle_brackets_is_rejoined() -> None:
    assert LINK in _urls("pay at <https://falcon-demo-bank-verify.example/\nlogin> now")


def test_html_attachment_links_are_judged() -> None:
    m = EmailMessage()
    m["From"] = "Falcon Demo Bank <alerts@falcon-demo-bank-verify.example>"
    m["Subject"] = "Notice"
    m.set_content("see attached\n")
    m.add_attachment(
        f'<html><a href="{LINK}">open</a></html>'.encode(), maintype="text", subtype="html", filename="notice.html"
    )
    assert LINK in _links(m.as_bytes())


def test_message_link_in_the_unscanned_middle_is_judged() -> None:
    text = "A" * 60_000 + f" pay at {LINK} " + "B" * 60_000
    res = analyze_message(text)
    assert LINK in {c.value for c in res.children}
    assert any(e.signal == "message.limit_exceeded" for e in res.evidence)
    assert _msg_rank(text) >= 1


@pytest.mark.parametrize("pad", [70_000, 130_000])
@pytest.mark.parametrize("junk", [".", "\n", "\x00", "\u200b"])
def test_message_padding_on_both_sides_never_lowers_label_or_links(pad: int, junk: str) -> None:
    base = f"Falcon Demo Bank: urgent, verify at {LINK} . Send the OTP code"
    padded = junk * pad + " " + base + " " + junk * pad
    assert _msg_rank(padded) >= _msg_rank(base)
    assert {u.lower() for u in _urls(base)} <= {u.lower() for u in _urls(padded)}


def test_hard_ceilings_refuse_instead_of_labelling() -> None:
    with pytest.raises(InputTooLarge):
        analyze_message("a" * (HARD_MAX_MESSAGE_CHARS + 1))
    with pytest.raises(InputTooLarge):
        analyze_email(HDR + b"\r\n" + b"a" * HARD_MAX_EMAIL_BYTES)


def test_cascade_does_not_turn_too_large_into_a_verdict() -> None:
    class _D:
        registry = None

    class _C:
        d = _D()

    with pytest.raises(InputTooLarge):
        asyncio.run(run_input(_C(), "v", "message", b"a" * (HARD_MAX_MESSAGE_CHARS + 1), None))  # type: ignore[arg-type]


@pytest.mark.parametrize("size", [3 * 1024 * 1024, 6 * 1024 * 1024])
def test_email_padding_on_both_sides_never_lowers_label(size: int) -> None:
    ref = _email_rank(HDR + b"Content-Type: text/plain\r\n\r\n" + CORE.encode())
    pad = b"\x00" * (size // 2)
    got = _email_rank(HDR + b"Content-Type: text/plain\r\n\r\n" + pad + CORE.encode() + pad)
    assert got[0] >= ref[0]
    assert ref[1] <= got[1]


def test_data_uri_is_informational_unless_active() -> None:
    plain = "open data:text/plain;base64," + base64.b64encode(b"hello").decode()
    active = "open data:text/html;base64," + base64.b64encode(b"<form action=x><input name=p></form>").decode()
    r1 = {e.signal for e in analyze_message(plain).evidence}
    r2 = {e.signal for e in analyze_message(active).evidence}
    assert "message.data_uri" in r1 and "message.data_uri_active" not in r1
    assert {"message.data_uri", "message.data_uri_active"} <= r2
    ev = [from_signal(e) for e in analyze_message(plain).evidence if e.signal == "message.data_uri"]
    w = score(ev, None, ArbiterContext(input_type="message"))
    assert all(e.weight == 0.0 for e in w.weighted_evidence)
    ev2 = [from_signal(e) for e in analyze_message(active).evidence if e.signal == "message.data_uri_active"]
    assert score(ev2, None, ArbiterContext(input_type="message")).weighted_evidence[0].weight == 2.0


def test_email_data_href_is_seen() -> None:
    m = EmailMessage()
    m["From"] = "a@falcon-demo-bank-verify.example"
    m["Subject"] = "x"
    m.set_content("hello")
    m.add_alternative('<a href="data:text/html,%3Cscript%3E1%3C/script%3E">go</a>', subtype="html")
    assert any(e.signal == "message.data_uri_active" for e in analyze_email(m.as_bytes()).evidence)
