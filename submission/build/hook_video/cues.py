# ruff: noqa: E501
"""Cue sheet of the Falcon Lens hook film: logo sting, cold open, the Falcon's live steps, end card.

One source of truth for picture and sound. `build_timeline()` turns the lines below plus the measured clip
lengths into absolute times; `audio.py` lays the clips on those times and the page in `composition/` animates
to the same times, so a caption can never drift from the voice.

Rules this file encodes (CLAUDE.md, demo-kit/hook-video/README.md):
- Falcon's captions are the product's own spoken lines, word for word (a test compares them with
  `packages/falcon_core/src/falcon_core/i18n/voice_script.yaml`).
- The only bank is the invented "Falcon Demo Bank" and the only link is the defanged fixture host.
- The verdict word is «خطِر». The word for "harmless" never appears, in either language.
- No statistic and no score is shown: nothing in the film is a measured number.
- The film is labelled «تمثيل — Dramatisation» on every frame.

Standard library only, so the tests can import it without the render tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

FPS = 60
VARIANTS = ("sequence", "final", "intro")

# ── fixed scene lengths (seconds) ────────────────────────────────────────────────────────────────
INTRO = 3.4  # logo sting; the hits below sit on a 140 bpm grid
BEAT = 60.0 / 140.0
INTRO_HIT1 = 3 * BEAT  # the lens ring snaps into focus
INTRO_TAPS = (INTRO_HIT1 + BEAT, INTRO_HIT1 + 1.5 * BEAT)
INTRO_HIT2 = INTRO_HIT1 + 2 * BEAT  # the wordmark lands
INTRO_OUT = 3.06  # whoosh into the cold open
COLD_SEQUENCE = 4.5  # animated cold open when there is no footage
END = 3.05  # end card; a deck holds on its last frame
VERDICT_PRE = 0.50  # the evidence converges on the lens before the earcon
EARCON = 0.54  # web/public/voice/sfx/dangerous.mp3
HARD_MAX = 60.0  # the owner's hard limit for the whole hook

# ── on-screen fixture text (never a real brand, number or live address) ──────────────────────────
BANK_AR = "بنك الصقر التجريبي"
BANK_EN = "Falcon Demo Bank"
SENDER = "FDB-TEST"
FIXTURE_NOTE = "رسالة تمثيلية — TEST FIXTURE"
LINK_DEFANGED = "falcon-demo-bank-secure[.]test/login"
HOST_LOOKALIKE = "falcon-demo-bank-secure[.]test"
HOST_OFFICIAL = "falcon-demo-bank[.]test"  # the verified domain of the invented brand in data/brands.yaml
ADDED_WORD = "-secure"
# demo-kit/messages/01-arabic-sms-phishing.txt with the link defanged, split so the page can light up phrases.
SMS_PARTS: tuple[tuple[str, str], ...] = (
    ("plain", "عزيزي العميل، حسابك في"),
    ("brand", BANK_AR),
    ("urgent", "سيتم تجميده خلال ساعة."),
    ("plain", "أرسل"),
    ("otp", "رمز التحقق"),
    ("plain", "الذي وصلك وادخل على"),
    ("link", LINK_DEFANGED),
    ("plain", "للتحديث فوراً"),
)
LABEL = "تمثيل — Dramatisation"
TAGLINE_AR = "اسأل الصقر قبل لا تضغط"
TAGLINE_EN = "Ask the falcon before you tap."
WORDMARK_AR = "عدسة الصقر"
WORDMARK_EN = "Falcon Lens"
SITE = "falconlens.app"
EVENT = "ScamShield AI · 2026"
# Plain-text competition credit, end card only, small type. It names the event and says the entry is independent.
CREDIT_EN = (
    "Abu Dhabi Police × 42 — ScamShield AI hackathon entry · independent project, ready to connect, not connected"
)
CREDIT_AR = "مشروع مستقل مشارك في هاكاثون ScamShield AI — جاهز للربط وغير مربوط"
FICTION_AR = "تمثيل. الشخصيات والرسالة والبنك من نسج الخيال. «بنك الصقر التجريبي» اسم مُختلق لأغراض العرض."
FICTION_EN = (
    "Dramatisation. The characters, the message and the bank are fictional. “Falcon Demo Bank” is an invented name."
)
AI_PEOPLE_AR = "الأشخاص والأصوات مولَّدة بالذكاء الاصطناعي."
AI_PEOPLE_EN = "People and voices are AI-generated."

# What each tier found, as the product words it (web/lib/voice-script.ts FINDINGS / CRED_LINES / find.brand.*).
# These are the finding lines for the fixture: url.combosquat on the look-alike host, the brand claim and the
# card fields of services/fixtures/sites/phish/login.html, and message.scam_intent for the wording.
FINDINGS: dict[str, tuple[str, str]] = {
    "lists": ("لا شيء لافت", "Known lists: nothing notable"),  # voice.prog.nothing
    "address": ("العنوان يضيف كلمة لاسم جهة معروفة.", "The address adds a word to a well-known name."),
    "page_brand": (
        "تدّعي إنها بنك الصقر التجريبي والنطاق مو لهم.",
        "It claims to be Falcon Demo Bank, but the domain is not theirs.",
    ),
    "page_form": ("الصفحة تطلب بيانات بطاقتك.", "The page asks for your card details."),
    "ai": ("الرسالة تطلب رمز أو فلوس بأسلوب النصابين.", "The message asks for a code or money the way scammers do."),
}
ARBITER_NOTE_AR = "الدرجة يحسبها المحكّم من الأدلة، لا الذكاء الاصطناعي"
ARBITER_NOTE_EN = "The arbiter sets the score from the evidence, not the AI."


@dataclass(frozen=True)
class Line:
    """One spoken line of the Falcon: a pre-generated product clip and its caption."""

    key: str  # product voice-script key; the clip file is ar_ae.<key>.mp3
    ar: str  # exact spoken text
    en: str  # the product's English line for the same key
    scene: str
    step: int | None = None  # row number in the live-steps list
    gap: float = 0.13  # silence before the clip (the product leaves 150 to 250 ms; the hook is cut a little tighter)


# The answer, in the order the product speaks it for one copied message.
FALCON: tuple[Line, ...] = (
    Line("wake.ack", "هلا، سامعك.", "Yes, I'm listening.", "wake", None, 0.0),
    Line("found.1", "لقيت مسج واحد.", "I found one message.", "found", 1),
    Line(
        "investigator.start.1",
        "بصير يشيّك على المسج الأول.",
        "Baseer, the Investigator, is checking the first message.",
        "baseer",
        2,
    ),
    Line("investigator.lists", "أطابقه مع قوائم النصب المعروفة.", "Checking known scam lists.", "lists", 3),
    Line(
        "investigator.address",
        "أشوف عنوان الموقع، يمكن فيه تشابه مخادع.",
        "Checking the web address for look-alike tricks.",
        "address",
        4,
    ),
    Line(
        "investigator.page",
        "أفتح الصفحة في متصفح معزول عندنا، وما يندخل فيها شي.",
        "Opening the page in our isolated browser. Nothing is typed.",
        "page",
        5,
    ),
    Line(
        "investigator.ai_second_look_local",
        "نتأكد بنموذج الذكاء الاصطناعي اللغوي حقنا.",
        "Checking with our AI language model (LLM).",
        "ai",
        6,
    ),
    Line(
        "investigator.arbiter_result.dangerous",
        "الحكم النهائي: المسج خطر!",
        "The arbiter's decision: dangerous.",
        "verdict",
        7,
        0.10,
    ),
    Line("sentinel.handover", "أسلّم النتايج لدرع.", "Handing the results to Dir, the Sentinel.", "dir", 8, 0.12),
    Line(
        "sentinel.linked.3",
        "درع ربط ثلاث مسجات في حملة نصب وحدة.",
        "Dir linked three reports into one campaign.",
        "dir",
        9,
        0.14,
    ),
    Line("todo.lead", "نصيحتي لك:", "What to do now:", "todo", 10, 0.14),
    Line("todo.link", "لا تضغط على الرابط، ولا تدوس عليه.", "Don't tap the link.", "todo", 10, 0.12),
    Line("todo.otp", "ولا تعطي حد الرمز أبداً.", "Never share a code with anyone.", "todo", 10, 0.14),
)
# Wording that is in an open pull request and already in the generated clips, so it is not in the YAML on main yet.
PENDING_SCRIPT = {"investigator.ai_second_look_local": "PR #157 (generic LLM step wording)"}
SFX_VERDICT = "dangerous.mp3"


@dataclass(frozen=True)
class LiveLine:
    """A line spoken by an actor in the owner's footage; `src` is where the speech sits in that file."""

    id: str
    who: str  # "abu_saeed" or "saeed" (both fictional)
    ar: str
    en: str
    src: tuple[float, float]


