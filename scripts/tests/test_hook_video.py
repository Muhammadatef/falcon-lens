"""Tests for the hook film builder (submission/build/hook_video): cue sheet, wording rules, determinism of the page."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "submission" / "build" / "hook_video"
SCRIPT = ROOT / "packages" / "falcon_core" / "src" / "falcon_core" / "i18n" / "voice_script.yaml"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"hook_{name}", HOOK / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cues = load("cues")
align = load("align")
# Clip lengths in seconds, as generated for the product (the clips themselves are private and not in the repo).
LENGTHS = {
    "wake.ack": 0.98, "found.1": 1.05, "investigator.start.1": 1.72, "investigator.lists": 2.05,
    "investigator.address": 2.66, "investigator.page": 3.89, "investigator.ai_second_look_local": 3.08,
    "investigator.arbiter_result.dangerous": 1.76, "sentinel.handover": 1.33, "sentinel.linked.3": 2.67,
    "todo.lead": 0.77, "todo.link": 2.21, "todo.otp": 1.62,
}  # fmt: skip


def timeline(variant: str) -> dict[str, Any]:
    return cues.build_timeline(variant, LENGTHS)


def test_captions_are_the_products_own_spoken_lines() -> None:
    script = yaml.safe_load(SCRIPT.read_text(encoding="utf-8"))
    for ln in cues.FALCON:
        assert ln.key in script["ar_ae"], ln.key
        if ln.key in cues.PENDING_SCRIPT:
            continue  # wording from an open pull request; the clip manifest is checked at build time instead
        assert ln.ar == script["ar_ae"][ln.key], ln.key
        assert ln.en == script["en"][ln.key], ln.key


def test_every_step_of_a_real_check_is_in_the_answer_in_order() -> None:
    keys = [ln.key for ln in cues.FALCON]
    wanted = [
        "wake.ack", "found.1", "investigator.start.1", "investigator.lists", "investigator.address", "investigator.page",
        "investigator.ai_second_look_local", "investigator.arbiter_result.dangerous", "sentinel.handover",
        "sentinel.linked.3", "todo.lead", "todo.link", "todo.otp",
    ]  # fmt: skip
    assert keys == wanted
    numbers = [ln.step for ln in cues.FALCON if ln.step]
    assert numbers == sorted(numbers) and numbers[0] == 1
    assert [row["n"] for row in cues.steps()] == list(range(1, 11))


@pytest.mark.parametrize("variant", cues.VARIANTS)
def test_timeline_is_ordered_and_within_the_limit(variant: str) -> None:
    tl = timeline(variant)
    assert tl["duration"] <= cues.HARD_MAX
    assert tl["frames"] == round(tl["duration"] * tl["fps"])
    scenes = tl["scenes"]
    assert scenes[0]["id"] == "intro" and scenes[0]["t0"] == 0
    for a, b in zip(scenes, scenes[1:], strict=False):
        assert a["t1"] == b["t0"] and a["t1"] > a["t0"]
    starts = [ln["t0"] for ln in tl["lines"]]
    assert starts == sorted(starts)
    spoken = [ln for ln in tl["lines"] if ln["who"] == "falcon"]
    for a, b in zip(spoken, spoken[1:], strict=False):
        assert b["t0"] >= a["t1"], (a["id"], b["id"])  # the Falcon never talks over itself
    for ln in tl["lines"]:
        times = [w[1] for w in ln["words"]]
        assert times == sorted(times) and len(times) == len(cues.split_words(ln["ar"]))


def test_the_earcon_lands_on_the_verdict_and_nothing_else_plays_there() -> None:
    tl = timeline("sequence")
    slam = tl["marks"]["verdict.slam"]
    earcons = [c for c in tl["clips"] if c["kind"] == "earcon"]
    assert [c["file"] for c in earcons] == [cues.SFX_VERDICT] and earcons[0]["t0"] == pytest.approx(slam)
    verdict_line = next(ln for ln in tl["lines"] if ln["id"] == "investigator.arbiter_result.dangerous")
    assert verdict_line["t0"] >= slam + cues.EARCON
    assert all(not (ln["t0"] < slam + cues.EARCON and ln["t1"] > slam) for ln in tl["lines"] if ln["who"] == "falcon")


def test_cuts_differ_only_in_how_they_open() -> None:
    seq, fin, intro = timeline("sequence"), timeline("final"), timeline("intro")
    assert [s["id"] for s in intro["scenes"]] == ["intro"] and not intro["lines"]
    assert not seq["live_pic"] and not seq["live_audio"]
    assert {p["id"] for p in fin["live_pic"]} == {"plate", "son", "hey"}
    answer = lambda tl: [ln["id"] for ln in tl["lines"] if ln["who"] == "falcon"]  # noqa: E731
    assert answer(seq) == answer(fin) == [ln.key for ln in cues.FALCON]
    assert cues.build_timeline("final", LENGTHS, relief=True)["duration"] > fin["duration"]
    for run in fin["live_audio"]:
        assert 0 <= run["src0"] < run["src1"] <= 65.6  # inside the footage


def _all_text() -> list[str]:
    out: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list | tuple):
            for v in value:
                walk(v)

    for variant in ("sequence", "final"):
        walk(cues.page_data(variant))
        walk([[ln["ar"], ln["en"]] for ln in timeline(variant)["lines"]])
    return out


def test_wording_rules_hold_for_everything_on_screen() -> None:
    texts = _all_text()
    blob = "\n".join(texts)
    assert not re.search(r"\bsafe(ty|ly)?\b", blob, re.IGNORECASE)
    assert not re.search(r"آمن|مأمون|سليم", blob)
    assert cues.LABEL == "تمثيل — Dramatisation"
    # The competition is named once, on the end card, next to the words that say the entry is independent.
    police = [t for t in set(texts) if "Abu Dhabi Police" in t or "شرطة" in t]
    assert police == [cues.CREDIT_EN] and "independent" in cues.CREDIT_EN and "not connected" in cues.CREDIT_EN
    assert "مستقل" in cues.CREDIT_AR


def test_only_the_invented_bank_and_defanged_fixture_hosts_appear() -> None:
    blob = "\n".join(_all_text())
    assert "http://" not in blob and "https://" not in blob
    hosts = set(re.findall(r"[a-z0-9-]+(?:\[\.\]|\.)[a-z]{2,}", blob))
    assert hosts <= {cues.HOST_LOOKALIKE, cues.HOST_OFFICIAL, cues.SITE}, hosts
    assert cues.HOST_LOOKALIKE.endswith("[.]test") and cues.HOST_OFFICIAL.endswith("[.]test")
    assert cues.HOST_OFFICIAL.replace("[.]test", cues.ADDED_WORD + "[.]test") == cues.HOST_LOOKALIKE
    assert not re.search(r"\d{5,}", blob)  # no phone number, no account number, no statistic
    real_banks = "FAB|ADCB|Emirates NBD|Mashreq|RAKBANK|بنك أبوظبي|بنك الإمارات|المشرق"
    assert not re.search(real_banks, blob)
    assert cues.BANK_EN == "Falcon Demo Bank" and cues.BANK_AR in blob


def test_the_page_is_a_pure_function_of_time() -> None:
    js = "\n".join(p.read_text(encoding="utf-8") for p in sorted((HOOK / "composition").glob("*.js")))
    for banned in ("setTimeout", "setInterval", "requestAnimationFrame", "Date.now", "performance.now", "Math.random"):
        assert banned not in js, banned
    css = (HOOK / "composition" / "hook.css").read_text(encoding="utf-8")
    assert "@keyframes" not in css
    assert "animation: none !important" in css and "transition: none !important" in css
    assert "window.__seek" in js and "window.__ready" in js


def test_word_timings_follow_the_recogniser_but_keep_the_script_words() -> None:
    text = "أفتح الصفحة في متصفح معزول"
    heard = [
        (0.0, 0.3, "أفتح"),
        (0.3, 0.8, "الصفحة"),
        (0.8, 0.9, "في"),
        (0.9, 1.5, "متصفح"),
        (1.5, 1.6, "مع"),
        (1.6, 1.9, "زول"),
    ]
    out = align.align(text, heard, 2.0)
    assert [w for w, _ in out] == text.split()
    times = [t for _, t in out]
    assert times == sorted(times) and times[0] == 0.0 and 1.3 < times[-1] < 1.7
    spread = cues.spread_words(text, 1.0, 3.0)
    assert [w for w, _ in spread] == text.split() and spread[0][1] == 1.0 and spread[-1][1] < 3.0


def test_sound_is_limited_below_full_scale() -> None:
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    audio = load("audio")
    burst = np.zeros((audio.SR // 2, 2))
    burst[1000:1400] = 2.5  # far over full scale
    out = audio.limit(burst)
    assert float(np.abs(out).max()) <= audio.db(audio.CEILING_DB) + 1e-6
    music, bed, sfx = audio.score(timeline("intro"))
    assert np.isfinite(music).all() and float(np.abs(music).max()) > 0.05
    assert not bed.any() and not sfx.any()  # the sting alone carries the logo
