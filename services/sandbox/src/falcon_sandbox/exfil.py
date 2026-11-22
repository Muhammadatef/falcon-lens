"""Classify POST targets: messaging-bot APIs, webhooks and form relays are exfil channels (H4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_Rule = tuple[str, "re.Pattern[str] | None", "re.Pattern[str] | None"]

#: (category, host regex or None, path regex or None); a target matches if every given part does.
_PATTERNS: tuple[_Rule, ...] = (
    ("messaging_bot_api", re.compile(r"(^|\.)api\.telegram\.org$"), None),
    (
        "messaging_bot_api",
        None,
        re.compile(r"/bot\d{3,}:[\w-]{3,}/(send\w+|getupdates|forwardmessage)", re.I),
    ),
    (
        "webhook",
        re.compile(r"(^|\.)(discord|discordapp)\.com$"),
        re.compile(r"/api(/v\d+)?/webhooks/", re.I),
    ),
    ("webhook", re.compile(r"^hooks\.slack\.com$"), re.compile(r"^/services/")),
    (
        "webhook",
        re.compile(r"(^|\.)(webhook\.site|requestbin\.\w+|pipedream\.net|hookbin\.com|ngrok(-free)?\.(io|app|dev))$"),
        None,
    ),
    ("webhook", re.compile(r"^script\.google(usercontent)?\.com$"), re.compile(r"/macros/")),
    ("webhook", None, re.compile(r"/webhooks?/[\w-]{6,}", re.I)),
    (
        "form_relay",
        re.compile(
            r"(^|\.)(formspree\.io|formsubmit\.co|getform\.io|web3forms\.com|formcarry\.com"
            r"|formbold\.com|usebasin\.com|submit-form\.com|staticforms\.xyz)$"
        ),
        None,
    ),
)


@dataclass(frozen=True)
class PostTargetClass:
    exfil: bool
    category: str | None  # messaging_bot_api | webhook | form_relay | None


def classify_post_target(url: str) -> PostTargetClass:
    """Is ``url`` a known credential-relay channel? Host/path patterns only, no network I/O."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return PostTargetClass(False, None)
    path = parts.path or ""
    for category, host_re, path_re in _PATTERNS:
        if host_re is not None and not host_re.search(host):
            continue
        if path_re is not None and not path_re.search(path):
            continue
        return PostTargetClass(True, category)
    return PostTargetClass(False, None)
