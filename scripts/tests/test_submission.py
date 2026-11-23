"""Tests for the submission kit: description limits, number tracing, capability gating, tools list."""

from __future__ import annotations

import itertools
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from submission import artifact, build, capabilities, check_numbers, content, descriptions, tools_used  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ALL = {cap.id: True for cap in capabilities.CAPABILITIES}
NONE = {cap.id: False for cap in capabilities.CAPABILITIES}

# Every capability a description sentence or clause depends on.
DESCRIPTION_CAPS = (
    "url_check",
    "message_check",
    "email_check",
    "image_check",
    "brand_check",
    "sentinel_rules",
    "sentinel_agent",
    "sovereign",
    "rest_api",
    "mcp",
)


# ── description length and wording ───────────────────────────────────────────
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_every_capability_subset_fits_the_form(lang: str) -> None:
    """All 2^10 combinations, including url_check=False with the Sentinel shipped (PR-31 B2)."""
    for bits in itertools.product((False, True), repeat=len(DESCRIPTION_CAPS)):
        caps = {**NONE, **dict(zip(DESCRIPTION_CAPS, bits, strict=True))}
        text = descriptions.compose(caps, lang)
        assert descriptions.check(text) == [], (caps, text)
        assert descriptions.count_chars(text) <= 600
        assert 2 <= len(descriptions.sentences(text)) <= 4


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_pre_mvp_with_sentinel_agent_is_four_sentences(lang: str) -> None:
    """The exact state of main when PR-31 was reviewed: Sentinel shipped, end-to-end check not."""
    caps = {**NONE, "sentinel_rules": True, "sentinel_agent": True}
    text = descriptions.compose(caps, lang)
    assert descriptions.check(text) == []
    assert len(descriptions.sentences(text)) == 4


def test_fit_counts_sentences_not_candidates() -> None:
    two_in_one = [(0, ["One. Two."]), (0, ["Three."]), (1, ["Four."]), (0, ["Five."])]
    text = descriptions._fit(two_in_one)
    assert len(descriptions.sentences(text)) == 4 and "Four." not in text


def test_length_limit_is_600_code_points() -> None:
    ok = "A" * 297 + ". " + "B" * 300 + "."
    assert descriptions.count_chars(ok) == 600
    assert descriptions.check(ok) == []
    assert any("too long: 601" in e for e in descriptions.check(ok + "x"))


def test_arabic_is_counted_in_characters_not_bytes() -> None:
    text = "عدسة الصقر تفحص الروابط. وهي مشروع مستقل."
    assert descriptions.count_chars(text) == len(text) < len(text.encode("utf-8"))
    assert descriptions.count_chars("é") == 1  # a decomposed character counts once after NFC


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


def test_pre_mvp_sentinel_sentence_says_events_are_replayed() -> None:
    en = descriptions.compose({**NONE, "sentinel_rules": True, "sentinel_agent": True}, "en")
    assert "replayed in this build" in en and "Built so far" not in en
    # a brand check cannot be claimed while no check runs end to end
    assert "brand check" not in descriptions.compose({**NONE, "brand_check": True}, "en")


def test_description_claims_only_shipped_capabilities() -> None:
    caps = {**NONE, "url_check": True, "message_check": True}
    en = descriptions.compose(caps, "en")
    assert "link or message" in en
    for word in ("email", "image", "Sentinel", "MCP", "REST", "brand check"):
        assert word not in en
    assert "Abu Dhabi Police" in en and "independent" in en


# ── number tracing ───────────────────────────────────────────────────────────
# The shape of the real artifact, with strings full of digit runs (PR-31 B3).
ARTIFACT = {
    "git_sha": "7e52a88ac36c6a4ece9f814cebbc337eef685c03-dirty",
    "created_at": "2026-11-22T18:04:22Z",
    "dataset_hash": "sha256:98ab31c0",
    "seeds": {"bootstrap": 20261122, "n_bootstrap": 1000},
    "model_ids": {"extractor": "claude-haiku-5-5"},
    "thresholds": {"tau_high": 0.8139},
    "metrics": {
        "test.recall": 0.9312,
        "test.fpr": 0.0125,
        "test.n": 412,
        "test.recall_ci95": [0.9, 1.0],
        "latency_ms": {"p95": 1840.5},
    },
}
TRACE = check_numbers.Traceable(ARTIFACT, names=("20261122T180422Z.json", "20261122T180422Z"))


