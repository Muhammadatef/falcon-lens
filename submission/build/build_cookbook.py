# ruff: noqa: E501
"""Build submission/FalconLens_Cookbook.pdf from submission/build/cookbook.md.

    uv run --no-project --with-requirements submission/build/requirements.txt python submission/build/build_cookbook.py

Markdown is rendered with python-markdown (tables, fenced code, Pygments colours), then printed by Chromium
with Arabic-capable fonts, an outline, page numbers and a table of contents whose page numbers come from a first
render (two passes). The Makefile target list in the appendix, and the two recipes that depend on unmerged work,
are generated from the checkout so they cannot claim a command that does not exist.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import markdown  # noqa: E402
from common import FONT_CSS, ROOT, SUBMISSION, TEAM, WORK, heading_pages, html_to_pdf  # noqa: E402
from pygments.formatters import HtmlFormatter  # noqa: E402

SRC = Path(__file__).resolve().parent / "cookbook.md"
PDF = SUBMISSION / "FalconLens_Cookbook.pdf"
RENDERED = Path(__file__).resolve().parent / "cookbook.rendered.md"


def make_targets() -> list[tuple[str, str]]:
    rows = []
    for line in (ROOT / "Makefile").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):.*?## (.*)$", line)
        if m and m.group(1) != "help":
            rows.append((m.group(1), m.group(2).strip()))
    return rows


def substitute(md: str) -> str:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    openapi = (ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8")
    targets = "| Target | What it does |\n|---|---|\n" + "\n".join(
        f"| `make {t}` | {d.replace('|', '/')} |" for t, d in make_targets()
    )
    if re.search(r"(?m)^dspy-optimize:", makefile):
        dspy = (
            "DSPy tunes the prompts offline on the validation split and freezes the compiled prompts into the repository, "
            "so nothing optimises at run time.\n\n```bash\nmake dspy-optimize LM=local     # LM=local uses the Ollama model\n```\n\n"
            "Review the diff of the compiled prompts in a PR like any other change, and never tune on the test split."
        )
    else:
        dspy = (
            "The offline DSPy optimisation pipeline is in an open pull request (ADR-002 describes it) and is not on `main` yet, so this checkout has no make target for it. "
            "The design: DSPy tunes the script-classifier and incident-summary prompts on the validation split only, and the compiled prompts are frozen into the repository, so nothing optimises at run time. "
            "When the pull request is merged, this recipe is regenerated with the real command."
        )
    if re.search(r"/v1/incidents/\{incident_id\}/trace:", openapi):
        trace = "For one incident's Sentinel run (node by node) call `GET /v1/incidents/<incident_id>/trace`."
    else:
        trace = "A per-incident view of the Sentinel's agent run (node by node) is in an open pull request and is not in this checkout, so it is not described as a command here."
    return md.replace("{{MAKE_TARGETS}}", targets).replace("{{DSPY}}", dspy).replace("{{INCIDENT_TRACE}}", trace)


CSS = (
    FONT_CSS
    + HtmlFormatter(style="default", noclasses=False).get_style_defs(".codehilite")
    + """