SPEAKERS = {
    "falcon": ("الصقر", "Falcon"),
    "abu_saeed": ("أبو سعيد", "Abu Saeed"),
    "saeed": ("سعيد", "Saeed"),
    "you": ("أنت", "You"),
}
# On-screen words of the animation-only cut, where no actor speaks. They are titles, not captions of speech.
TITLE_WAIT = ("لحظة… قبل لا تضغط.", "Wait. Before you tap…")
TITLE_HEY = ("يا صقر!", "Hey Falcon!")
# Speech positions measured on deliverables/media/hook.mp4 (65.6 s cut, 24 Nov). Dialogue is the kit's D3 to D10.
LIVE: dict[str, LiveLine] = {
    "frozen": LiveLine(
        "frozen",
        "abu_saeed",
        "«حسابك بيتجمّد خلال ساعة»…",
        "“Your account will be frozen within the hour”…",
        (15.80, 17.74),
    ),
    "what_now": LiveLine("what_now", "abu_saeed", "شو أسوّي الحين؟", "What do I do now?", (18.12, 19.06)),
    "dont_tap": LiveLine("dont_tap", "saeed", "لا تضغط على شي.", "Don't tap anything.", (19.30, 20.42)),
    "say": LiveLine("say", "saeed", "وقول: يا صقر.", "and say: Hey Falcon.", (23.36, 24.86)),
    "hey": LiveLine("hey", "abu_saeed", "يا صقر!", "Hey Falcon!", (25.26, 26.54)),
    "check": LiveLine("check", "abu_saeed", "شيّك مسجاتي.", "Check my messages.", (28.88, 29.80)),
    "thanks": LiveLine(
        "thanks", "abu_saeed", "لا، مشكور يا صقر.", "No… thank you, Falcon.", (54.62, 56.16)
    ),  # optional closing beat
}
# Sound taken from the footage (source in, source out) and the picture shown over it. The runs are butt-joined:
# the son's line is cut from «لا تضغط على شي.» to «وقول: يا صقر.» and the copy step is shown on screen instead
# (the product checks what the user copied, so the film must show the copy).
RUN_A = (15.74, 20.50)
RUN_B1 = (23.28, 24.94)
RUN_B2 = (25.20, 26.62)
RUN_CHECK = (28.84, 29.88)
RUN_THANKS = (54.30, 56.28)
PLATE = (12.60, 12.78)  # the two-shot in the majlis: its six clean frames, then held as a blurred plate
PIC_SON = (19.60, 20.50)  # Saeed pouring coffee (the shot starts on frame 588)
PIC_HEY = (25.87, 26.78)  # Abu Saeed, close, teal light on his glasses (clean between two dissolves)
PIC_THANKS = (54.30, 56.28)  # Abu Saeed smiling
COLD_LEAD = 0.38  # buzz and the message landing before the first word