def findings(text: str, traceable: check_numbers.Traceable | None = TRACE) -> list[str]:
    return [f.token for f in check_numbers.find_untraceable(text, traceable or check_numbers.Traceable(None), "t")]


def test_metric_values_are_traceable() -> None:
    assert findings("Recall 0.9312 on 412 URLs, p95 latency 1840.5 ms, ci95 [0.9, 1.0].") == []
    assert findings("Recall 0.93 and FPR 0.013.") == []  # rounded to the shown decimals
    assert findings("Recall 93.1% and FPR 1.25%.") == []  # ratios shown as percentages
    assert findings("Recall 93.1 percent, 93.1 per cent, ٩٣٫١٪, 93.1％ and 93.1 بالمئة.") == []
    assert findings("Recall ٩٣٫١٪ on ٤١٢ URLs.") == []  # Arabic-Indic digits
    assert findings("Source: evals/results/published/20261122T180422Z.json") == []


def test_invented_numbers_fail() -> None:
    assert findings("Recall 0.97 on 500 URLs.") == ["0.97", "500"]
    assert findings("We catch 99% of scams.") == ["99%"]
    assert findings("Latency 93.1 ms.") == ["93.1"]  # 0.9312 only matches 93.1 as a percentage


def test_without_an_artifact_every_statistic_fails() -> None:
    assert findings("Recall 0.9312 on 412 URLs.", None) == ["0.9312", "412"]
    assert findings("Evaluation in progress.", None) == []


@pytest.mark.parametrize(
    "text",
    [
        "Recall is 98 percent.",
        "We caught 98 scams.",
        "22 campaigns blocked",
        "52 incidents opened",
        "88 lookalike domains",
        "Bootstrap of 1000 resamples and 20261122 runs",  # seeds are not metrics
        "Threshold 0.8139",  # thresholds are not metrics
        "Model 5 of 5",  # digits of a model id
        "18 seconds and 04 minutes",  # digits of a timestamp
    ],
)
def test_digits_inside_artifact_strings_do_not_make_a_number_traceable(text: str) -> None:
    """PR-31 B3: a SHA, a timestamp, a hash, seeds or thresholds never vouch for a number."""
    assert findings(text) != []
    assert findings(text, None) != []


def test_whole_artifact_strings_and_sha_prefixes_pass() -> None:
    assert findings("Commit 7e52a88ac36c, extractor claude-haiku-5-5, created 2026-11-22T18:04:22Z.") == []
    assert findings("Commit 7e52a88ac36c6a4ece9f814cebbc337eef685c03-dirty.") == []
    assert findings("Commit 0123456789.") == ["0123456789"]
    assert findings("Commit 7e52a8.") != []  # shorter than a short SHA
    assert findings("Model claude-haiku-5-6.") != []  # not the artifact's string


@pytest.mark.parametrize(
    "text",
    [
        "98 percent",
        "98 per cent",
        "98 Percent of pages",
        "ninety-eight percent",
        "ninety eight per cent of scams",
        "recall of ninety-eight",
        "Accuracy: ninety five",
        "و٩٨٪",
        "بنسبة٩٨٪",
        "ب98%",
        "٩٨ بالمئة",
        "98 في المئة",
        "ثمانية وتسعون بالمئة",
        "نسبة الكشف ثمانية وتسعون",
        "دقة تسعين",
        "98％",
        "９８％",
        "F1 .98",
        "recall ⁹⁸",
        "recall ⁹⁸%",
        "98 %",
    ],
)
def test_percentage_and_number_word_bypasses_are_caught(text: str) -> None:
    """PR-31 B4. None of these can pass, with or without an artifact."""
    assert findings(text) != [], text
    assert findings(text, None) != [], text


