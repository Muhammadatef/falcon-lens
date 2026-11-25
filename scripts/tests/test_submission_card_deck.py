"""Tests for the submission card, the demo script and the deck generator (submission/build/*.py)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from submission import artifact, check_numbers, descriptions  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "evals" / "results" / "published"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"t_{name}", ROOT / "submission" / "build" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_card_descriptions_fit_the_form_and_have_no_email() -> None:
    card = load("project_card")
    text, problems, count = card.build(ROOT)
    assert problems == []
    assert all(n <= descriptions.MAX_CHARS for n in count.values())
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    assert "https://github.com/Muhammadatef/falcon-lens" in text
    assert "Mohamed Atef" in text and "MokhmadSalakh Salamov" in text


def test_card_fails_when_a_description_is_over_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    card = load("project_card")
    monkeypatch.setattr(card.descriptions, "compose", lambda caps, lang: "Word. " * 200)
    _text, problems, _count = card.build(ROOT)
    assert any("600" in p for p in problems)


def test_card_tools_come_from_the_generator_not_from_typing(tmp_path: Path) -> None:
    card = load("project_card")
    assert "LangGraph" not in card.tools_line(tmp_path)  # an empty tree lists nothing
    line = card.tools_line(ROOT)
    assert "FastAPI" in line and "Playwright" in line and "LangGraph" in line
    assert ("DSPy" in line) == card.dspy_shipped(ROOT)  # listed only when locked and imported


def test_demo_script_numbers_come_from_the_artifact_and_trace() -> None:
    mod = load("demo_script")
    text, problems = mod.build(ROOT)
    assert problems == []
    art = artifact.load(PUBLISHED)
    if art is not None:
        assert mod.pct(dict(art.metrics)["test.recall"]) in text
    traceable = check_numbers.traceable_for(art, PUBLISHED)
    assert check_numbers.find_untraceable(check_numbers.strip_markdown(text), traceable, "DEMO_SCRIPT.md") == []


def test_demo_script_has_the_pitch_timeline_and_ten_questions() -> None:
    text, problems = load("demo_script").build(ROOT)
    assert problems == []
    for stamp in (
        "0:00 to 0:25",
        "0:25 to 0:55",
        "0:55 to 2:40",
        "2:40 to 3:00",
        "M1",
        "/history",
        "/campaigns",
        "/results",
        "/ops",
    ):
        assert stamp in text
    for phrase in ("يا صقر، شيّك اللي نسخته", "Hey Falcon, someone called saying he's from the bank", "خطِر"):
        assert phrase in text
    assert "ready to connect, not connected" in text.lower()
    assert not any(
        f"{{{k}}}" in text for k in ("ASKED", "FRESH_MAIN", "STATUS_TABLE", "HUNTER_BEAT")
    )  # every placeholder filled
    questions = [ln for ln in text.splitlines() if re.match(r"^\d+\. \*\*.*\?\*\*", ln)]
    assert len(questions) == 10


def test_demo_script_marks_unmerged_features_as_planned() -> None:
    mod = load("demo_script")
    text, _ = mod.build(ROOT)
    for cap_id in ("evidence_pack", "hunter", "batch_check"):
        assert mod.shipped(cap_id) or "PLANNED" in text


def write_fp(directory: Path, name: str, created: str, value: float) -> None:
    (directory / "fp_regress").mkdir(parents=True, exist_ok=True)
    body = {
        "created_at": created,
        "n": 200,
        "target": 0.02,
        "false_positive_rate": {"value": value, "ci95": [0.1, 0.9]},
    }
    (directory / "fp_regress" / name).write_text(json.dumps(body), encoding="utf-8")


def test_newest_fp_regress_run_wins_and_its_numbers_are_traceable(tmp_path: Path) -> None:
    write_fp(tmp_path, "a.json", "2026-11-23T01:00:00Z", 0.5)
    write_fp(tmp_path, "b.json", "2026-11-23T09:00:00Z", 0.285)
    (tmp_path / "fp_regress" / "old_format.json").write_text(
        json.dumps({"created_at": "2026-11-24T00:00:00Z"}), encoding="utf-8"
    )
    newest = artifact.load_fp_regress(tmp_path)
    assert newest is not None and newest["false_positive_rate"]["value"] == 0.285
    traceable = check_numbers.traceable_for(None, tmp_path)
    assert check_numbers.find_untraceable("Flagged 28.5% of 200 sites, target 2.0%.", traceable, "x") == []
    assert check_numbers.find_untraceable("Flagged 31.5% of sites.", traceable, "x") != []


def test_no_fp_regress_means_no_extra_numbers(tmp_path: Path) -> None:
    assert artifact.load_fp_regress(tmp_path) is None
    traceable = check_numbers.traceable_for(None, tmp_path)
    assert check_numbers.find_untraceable("Flagged 28.5% of sites.", traceable, "x") != []


# ── deck (python-pptx is a build-time tool: skipped where it is not installed) ──
def test_deck_pptx_roundtrips_with_notes_and_rtl(tmp_path: Path) -> None:
    pytest.importorskip("pptx")
    deck = load("build_deck")
    s = deck.Slide("t", "Title", "العنوان")
    s.add(deck.tb(1, 2, 5, 1, deck.p("Hello", 20), deck.p("مرحبا", 20, align="r")), deck.card(1, 3, 4, 1))
    s.notes = "Speaker note."
    deck.frame(s, 1, 1)
    out = tmp_path / "d.pptx"
    deck.write_pptx([s], out)
    assert deck.verify_pptx(out, 1) == []
    assert deck.verify_pptx(out, 2) != []  # a wrong slide count is reported
    with zipfile.ZipFile(out) as zf:
        xml = "".join(zf.read(n).decode() for n in zf.namelist() if n.startswith("ppt/slides/slide"))
    assert 'rtl="1"' in xml and "Arial" in xml


def test_deck_text_check_rejects_an_invented_number_and_the_word_safe(tmp_path: Path) -> None:
    pytest.importorskip("pptx")
    deck = load("build_deck")
    s = deck.Slide("t", "Title", "العنوان")
    s.add(deck.tb(1, 2, 5, 1, deck.p("We catch 77.7% of scams and it is safe.", 20)))
    s.notes = "Note."
    out = tmp_path / "bad.pptx"
    deck.write_pptx([s], out)
    problems = deck.check_text(out, artifact.load(PUBLISHED), PUBLISHED)
    assert any("untraceable number" in p for p in problems) and any("safe" in p for p in problems)


def test_deck_pct_is_exact_decimal_rounding() -> None:
    pytest.importorskip("pptx")
    deck = load("build_deck")
    assert deck.pct(0.983333) == "98.3%" and deck.pct(0.0375) == "3.8%" and deck.pct(1.0) == "100.0%"


def test_unshipped_capability_is_marked_planned() -> None:
    pytest.importorskip("pptx")
    deck = load("build_deck")
    facts = deck.Facts(None, None, {"mcp": False, "rest_api": True}, "u", [], [])
    assert facts.planned("mcp", "Serves MCP.").startswith("Planned: serves")
    assert facts.planned("rest_api", "Serves REST.") == "Serves REST."
    assert facts.planned(None, "Always.") == "Always."


def test_curated_tool_groups_only_show_generated_tools() -> None:
    pytest.importorskip("pptx")
    deck = load("build_deck")
    facts = deck.Facts(None, None, {}, "u", [("Backend", ["FastAPI"])], [])
    assert dict(deck.shown_tools(facts)) == {"Backend": ["FastAPI"]}


def test_deck_spoken_lines_are_the_run_sheet_lines() -> None:
    """Slides 3, 5, 7 and 14 speak the run-sheet word for word (DECK_DESIGN.md section 4)."""
    pytest.importorskip("lxml")
    pytest.importorskip("pptx")
    deck = load("build_deck")
    template = (ROOT / "submission" / "build" / "demo_template.md").read_text(encoding="utf-8")
    for line in (
        deck.PROBLEM_EN,
        deck.PROBLEM_AR,
        deck.SOLUTION_EN,
        deck.SOLUTION_AR,
        deck.DEMO_EN,
        deck.DEMO_AR,
        deck.CLOSE_EN,
        deck.CLOSE_AR,
        deck.HOOK_FAIL_AR,
    ):
        assert line.replace("«", "").replace("»", "") in template.replace("«", "").replace("»", "")


def test_keynote_visible_motion_vocabulary() -> None:
    """Every build uses an effect Keynote imports as a visible build, and lasts long enough to be seen."""
    pytest.importorskip("lxml")
    pytest.importorskip("pptx")
    deck = load("build_deck")
    motion = sys.modules["deck_motion"]
    slides = deck.build_slides(deck.gather(ROOT), {})
    steps = [m for s in slides for m in s.motion]
    assert len(steps) >= 100
    assert {m.effect for m in steps} <= set(motion.EFFECTS)
    assert min(m.dur for m in steps) >= 500
    assert max(m.dur for m in steps) <= motion.MAX_EFFECT_MS
    assert sum(m.effect.startswith(("fly", "zoom", "wipe")) for m in steps) > len(steps) / 2
    assert [m.trigger for m in slides[1].motion] == ["click"] * 8  # the agenda: one item per click


def test_video_timing_is_a_play_command_plus_a_media_node() -> None:
    pytest.importorskip("lxml")
    pytest.importorskip("pptx")
    load("build_deck")
    motion = sys.modules["deck_motion"]
    from lxml import etree

    for auto in (False, True):
        root = etree.fromstring(motion.media_timing_xml(7, 65600, auto))
        ns = {"p": motion.NS_P}
        assert root.xpath("//p:cmd[@cmd='playFrom(0.0)']//p:spTgt/@spid", namespaces=ns) == ["7"]
        assert root.xpath("//p:video//p:spTgt/@spid", namespaces=ns) == ["7"]
        assert bool(root.xpath("//p:cond[@evt='onBegin']", namespaces=ns)) is auto


def test_presentation_html_is_self_contained(tmp_path: Path) -> None:
    pytest.importorskip("lxml")
    pytest.importorskip("pptx")
    deck = load("build_deck")
    present = load("deck_present")
    slides = deck.build_slides(deck.gather(ROOT), {})
    out = tmp_path / "deck.html"
    present.write(deck, slides, out, ROOT)
    page = out.read_text(encoding="utf-8")
    assert page.count('<section class="slide"') == len(slides)
    assert "file://" not in page and 'src="http' not in page and 'href="http' not in page
    assert "prefers-reduced-motion" in page
    beats = present.beats(slides[1].motion)
    assert len(beats) == 8 and not beats[0]["auto"]
    assert present.beats(slides[0].motion)[0]["auto"]