def split_words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def spread_words(text: str, t0: float, t1: float) -> list[list[Any]]:
    """Start time of each word, spread over [t0, t1] by letter count (used when no alignment is available)."""
    words = split_words(text)
    weights = [max(1, len(re.sub(r"[^\w]", "", w))) + 0.6 for w in words]
    total = sum(weights)
    out: list[list[Any]] = []
    acc = 0.0
    for w, k in zip(words, weights, strict=True):
        out.append([w, round(t0 + (t1 - t0) * acc / total, 3)])
        acc += k
    return out


@dataclass
class Timeline:
    variant: str
    fps: int = FPS
    t: float = 0.0
    scenes: list[dict[str, Any]] = field(default_factory=list)
    lines: list[dict[str, Any]] = field(default_factory=list)
    marks: dict[str, float] = field(default_factory=dict)
    clips: list[dict[str, Any]] = field(default_factory=list)  # Falcon clips and the earcon: {file, t0, kind}
    live_audio: list[dict[str, Any]] = field(default_factory=list)  # {src0, src1, t0}
    live_pic: list[dict[str, Any]] = field(default_factory=list)  # {id, src0, src1, t0, t1}

    def scene(self, sid: str) -> None:
        if self.scenes:
            self.scenes[-1]["t1"] = round(self.t, 3)
        self.scenes.append({"id": sid, "t0": round(self.t, 3), "t1": round(self.t, 3)})

    def wait(self, seconds: float) -> None:
        self.t += seconds

    def mark(self, name: str, at: float | None = None) -> None:
        self.marks[name] = round(self.t if at is None else at, 3)

    def say(self, line: Line, clip_len: dict[str, float], words: dict[str, list[list[Any]]] | None = None) -> None:
        self.t += line.gap
        t0, dur = self.t, clip_len[line.key]
        rel = (words or {}).get(line.key)
        timed = [[w, round(t0 + dt, 3)] for w, dt in rel] if rel else spread_words(line.ar, t0 + 0.03, t0 + dur - 0.05)
        self.lines.append(
            {"id": line.key, "who": "falcon", "ar": line.ar, "en": line.en, "scene": line.scene, "step": line.step,
             "t0": round(t0, 3), "t1": round(t0 + dur, 3), "words": timed}
        )  # fmt: skip
        self.clips.append({"file": f"ar_ae.{line.key}.mp3", "t0": round(t0, 3), "kind": "voice"})
        self.t = t0 + dur

    def run(self, src: tuple[float, float], lines: tuple[str, ...], at: float | None = None) -> float:
        """Lay a stretch of the footage's sound at `at` (default: now). Returns the output time of source time 0."""
        t0 = self.t if at is None else at
        offset = t0 - src[0]
        self.live_audio.append({"src0": src[0], "src1": src[1], "t0": round(t0, 3)})
        for lid in lines:
            ll = LIVE[lid]
            a, b = ll.src[0] + offset, ll.src[1] + offset
            self.lines.append(
                {"id": ll.id, "who": ll.who, "ar": ll.ar, "en": ll.en, "scene": self.scenes[-1]["id"], "step": None,
                 "t0": round(a, 3), "t1": round(b, 3), "words": spread_words(ll.ar, a, b - 0.08)}
            )  # fmt: skip
        if at is None:
            self.t = t0 + (src[1] - src[0])
        return offset

    def picture(self, pid: str, src: tuple[float, float], offset: float) -> None:
        self.live_pic.append(
            {
                "id": pid,
                "src0": src[0],
                "src1": src[1],
                "t0": round(src[0] + offset, 3),
                "t1": round(src[1] + offset, 3),
            }
        )

    def title(self, lid: str, who: str, text: tuple[str, str], t0: float, t1: float) -> None:
        """Words on screen that nobody speaks (the animation-only cut)."""
        self.lines.append(
            {"id": lid, "who": who, "ar": text[0], "en": text[1], "scene": self.scenes[-1]["id"], "step": None,
             "t0": round(t0, 3), "t1": round(t1, 3), "words": spread_words(text[0], t0, t0 + min(0.7, t1 - t0))}
        )  # fmt: skip

    def close(self) -> dict[str, Any]:
        self.scenes[-1]["t1"] = round(self.t, 3)
        frames = round(self.t * self.fps)
        return {
            "variant": self.variant, "fps": self.fps, "frames": frames, "duration": round(frames / self.fps, 4),
            "scenes": self.scenes, "lines": self.lines, "marks": self.marks, "clips": self.clips,
            "live_audio": self.live_audio, "live_pic": self.live_pic,
        }  # fmt: skip