def test_plain_counts_in_words_are_not_flagged() -> None:
    text = "Six scenarios, three verdicts, one command and eleven slides. ستة مشاهد وثلاثة أحكام."
    assert findings(text, None) == []
    assert findings("[NUMBER: zero-day recall and false-positive rate from the published artifact]", None) == []


def test_inline_code_with_a_percentage_is_scanned() -> None:
    assert findings(check_numbers.strip_markdown("We reach `98%` recall."), None) == ["98%"]
    assert findings(check_numbers.strip_markdown("We reach `98 percent`."), None) == ["98 percent"]
    assert findings(check_numbers.strip_html("<p>We reach <code>98%</code>.</p>"), None) == ["98%"]
    assert findings(check_numbers.strip_markdown("Run on port `8443` with `DURATION=2m`."), None) == []


@pytest.mark.parametrize(
    "text",
    [
        "Falcon Lens returns a verdict in under 3 seconds.",
        "A 2-second verdict for every link.",
        "Verdicts within 2 s.",
        "Answers in 0:03.",
        "At most 5 seconds per check.",
        "T0 answers in 50 ms.",
        "x 42 incidents",
        "Abu Dhabi Police x 42 incidents",
        "999 scams caught",
        "We run 24/7.",
        "Up to 300 pages checked.",
        "A 30-minute outage.",
        "Scenario 98 of our tests passed.",
    ],
)
def test_speed_claims_and_counts_are_not_allowlisted(text: str) -> None:
    """PR-31 B5: latency and counts are claims. Only the artifact or a labelled design budget covers them."""
    assert findings(text, None) != [], text


def test_latency_from_the_artifact_and_labelled_design_budgets_pass() -> None:
    assert findings("p95 latency 1840.5 ms.") == []
    assert findings("| T0 | 50 ms (design budget) | cache |", None) == []
    assert findings("design budgets · 50 ms · 1 s · 6 s · 15 s", None) == []
    assert findings("design budget: 6 s", None) == []
    assert findings("design budget 50 ms and then 98 checks", None) == ["98"]


def test_identifiers_and_exact_contexts_pass() -> None:
    text = (
        "Tiers T0 to T3, rules H1 and R5, gate G6, REST v1, STIX 2.1, Abu Dhabi Police x 42. "
        "Due Wed 25 Nov 2026 08:00, see ADR-001 and PR #17. The deck is at most 20 MB, the description "
        "at most 600 characters. A 60-second video and a 3-minute pitch. Scenarios 2 to 6, step 8, ports 80 and 443."
    )
    assert findings(text, None) == []


def test_percentages_are_never_allowlisted() -> None:
    assert findings("At most 20 MB and 2% false positives.", None) == ["2%"]
    assert findings("Phase 1 reached 90% recall.", None) == ["90%"]
    assert findings("Scenario 2 percent", None) != []
    assert findings("design budget 50 ms (98%)", None) == ["98%"]


def test_markdown_code_links_and_tags_are_not_claims() -> None:
    markdown = (
        "Run `make up` on port `8443`.\n\n```bash\ncurl https://localhost:8443/v1/check/url --max-time 30\n```\n"
        '<img src="a.svg" width="100%">\n[doc](docs/x-99.md)\n1. First step\n2. Second step\n<!-- 77 -->\nRecall is 0.5.\n'
    )
    assert findings(check_numbers.strip_markdown(markdown), None) == ["0.5"]


def test_html_style_and_code_are_stripped() -> None:
    page = "<style>p{margin:4mm}</style><p>Recall 0.42</p><code>port 8443</code>"
    assert findings(check_numbers.strip_html(page), None) == ["0.42"]


def test_svg_text_nodes_are_scanned() -> None:
    svg = '<svg><title>Arch</title>\n<g><text x="1">design budgets</text><text x="2">50 ms</text><text x="3">1 s</text></g>\n<text x="9">6 dashboards</text>\n<rect width="100" height="90"/></svg>'
    text = check_numbers.svg_text(svg)
    assert text == "Arch\ndesign budgets · 50 ms · 1 s\n6 dashboards"
    assert findings(text, None) == ["6"]


