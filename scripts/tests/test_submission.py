"""Tests for the submission kit: description limits, number tracing, capability gating, tools list."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from submission import artifact, build, capabilities, check_numbers, content, descriptions, tools_used  # noqa: E402

ALL = {cap.id: True for cap in capabilities.CAPABILITIES}
NONE = {cap.id: False for cap in capabilities.CAPABILITIES}


# ── description length and wording ───────────────────────────────────────────
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("caps", [ALL, NONE, {**NONE, "url_check": True}, {**ALL, "mcp": False, "image_check": False}])
def test_composed_descriptions_fit_the_form(lang: str, caps: dict[str, bool]) -> None:
    text = descriptions.compose(caps, lang)
    assert descriptions.check(text) == []
    assert descriptions.count_chars(text) <= 600
    assert 2 <= len(descriptions.sentences(text)) <= 4


def test_every_capability_subset_of_inputs_fits() -> None:
    kinds = [
        "message_check",
        "email_check",
        "image_check",
        "brand_check",
        "sentinel_agent",
        "sovereign",
        "rest_api",
        "mcp",
    ]
    for mask in range(1 << len(kinds)):
        caps = {**NONE, "url_check": True, **{k: bool(mask >> i & 1) for i, k in enumerate(kinds)}}
        for lang in ("en", "ar"):
            assert descriptions.check(descriptions.compose(caps, lang)) == [], (caps, lang)


def test_length_limit_is_600_code_points() -> None:
    ok = "A" * 297 + ". " + "B" * 300 + "."
    assert descriptions.count_chars(ok) == 600
    assert descriptions.check(ok) == []
    errors = descriptions.check(ok + "x")
    assert any("too long: 601" in e for e in errors)


def test_arabic_is_counted_in_characters_not_bytes() -> None:
    text = "عدسة الصقر تفحص الروابط. وهي مشروع مستقل."
    assert descriptions.count_chars(text) == len(text) < len(text.encode("utf-8"))
    # A decomposed character counts once after NFC.
    assert descriptions.count_chars("é") == 1


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("One sentence only.", "1 sentences"),
        ("One. Two. Three. Four. Five.", "5 sentences"),
        ("", "empty"),
        ("First line.\nSecond line.", "line break"),
        ("This link is safe. Open it.", '"safe"'),
        ("هذا الرابط آمن. افتحه.", "آمن"),
        ("Falcon Lens is endorsed by the police. It checks links.", "relationship"),
    ],
)
def test_check_rejects(text: str, needle: str) -> None:
    assert any(needle in error for error in descriptions.check(text)), descriptions.check(text)


def test_wording_allows_negated_disclaimer_and_safe_browsing() -> None:
    assert descriptions.wording_errors("It is not affiliated with or endorsed by Abu Dhabi Police.") == []
    assert descriptions.wording_errors("Google Safe Browsing is disabled.") == []
    assert descriptions.wording_errors("مشروع مستقل، غير تابع لشرطة أبوظبي.") == []


def test_unshipped_product_is_described_as_in_development() -> None:
    en = descriptions.compose(NONE, "en")
    assert "in development" in en and "not finished" in en
    assert "Sentinel" not in en and "MCP" not in en
    assert "قيد التطوير" in descriptions.compose(NONE, "ar")


def test_description_claims_only_shipped_capabilities() -> None:
    caps = {**NONE, "url_check": True, "message_check": True}
    en = descriptions.compose(caps, "en")
    assert "link or message" in en
    for word in ("email", "image", "Sentinel", "MCP", "REST", "brand check"):
        assert word not in en
    assert "Abu Dhabi Police" in en and "independent" in en


# ── number tracing ───────────────────────────────────────────────────────────
ARTIFACT = {
    "git_sha": "ab12cd34ef56",
    "created_at": "2026-11-23T10:00:00Z",
    "models": {"extractor": "claude-haiku-5-5"},
    "metrics": {"recall": 0.9312, "fpr": 0.0125, "n_test": 412, "latency_ms": {"p95": 1840.5}},
}


def findings(text: str, data: dict | None = ARTIFACT) -> list[str]:
    return [f.token for f in check_numbers.find_untraceable(text, check_numbers.Traceable(data), "t")]


def test_artifact_values_are_traceable() -> None:
    assert findings("Recall 0.9312 on 412 URLs, p95 latency 1840.5 ms.") == []
    assert findings("Recall 0.93 and FPR 0.013.") == []  # rounded to the shown decimals
    assert findings("Recall 93.1% and FPR 1.25%.") == []  # ratios shown as percentages
    assert findings("Recall ٩٣٫١٪ on ٤١٢ URLs.") == []  # Arabic-Indic digits


def test_invented_numbers_fail() -> None:
    assert findings("Recall 0.97 on 500 URLs.") == ["0.97", "500"]
    assert findings("We catch 99% of scams.") == ["99%"]
    assert findings("Latency 93.1 ms.") == ["93.1"]  # 0.9312 only matches 93.1 as a percentage


def test_without_an_artifact_every_statistic_fails() -> None:
    assert findings("Recall 0.9312 on 412 URLs.", None) == ["0.9312", "412"]
    assert findings("Evaluation in progress.", None) == []


def test_identifiers_and_allowed_contexts_pass() -> None:
    text = (
        "Tiers T0 to T3, rules H1 and R5, gate G6, REST v1, STIX 2.1, Abu Dhabi Police x 42. "
        "Due Wed 25 Nov 2026 at 08:00, see ADR-001 and PR #17. The deck is at most 20 MB. A 60-second video."
    )
    assert findings(text, None) == []


def test_percentages_are_never_allowlisted() -> None:
    # "at most 20 MB" is an allowed limit; the same shape with a percent sign is a statistic.
    assert findings("At most 2% false positives.", None) == ["2%"]
    assert findings("Phase 1 reached 90% recall.", None) == ["90%"]


def test_git_sha_and_model_ids_from_the_artifact_pass() -> None:
    assert findings("Commit ab12cd3, extractor claude-haiku-5-5, created 2026-11-23.") == []
    assert findings("Commit 0123456789.") == ["0123456789"]


def test_markdown_code_links_and_tags_are_not_claims() -> None:
    markdown = (
        "Run `make up` on port `8443`.\n\n```bash\ncurl https://localhost:8443/v1/check/url --max-time 30\n```\n"
        '<img src="a.svg" width="100%">\n[doc](docs/x-99.md)\n1. First step\n2. Second step\n<!-- 77 -->\nRecall is 0.5.\n'
    )
    assert findings(check_numbers.strip_markdown(markdown), None) == ["0.5"]


def test_html_style_and_code_are_stripped() -> None:
    page = "<style>p{margin:4mm}</style><p>Recall 0.42</p><code>port 8443</code>"
    assert findings(check_numbers.strip_html(page), None) == ["0.42"]


def test_pptx_text_extraction_and_cli(tmp_path: Path) -> None:
    root = tmp_path
    sub = root / "submission"
    sub.mkdir()
    slide = '<p:sld xmlns:a="x"><a:p><a:r><a:t>Recall </a:t></a:r><a:r><a:t>0.9312</a:t></a:r></a:p><a:p><a:r><a:t>FPR 0.5</a:t></a:r></a:p></p:sld>'
    with zipfile.ZipFile(sub / "deck.pptx", "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
    assert check_numbers.pptx_text(sub / "deck.pptx") == "Recall 0.9312\nFPR 0.5"
    (sub / "description.html").write_text("<p>Evaluation in progress</p>", encoding="utf-8")
    published = root / "evals" / "results" / "published"
    published.mkdir(parents=True)
    (published / "2026-11-23.json").write_text(json.dumps(ARTIFACT), encoding="utf-8")

    args = ["--root", str(root), "--allow-missing"]
    assert check_numbers.main(args) == 1  # 0.5 is not in the artifact
    with zipfile.ZipFile(sub / "deck.pptx", "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide.replace("FPR 0.5", "FPR 0.0125"))
    assert check_numbers.main(args) == 0
    (root / "README.md").write_text("# Title\n\nWe block 99.9% of attacks.\n", encoding="utf-8")
    assert check_numbers.main(args) == 1
    assert check_numbers.main(["--root", str(root)]) == 2  # description.pdf missing


def test_newest_artifact_wins(tmp_path: Path) -> None:
    (tmp_path / "2026-11-22.json").write_text(json.dumps({"metrics": {"recall": 0.5}}), encoding="utf-8")
    (tmp_path / "2026-11-23.json").write_text(json.dumps({"metrics": {"recall": 0.9}}), encoding="utf-8")
    loaded = artifact.load(tmp_path)
    assert loaded is not None and loaded.metrics == [("recall", 0.9)]
    assert artifact.load(tmp_path / "nothing") is None


# ── content gating ───────────────────────────────────────────────────────────
def test_results_say_in_progress_without_an_artifact() -> None:
    sections = {s.key: s for s in content.build(NONE, None, "https://example.invalid/repo")}
    assert "Evaluation in progress" in sections["results"].lead
    assert sections["results"].table == ()
    assert "evaluation in progress" in " ".join(line.text for line in sections["deployment"].lines)
    assert findings(content.all_text(list(sections.values())).replace("https://example.invalid/repo", ""), None) == []


def test_results_copy_artifact_values_verbatim(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps(ARTIFACT), encoding="utf-8")
    loaded = artifact.load(tmp_path)
    results = next(s for s in content.build(ALL, loaded, "") if s.key == "results")
    assert ("recall", "0.9312") in results.table and ("latency_ms.p95", "1840.5") in results.table


def test_unshipped_lines_are_marked_planned_and_listed_on_the_roadmap() -> None:
    sections = {s.key: s for s in content.build(NONE, None, "")}
    assert all(line.planned for line in sections["solution"].lines)
    assert any("Not built yet" in line.text and "MCP server" in line.text for line in sections["roadmap"].lines)
    shipped = {s.key: s for s in content.build(ALL, None, "")}
    assert not any(line.planned for s in shipped.values() for line in s.lines)
    assert not any("Not built yet" in line.text for line in shipped["roadmap"].lines)


def test_deck_has_eleven_sections_and_clean_wording() -> None:
    sections = content.build(ALL, None, "")
    assert len(sections) == 11
    assert descriptions.wording_errors(content.all_text(sections)) == []
    assert "not connected" in next(s for s in sections if s.key == "integration").lead.lower()


# ── capability probes ────────────────────────────────────────────────────────
def test_make_target_stub_is_not_implemented(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        'NYI = @echo "nyi"; exit 1\nsmoke:\n\t@scripts/smoke.sh\n\nreplay:\n\t$(NYI)\n', encoding="utf-8"
    )
    assert capabilities.make_target_implemented(tmp_path, "smoke")
    assert not capabilities.make_target_implemented(tmp_path, "replay")
    assert not capabilities.make_target_implemented(tmp_path, "demo")


def test_probes(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.py").write_text("@mcp.tool\ndef check_url(): ...\n", encoding="utf-8")
    assert capabilities.probe(tmp_path, "path:a/*.py")
    assert not capabilities.probe(tmp_path, "path:b/*.py")
    assert capabilities.probe(tmp_path, r"grep:a/**/*.py::@\w+\.tool")
    assert not capabilities.probe(tmp_path, "grep:a/**/*.py::playwright")
    assert capabilities.detect(tmp_path) == NONE


# ── tools used, repo url ─────────────────────────────────────────────────────
def test_python_tools_list_only_imported_direct_dependencies(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(
        """
