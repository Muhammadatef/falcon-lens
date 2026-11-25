"""Unit checks for the v2 pitch deck builder (submission/build/build_deck_v2.py). No browser, no Keynote."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pptx")
pytest.importorskip("lxml")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "submission" / "build"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_deck_v2 as v2  # noqa: E402


def test_runs_are_split_by_script() -> None:
    runs = v2.split_scripts([v2.Run("عدسة الصقر | Falcon Lens", 20)])
    assert [r.text for r in runs] == ["عدسة الصقر | ", "Falcon Lens"]
    assert "".join(r.text for r in runs) == "عدسة الصقر | Falcon Lens"


def test_every_tool_has_a_monogram_and_only_vendored_logos() -> None:
    logos = {p.stem for p in (ROOT / "submission" / "build" / "logos").glob("*.svg")}
    for tool, (slug, mono) in v2.TOOL_MARK.items():
        assert len(mono) == 2, tool
        assert slug is None or slug in logos, f"{tool}: {slug}.svg is not vendored"
    shown = {tool for _, _, _, tools in v2.TOOL_LAYERS for _, _, tool in tools}
    assert shown <= set(v2.TOOL_MARK)


def test_no_police_or_bank_logo_is_vendored() -> None:
    names = " ".join(p.stem for p in (ROOT / "submission" / "build" / "logos").glob("*.svg"))
    for banned in ("police", "adp", "bank", "nbd", "adcb", "fab"):
        assert banned not in names


def test_main_path_has_at_most_one_click_per_slide_and_every_appendix_slide_links_back() -> None:
    v2.LOGOS.clear()  # monogram badges: no browser needed
    facts = v2.bd.gather(ROOT)
    slides, n_main = v2.build_slides(facts, ROOT, None)
    assert n_main == 8
    keys = [s.key for s in slides]
    assert len(keys) == len(set(keys))
    for s in slides:
        assert sum(1 for m in s.motion if m.trigger == "click") <= 1, s.key
        assert s.notes.strip(), s.key
        links = [sh.link for sh in v2.walk(s.shapes) if isinstance(sh, v2.Hot)]
        assert all(link in keys for link in links), s.key
        if getattr(s, "appendix", False):
            assert "index" in links, s.key
    index = slides[n_main]
    assert {sh.link for sh in v2.walk(index.shapes) if isinstance(sh, v2.Hot)} >= {s.key for s in slides[n_main + 1 :]}
