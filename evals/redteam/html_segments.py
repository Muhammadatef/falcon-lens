"""Fixture HTML -> page features (a stand-in for the sandbox capture, which is not merged yet).

Splits a page into the channels the injection detector understands and builds ``visible_text`` the
way a browser's ``innerText`` would (it keeps CSS-concealed text such as opacity:0 or off-screen
text, and drops display:none / visibility:hidden / [hidden]). Iterative (``html.parser``), bounded
depth, never executes anything. Fixture pages only; live pages go through the sandbox.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from falcon_core.signals.injection import Segment

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
SKIP_TEXT = frozenset(["script", "style", "template", "noscript", "svg", "head"])
MAX_DEPTH = 512
MAX_VISIBLE = 64 * 1024

_HIDE_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|content-visibility\s*:\s*hidden")
_CONCEAL_RE = re.compile(
    r"opacity\s*:\s*0(?:\.0+)?(?:;|$|\s)|font-size\s*:\s*[01](?:px|pt|em|rem)?(?:;|$|\s)|"
    r"(?:left|top|text-indent|margin-left)\s*:\s*-\d{3,}|clip\s*:\s*rect\(0|clip-path\s*:\s*inset\(50%|"
    r"(?:height|width|max-height)\s*:\s*0(?:px)?\s*;.*overflow\s*:\s*hidden|transform\s*:\s*scale\(0\)"
)
_COLOR_RE = re.compile(r"(?<![-\w])color\s*:\s*([#\w(),. ]+)")
_BG_RE = re.compile(r"background(?:-color)?\s*:\s*([#\w(),. ]+)")
_CLASS_RULE_RE = re.compile(r"\.([A-Za-z_][\w-]*)\s*\{([^}]*)\}")


def _style_state(style: str) -> str | None:
    s = style.lower()
    if _HIDE_RE.search(s):
        return "hidden"
    if _CONCEAL_RE.search(s):
        return "concealed"
    c, b = _COLOR_RE.search(s), _BG_RE.search(s)
    if c and b and c.group(1).strip(" ;") == b.group(1).strip(" ;"):
        return "concealed"
    return None


@dataclass
class PageFeatures:
    title: str = ""
    visible_text: str = ""
    segments: list[Segment] = field(default_factory=list)
    password_fields: int = 0
    forms: int = 0
    hidden_chars: int = 0
    visible_chars: int = 0
    max_depth_seen: int = 0

    def accessible_text(self) -> str:
        """alt + aria-label text: user-facing for screen-reader users, so the extractor may see it."""
        return "\n".join(s.text for s in self.segments if s.channel in ("alt", "aria"))


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.f = PageFeatures()
        self.stack: list[tuple[str, str]] = []  # (tag, state) state in visible|concealed|hidden|skip
        self.class_rules: dict[str, str] = {}
        self._in_style = False
        self._in_title = False
        self._visible: list[str] = []
        self._buf: list[tuple[str, str]] = []  # (state, text) contiguous runs

    def _state(self) -> str:
        return self.stack[-1][1] if self.stack else "visible"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        parent = self._state()
        state = parent
        if tag in SKIP_TEXT:
            state = "skip"
        elif parent not in ("hidden", "skip"):
            if "hidden" in a or (tag == "input" and a.get("type", "").lower() == "hidden"):
                state = "hidden"
            else:
                st = _style_state(a.get("style", ""))
                for cls in a.get("class", "").split():
                    st = st or _style_state(self.class_rules.get(cls, ""))
                if st == "hidden" or (st == "concealed" and parent == "visible"):
                    state = st
        if tag == "style":
            self._in_style = True
        if tag == "title":
            self._in_title = True
        if tag == "form":
            self.f.forms += 1
        if tag == "input" and a.get("type", "").lower() == "password":
            self.f.password_fields += 1
        for attr, channel in (("alt", "alt"), ("aria-label", "aria"), ("title", "title"), ("placeholder", "aria")):
            if a.get(attr):
                self.f.segments.append(Segment(a[attr], channel))  # type: ignore[arg-type]
        if tag == "input" and a.get("type", "").lower() == "hidden" and a.get("value"):
            self.f.segments.append(Segment(a["value"], "hidden"))
        if tag == "meta" and a.get("content") and a.get("name", "").lower() in ("description", "keywords", "robots"):
            self.f.segments.append(Segment(a["content"], "meta"))
        if tag not in VOID and len(self.stack) < MAX_DEPTH:
            self.stack.append((tag, state))
            self.f.max_depth_seen = max(self.f.max_depth_seen, len(self.stack))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        if tag == "title":
            self._in_title = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in ("p", "div", "li", "h1", "h2", "h3", "br", "tr", "section", "label", "button", "pre"):
            self._buf.append(("break", "\n"))

    def handle_data(self, data: str) -> None:
        if self._in_style:
            for m in _CLASS_RULE_RE.finditer(data):
                self.class_rules[m.group(1)] = m.group(2)
            return
        if self._in_title:
            self.f.title += data
            return
        state = self._state()
        if state == "skip" or not data.strip():
            if data and state != "skip":
                self._buf.append(("break", " "))
            return
        self._buf.append((state, data))

    def handle_comment(self, data: str) -> None:
        if data.strip():
            self.f.segments.append(Segment(data.strip(), "comment"))

    def finish(self) -> PageFeatures:
        runs: dict[str, list[str]] = {"visible": [], "concealed": [], "hidden": []}
        inner: list[str] = []
        for state, text in self._buf:
            if state == "break":
                inner.append(text)
                continue
            runs[state].append(text)
            if state in ("visible", "concealed"):
                inner.append(text)
        for ch in ("visible", "concealed", "hidden"):
            joined = " ".join(t.strip() for t in runs[ch] if t.strip())
            if joined:
                self.f.segments.insert(0, Segment(joined, ch))  # type: ignore[arg-type]
        if self.f.title.strip():
            self.f.segments.append(Segment(self.f.title.strip(), "title"))
        text = re.sub(r"[ \t]+", " ", "".join(inner))
        self.f.visible_text = re.sub(r"\s*\n\s*", "\n", text).strip()[:MAX_VISIBLE]
        self.f.visible_chars = sum(len(t) for t in runs["visible"])
        self.f.hidden_chars = sum(len(t) for t in runs["concealed"]) + sum(len(t) for t in runs["hidden"])
        self.f.title = self.f.title.strip()[:512]
        return self.f


def page_features(html: str) -> PageFeatures:
    p = _Parser()
    p.feed(html)
    p.close()
    return p.finish()