def _intro(tl: Timeline) -> None:
    tl.scene("intro")
    tl.mark("intro.hit1", INTRO_HIT1)
    tl.mark("intro.tap1", INTRO_TAPS[0])
    tl.mark("intro.tap2", INTRO_TAPS[1])
    tl.mark("intro.hit2", INTRO_HIT2)
    tl.mark("intro.out", INTRO_OUT)
    tl.wait(INTRO)


def _answer(tl: Timeline, clip_len: dict[str, float], words: dict[str, list[list[Any]]] | None) -> None:
    """The Falcon's answer, step by step: the same order and the same clips as a real check of one message."""
    by_scene: dict[str, list[Line]] = {}
    for ln in FALCON:
        by_scene.setdefault(ln.scene, []).append(ln)
    for sid in ("found", "baseer", "lists", "address", "page", "ai"):
        tl.scene(sid)
        for ln in by_scene[sid]:
            tl.say(ln, clip_len, words)
    tl.scene("verdict")
    tl.mark("verdict.converge")
    tl.wait(VERDICT_PRE)
    tl.mark("verdict.slam")  # the frame «خطِر» appears, and the earcon
    tl.clips.append({"file": SFX_VERDICT, "t0": round(tl.t, 3), "kind": "earcon"})
    tl.wait(EARCON)
    for ln in by_scene["verdict"]:
        tl.say(ln, clip_len, words)
    tl.wait(0.16)
    tl.scene("dir")
    for ln in by_scene["dir"]:
        tl.say(ln, clip_len, words)
    linked = tl.lines[-1]
    tl.mark("dir.ping1", linked["t0"] + 0.30)
    tl.mark("dir.ping2", linked["t0"] + 0.70)
    tl.mark("dir.link", linked["t0"] + 1.25)
    tl.wait(0.12)
    tl.scene("todo")
    for ln in by_scene["todo"]:
        tl.say(ln, clip_len, words)
    tl.wait(0.2)