[[package]]
name = "falcon-api"
version = "0.1.0"
source = { editable = "services/api" }
dependencies = [{ name = "fastapi" }, { name = "unusedlib" }, { name = "falcon-core" }]

[[package]]
name = "falcon-core"
version = "0.1.0"
source = { editable = "packages/falcon_core" }

[[package]]
name = "fastapi"
version = "0.165.0"

[[package]]
name = "unusedlib"
version = "1.0"

[[package]]
name = "starlette"
version = "0.50.0"
""",
        encoding="utf-8",
    )
    src = tmp_path / "services" / "api" / "src" / "falcon_api"
    src.mkdir(parents=True)
    (src / "main.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    assert tools_used.python_tools(tmp_path) == ["FastAPI 0.165.0"]


def test_tools_render_on_this_repo_is_deduplicated() -> None:
    text = tools_used.render()
    names = [item.strip() for line in text.splitlines() for item in line.split(":", 1)[1].split(",")]
    assert len(names) == len(set(names))
    assert "Python" in text and "falcon-" not in text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://github.com/o/r.git", "https://github.com/o/r"),
        ("git@github.com:o/r.git", "https://github.com/o/r"),
        ("https://user:token@github.com/o/r.git", "https://github.com/o/r"),
        ("ssh://git@github.com/o/r", "https://github.com/o/r"),
    ],
)
def test_repo_url_is_public_https_without_credentials(raw: str, expected: str) -> None:
    assert build.normalise_repo_url(raw) == expected


def test_text_only_build_writes_fields_and_checklist(tmp_path: Path) -> None:
    assert build.main(["--out", str(tmp_path), "--text-only"]) in (0, 1)
    assert (tmp_path / "title.txt").read_text(encoding="utf-8").strip() == "Falcon Lens | عدسة الصقر"
    for lang in ("en", "ar"):
        assert descriptions.check((tmp_path / f"description_{lang}.txt").read_text(encoding="utf-8")) == []
    checklist = (tmp_path / "CHECKLIST.md").read_text(encoding="utf-8")
    assert "private window" in checklist and "description_en" in checklist and "20 MB" in checklist