body{margin:0}
.cover{height:240mm;display:flex;flex-direction:column;justify-content:center;break-after:page}
.cover h1{font-size:40pt;color:var(--accent);margin:0 0 3mm 0}
.cover .ar{font-size:30pt;color:var(--accent);direction:rtl;text-align:left;margin-bottom:8mm}
.cover .sub{font-size:14pt;margin-bottom:6mm}
h1{font-size:19pt;color:var(--accent);border-bottom:2px solid var(--accent);padding-bottom:2mm;margin:0 0 4mm 0}
h2{font-size:16pt;color:var(--accent);border-bottom:1px solid var(--line);padding-bottom:1.5mm;margin:8mm 0 3mm 0;break-after:avoid}
h3{font-size:12pt;margin:6mm 0 2mm 0;break-after:avoid}
p{margin:0 0 2.6mm 0;orphans:3;widows:3}
ul,ol{margin:0 0 3mm 0;padding-left:6mm}li{margin-bottom:1mm}
table{border-collapse:collapse;width:100%;margin:2mm 0 4mm 0;font-size:8.8pt}
tr{break-inside:avoid}
th{background:var(--accent);color:#fff;text-align:left;padding:1.4mm 2mm}
td{border:1px solid var(--line);padding:1.3mm 2mm;vertical-align:top;overflow-wrap:anywhere}
tbody tr:nth-child(even) td{background:var(--bg2)}
code{font-size:8.4pt;background:#eef1f4;padding:0 .8mm;border-radius:1mm;overflow-wrap:anywhere}
pre{background:#f6f8fa;border:1px solid var(--line);border-radius:2mm;padding:2.5mm 3mm;font-size:8pt;line-height:1.4;white-space:pre-wrap;overflow-wrap:anywhere;break-inside:avoid;margin:0 0 3.5mm 0}
pre code{background:none;padding:0;font-size:8pt}
.codehilite{background:none}
blockquote{margin:3mm 0;padding:2.5mm 4mm;background:#e3f4f2;border-left:4px solid var(--accent);border-radius:2mm}
blockquote p{margin:0}
.toc{list-style:none;padding:0;margin:0}
.toc li{display:flex;gap:2mm;margin:1.2mm 0;align-items:baseline}
.toc li.l3{padding-left:7mm;font-size:9pt}
.toc a{color:inherit;text-decoration:none;font-weight:600}.toc li.l3 a{font-weight:400}
.toc .dots{flex:1;border-bottom:1px dotted #9aa7b2}
.pb{break-after:page}
a{color:var(--accent)}
"""
)


def render(md_text: str, pages: dict[str, int], date: str) -> str:
    # drop the first H1 (it is the cover title) and render the rest
    body_md = re.sub(r"\A# .*\n", "", md_text, count=1)
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "codehilite", "toc", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False, "css_class": "codehilite"}, "toc": {"toc_depth": "2-3"}},
    )
    body = md.convert(body_md)
    entries: list[tuple[int, str, str]] = []

    def flat(tokens: list[dict]) -> None:  # type: ignore[type-arg]
        for t in tokens:
            entries.append((t["level"], t["id"], t["name"]))
            flat(t.get("children", []))

    flat(md.toc_tokens)  # type: ignore[attr-defined]
    toc = "".join(
        f'<li class="l{lvl}"><a href="#{i}">{html.escape(name)}</a><span class="dots"></span><span>{pages.get(re.sub(chr(92) + "s+", "", name), "")}</span></li>'
        for lvl, i, name in entries
    )
    cover = f"""<div class="cover"><h1>Falcon Lens Cookbook</h1><div class="ar" lang="ar" dir="rtl">دليل الوصفات العملي لعدسة الصقر</div>
<div class="sub">A hands-on guide for a technical teammate: from clone to a running stack, recipes, the pull-request flow, troubleshooting and the defensive-only rules.</div>
<p>Team: {html.escape("; ".join(TEAM))}</p><p>Prepared {date}. Independent project: not affiliated with or endorsed by Abu Dhabi Police; ready to connect, not connected.</p></div>"""
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Falcon Lens Cookbook</title><style>{CSS}</style></head><body>{cover}<h1 id="toc">Contents</h1><ul class="toc">{toc}</ul><div class="pb"></div>{body}</body></html>'


def main() -> int:
    md_text = substitute(SRC.read_text(encoding="utf-8"))
    RENDERED.write_text(md_text, encoding="utf-8")  # input of verify_cookbook.py (gitignored)
    date = dt.date.today().strftime("%d %B %Y")
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "cookbook.html"
    out.write_text(render(md_text, {}, date), encoding="utf-8")
    html_to_pdf(out, PDF, "Falcon Lens Cookbook")
    pages = heading_pages(PDF)
    out.write_text(render(md_text, pages, date), encoding="utf-8")
    html_to_pdf(out, PDF, "Falcon Lens Cookbook")
    print(f"wrote {PDF.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