def test_repository_architecture_svg_has_no_untraceable_number() -> None:
    svg = ROOT / check_numbers.ARCHITECTURE_SVG
    if not svg.is_file():
        pytest.skip("architecture.svg is not in this checkout")
    assert findings(check_numbers.svg_text(svg.read_text(encoding="utf-8")), None) == []


def test_demo_md_has_no_number_that_needs_an_artifact() -> None:
    """PR-31 B6: DEMO.md is scanned, and as a script it must pass even with no artifact at all."""
    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    assert findings(check_numbers.strip_markdown(demo), None) == []
    for phrase in ("few hours", "ساعات قليلة", "already typed their card"):
        assert phrase not in demo


def test_pdf_decimal_rejoin_and_slide_order(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    with zipfile.ZipFile(deck, "w") as archive:
        for index in (10, 2, 1):
            archive.writestr(f"ppt/slides/slide{index}.xml", f"<a:p><a:r><a:t>slide {index}</a:t></a:r></a:p>")
    assert check_numbers.pptx_text(deck).splitlines() == ["slide 1", "slide 2", "slide 10"]


def test_cli_scans_deck_readme_and_demo(tmp_path: Path) -> None:
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
    (root / "docs").mkdir()
    (root / "docs" / "DEMO.md").write_text("Say: these pages are caught in 3 seconds.\n", encoding="utf-8")
    assert check_numbers.main(args) == 1  # DEMO.md is scanned
    (root / "docs" / "DEMO.md").write_text("Say: no warning signs found.\n", encoding="utf-8")
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
    sections = {s.key: s for s in content.build(NONE, None, "")}
    assert "Evaluation in progress" in sections["results"].lead
    assert sections["results"].table == ()
    assert "evaluation in progress" in " ".join(line.text for line in sections["deployment"].lines)
    assert findings(content.all_text(list(sections.values())), None) == []


def test_results_copy_artifact_values_verbatim_with_scope(tmp_path: Path) -> None:
    data = {**ARTIFACT, "scope": "offline T1 + arbiter on URLs", "not_evaluated": ["zero_day", "sandbox_tier_T2"]}
    data["metrics"] = {**ARTIFACT["metrics"], "val.recall": 0.5}
    (tmp_path / "a.json").write_text(json.dumps(data), encoding="utf-8")
    loaded = artifact.load(tmp_path)
    results = next(s for s in content.build(ALL, loaded, "") if s.key == "results")
    table = dict(results.table)
    assert table["test.recall"] == "0.9312   ci95 [0.9, 1.0]"
    assert table["test.n"] == "412"
    assert "val.recall" not in table and "More metrics" in results.note  # the test split is the headline
    assert "offline T1 + arbiter on URLs" in results.lead and "not a measurement of the full system" in results.lead
    assert "zero_day" in results.extra["not_evaluated"]
    text = content.all_text([results])
    assert findings(text, check_numbers.traceable_for(loaded)) == []


def test_unshipped_lines_are_marked_planned_and_listed_on_the_roadmap() -> None:
    sections = {s.key: s for s in content.build(NONE, None, "")}
    assert all(line.planned for line in sections["solution"].lines)
    assert any("Not built yet" in line.text and "MCP server" in line.text for line in sections["roadmap"].lines)
    shipped = {s.key: s for s in content.build(ALL, None, "")}
    assert not any(line.planned for s in shipped.values() for line in s.lines)
    assert not any("Not built yet" in line.text for line in shipped["roadmap"].lines)


def test_every_system_claim_is_gated_on_a_capability() -> None:
    """PR-31 B7: outside the problem framing, the roadmap and the team slide, no line is an ungated fact."""
    sections = {s.key: s for s in content.build(NONE, None, "")}
    for key in ("solution", "demo", "architecture", "agent", "security", "integration"):
        ungated = [line.text for line in sections[key].lines if line.cap is None]
        assert ungated == [], (key, ungated)
    deployment = [line.text for line in sections["deployment"].lines if line.cap is None]
    assert len(deployment) == 1 and deployment[0].startswith("Cost per check: evaluation in progress")
    text = content.all_text(list(sections.values()))
    assert "Recorded on the real screen" not in text
    for cap in {line.cap for s in sections.values() for line in s.lines if line.cap}:
        assert cap in capabilities.BY_ID, cap


def test_pipeline_and_audit_lines_follow_their_own_capabilities() -> None:
    caps = {**NONE, "pipeline": True}
    lines = {
        line.text: line.planned
        for line in next(s for s in content.build(caps, None, "") if s.key == "architecture").lines
    }
    assert lines["Gateway to API; jobs and verdict events travel on Redis streams."] is False
    assert lines["PostgreSQL stores verdicts and their evidence."] is False
    assert lines["Incidents and every Sentinel action go to an append-only audit log."] is True


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
    assert capabilities.probe(tmp_path, "nogrep:a/**/*.py::not_supported_yet")
    assert not capabilities.probe(tmp_path, "nogrep:a/**/*.py::check_url")
    assert not capabilities.probe(tmp_path, "nogrep:b/**/*.py::anything")  # no file: the feature is not there
    assert capabilities.detect(tmp_path) == NONE


def test_non_url_checks_are_not_shipped_while_the_worker_stub_remains(tmp_path: Path) -> None:
    worker = tmp_path / "services" / "worker" / "src" / "falcon_worker"
    worker.mkdir(parents=True)
    (worker / "consumer.py").write_text('reason = "input_type_not_supported_yet:message"\n', encoding="utf-8")
    assert not capabilities.probe(tmp_path, capabilities.WORKER_KIND_STUB)
    (worker / "consumer.py").write_text("handle(job)\n", encoding="utf-8")
    assert capabilities.probe(tmp_path, capabilities.WORKER_KIND_STUB)


def test_gate_probe_reads_status_md(tmp_path: Path) -> None:
    status = tmp_path / "STATUS.md"
    row = "| Gate | Target | State |\n|---|---|---|\n| G1 `make smoke` URL → verdict | Mon 06:00 | {} |\n"
    for state, expected in (
        ("—", False),
        ("⏳ in progress", False),
        ("not passed", False),
        ("✅ Mon 09:10", True),
        ("passed (smoke 8/8, real worker)", True),
        ("done", True),
    ):
        status.write_text(row.format(state), encoding="utf-8")
        assert capabilities.gate_passed(tmp_path, "G1") is expected, state
        assert capabilities.probe(tmp_path, "gate:G1") is expected
    assert not capabilities.gate_passed(tmp_path, "G4")
    status.unlink()
    assert not capabilities.gate_passed(tmp_path, "G1")


def test_end_to_end_claims_need_the_gate_and_the_wiring() -> None:
    by_id = capabilities.BY_ID
    for cap in (
        "url_check",
        "brand_check",
        "message_check",
        "verified_official",
        "rest_api",
        "mcp",
        "pwa",
        "extension",
    ):
        assert "gate:G1" in by_id[cap].probes, cap
    assert capabilities.T3_WIRED in by_id["investigator"].probes
    assert capabilities.EXTRACTOR_WIRED in by_id["injection_defence"].probes
    assert capabilities.ROUTER_WIRED in by_id["sovereign"].probes


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


def test_ollama_is_listed_only_with_a_call_site(tmp_path: Path) -> None:
    src = tmp_path / "services" / "sentinel" / "src" / "falcon_sentinel"
    src.mkdir(parents=True)
    (src / "llm.py").write_text('"""Talks to Ollama at OLLAMA_BASE_URL."""\n# ollama later\n', encoding="utf-8")
    assert tools_used.model_tools(tmp_path) == []
    (src / "main.py").write_text("client = Client(settings.ollama_base_url)\n", encoding="utf-8")
    assert tools_used.model_tools(tmp_path) == ["Ollama (local models)"]


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
