"""Canary token and leak detection on model output (THREAT_MODEL §I, ``fl_canary_leak_total``).

The canary is ``FLC-<12 hex>``. A reply leaks it when, after ``normalise_text``, lower-casing and
dropping every non-alphanumeric character, it contains any ``WINDOW``-character run of the hex
part, forwards or reversed. Base64-looking runs in the reply are decoded and checked the same way.
That catches the full token, the bare hex, partial hex, spaced / dashed / zero-width-split tokens,
reversed tokens and base64. With a random 48-bit hex part, a false match on ordinary text is
negligible.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets

from falcon_core.llm.textnorm import normalise_text

WINDOW = 6
_B64_RUN_RE = re.compile(r"[A-Za-z0-9+/]{12,}={0,2}")


def new_canary() -> str:
    return f"FLC-{secrets.token_hex(6)}"


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", normalise_text(text).lower())


def _windows(hexpart: str) -> set[str]:
    h = hexpart.lower()
    if len(h) <= WINDOW:
        return {h}
    return {h[i : i + WINDOW] for i in range(len(h) - WINDOW + 1)}


def _hit(squashed: str, windows: set[str]) -> bool:
    rev = squashed[::-1]
    return any(w in squashed or w in rev for w in windows)


def leaks(text: str, canary: str) -> bool:
    hexpart = canary.split("-", 1)[-1]
    windows = _windows(hexpart)
    if _hit(_squash(text), windows):
        return True
    for run in _B64_RUN_RE.findall(text.replace("\n", "")):
        try:
            decoded = base64.b64decode(run + "=" * (-len(run) % 4), validate=False)
        except (binascii.Error, ValueError):
            continue
        if _hit(_squash(decoded.decode("latin-1")), windows):
            return True
    return False