def _end(tl: Timeline) -> None:
    tl.scene("end")
    tl.mark("end.hit", tl.t + 0.50)
    tl.wait(END)


def build_timeline(
    variant: str,
    clip_len: dict[str, float],
    words: dict[str, list[list[Any]]] | None = None,
    fps: int = FPS,
    relief: bool = False,
) -> dict[str, Any]:
    """Absolute times for one cut. `clip_len` maps a script key to the length of its clip in seconds.

    `sequence` is the animation alone, `final` opens on the owner's footage, `intro` is the logo sting.
    `relief` adds the actor's closing thank-you to `final` (about two seconds longer).
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    tl = Timeline(variant, fps)
    _intro(tl)
    if variant == "intro":
        return tl.close()
    ack = FALCON[0]
    tl.scene("cold")
    c0 = tl.t
    tl.mark("cold.buzz", c0 + 0.10)
    tl.mark("cold.land", c0 + 0.26)
    if variant == "sequence":
        for name, dt in (("urgent", 1.00), ("finger", 2.00), ("beat1", 2.25), ("beat2", 3.10), ("stop", 3.55)):
            tl.mark(f"cold.{name}", c0 + dt)
        tl.title("title.wait", "title", TITLE_WAIT, c0 + 3.3, c0 + COLD_SEQUENCE + 0.55)
        tl.wait(COLD_SEQUENCE)
        tl.scene("wake")
        tl.mark("copy.press", tl.t + 0.05)  # the finger leaves the link and long-presses the message
        tl.mark("copy.done", tl.t + 0.65)
        tl.mark("mark.in", tl.t + 0.75)  # the sleeping mark appears
        tl.mark("wake.say", tl.t + 0.95)  # «يا صقر» is heard
        tl.mark("wake.chime", tl.t + 1.50)
        tl.title("title.hey", "you", TITLE_HEY, tl.t + 0.95, tl.t + 1.75)
        tl.wait(1.62)
        tl.mark("wake.snap")
        tl.wait(0.18)
        tl.say(ack, clip_len, words)
        tl.wait(0.12)
    else:
        tl.picture("plate", PLATE, c0 - PLATE[0])
        off = tl.run(RUN_A, ("frozen", "what_now", "dont_tap"), at=c0 + COLD_LEAD)
        tl.mark("cold.urgent", LIVE["frozen"].src[0] + off + 0.50)
        tl.mark("cold.finger", LIVE["what_now"].src[0] + off - 0.35)
        tl.mark("cold.beat1", LIVE["what_now"].src[0] + off)
        tl.mark("cold.beat2", LIVE["what_now"].src[1] + off - 0.05)
        tl.mark("cold.stop", LIVE["dont_tap"].src[0] + off + 0.06)  # «لا تضغط»: the finger freezes
        tl.t = PIC_SON[0] + off
        tl.scene("son")
        tl.picture("son", PIC_SON, off)
        tl.t = RUN_A[1] + off
        tl.scene("tease")
        tl.mark("copy.press", tl.t + 0.05)
        tl.mark("copy.done", tl.t + 0.65)
        tl.mark("mark.in", tl.t + 0.75)
        tl.run(RUN_B1, ("say",))
        off = tl.run(RUN_B2, ("hey",))
        tl.mark("wake.say", LIVE["hey"].src[0] + off)
        tl.t = PIC_HEY[0] + off
        tl.scene("call")
        tl.picture("hey", PIC_HEY, off)
        tl.mark("wake.chime", RUN_B2[1] + off - 0.02)  # the Falcon hears him while he is still on screen
        tl.t = PIC_HEY[1] + off
        tl.scene("wake")
        tl.mark("wake.snap")
        tl.wait(0.16)
        tl.say(ack, clip_len, words)
        tl.wait(0.08)
        tl.scene("listen")
        tl.run(RUN_CHECK, ("check",))
    _answer(tl, clip_len, words)
    if variant == "final" and relief:
        tl.scene("relief")
        off = tl.run(RUN_THANKS, ("thanks",))
        tl.picture("thanks", PIC_THANKS, off)
    _end(tl)
    return tl.close()


def steps() -> list[dict[str, Any]]:
    """The numbered live-steps rows: one row per step number, text joined when several clips share a row."""
    rows: dict[int, dict[str, Any]] = {}
    for ln in FALCON:
        if ln.step is None:
            continue
        row = rows.setdefault(ln.step, {"n": ln.step, "keys": [], "scene": ln.scene})
        row["keys"].append(ln.key)
    return [rows[n] for n in sorted(rows)]


def page_data(variant: str) -> dict[str, Any]:
    """Everything the page prints that is not a spoken line: fixture text, findings, labels, the end card."""
    return {
        "sms": [list(p) for p in SMS_PARTS], "sender": SENDER, "fixtureNote": FIXTURE_NOTE, "link": LINK_DEFANGED,
        "hostLookalike": HOST_LOOKALIKE, "hostOfficial": HOST_OFFICIAL, "addedWord": ADDED_WORD,
        "bankAr": BANK_AR, "bankEn": BANK_EN, "findings": {k: list(v) for k, v in FINDINGS.items()},
        "arbiterAr": ARBITER_NOTE_AR, "arbiterEn": ARBITER_NOTE_EN, "label": LABEL,
        "taglineAr": TAGLINE_AR, "taglineEn": TAGLINE_EN, "wordmarkAr": WORDMARK_AR, "wordmarkEn": WORDMARK_EN,
        "site": SITE, "event": EVENT, "creditAr": CREDIT_AR, "creditEn": CREDIT_EN,
        "fictionAr": FICTION_AR, "fictionEn": FICTION_EN,
        "people": variant == "final", "peopleAr": AI_PEOPLE_AR, "peopleEn": AI_PEOPLE_EN,
        "speakers": {k: list(v) for k, v in SPEAKERS.items()},
    }  # fmt: skip
