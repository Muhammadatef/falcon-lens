#!/usr/bin/env python3
# ruff: noqa: E501  (the card is copy-paste text)
"""Generate submission/PROJECT_CARD.md: the exact answer for every submission-form field.

    uv run --with-requirements scripts/submission/requirements.txt python submission/build/project_card.py [--check]

- Descriptions: scripts/submission/descriptions.py composes them from the capabilities detected in
  this checkout, so they cannot claim anything that is not built. The script fails (exit 1) when
  either is over 600 characters, outside two to four sentences, says "safe" or implies an endorsement.
- Tools used: generated from uv.lock, web/pnpm-lock.yaml, docker-compose.yml, the source imports and
  the model defaults (scripts/submission/tools_used.py and scripts/readme_stack.py). Nothing is typed.
- No number is typed. The card quotes the length of each text, which the script measures.
- No e-mail address appears anywhere in the card.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from submission import capabilities as caps_mod  # noqa: E402
from submission import descriptions, tools_used  # noqa: E402

OUT = ROOT / "submission" / "PROJECT_CARD.md"
TITLE = "عدسة الصقر | Falcon Lens"
REPO_URL = "https://github.com/Muhammadatef/falcon-lens"
TEAM = [
    ("Mohamed Atef", "Team leader"),
    ("Abdulrahman Alseiari", "Team member"),
    ("MokhmadSalakh Salamov", "Team member"),
]
# Libraries that are real but too small to name on a form (same idea as MINOR_LIBS in scripts/readme_stack.py).
MINOR = {
    "httpcore", "joblib", "jsonschema", "pyyaml", "python-ulid", "pydantic-settings", "argon2-cffi", "numpy", "pillow",
    "asyncpg", "httpx", "psycopg", "nginx (test fixtures)", "pytest", "ruff", "mypy", "claude code (development agents)",
    "react dom",
}  # fmt: skip
FIRST = ("AI models", "Languages and runtime")


def _readme_stack() -> ModuleType:
    spec = importlib.util.spec_from_file_location("readme_stack", ROOT / "scripts" / "readme_stack.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load scripts/readme_stack.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["readme_stack"] = mod
    spec.loader.exec_module(mod)
    return mod


def dspy_shipped(root: Path) -> bool:
    """DSPy is listed only when it is locked AND imported by shipped code."""
    lock = root / "uv.lock"
    if not lock.is_file():
        return False
    names = {p["name"] for p in tomllib.loads(lock.read_text(encoding="utf-8")).get("package", [])}
    if "dspy" not in names:
        return False
    return any(
        re.search(r"(?m)^\s*(?:from|import)\s+dspy\b", path.read_text(encoding="utf-8", errors="ignore"))
        for pattern in ("packages/*/src/**/*.py", "services/*/src/**/*.py", "services/sentinel/sentinel_core/**/*.py")
        for path in root.glob(pattern)
    )


def shipped_tools(root: Path = ROOT) -> list[tuple[str, list[str]]]:
    """(category, names without versions) of everything the shipped code uses. Source of truth for the card and the deck."""
    rs = _readme_stack()
    cats = {title: list(items) for title, items in tools_used.names(root)}
    # scikit-learn: a runtime dependency that the source probes of tools_used miss
    if "scikit-learn" in rs.runtime_deps(root):
        cats.setdefault("Detection and ML", []).append("scikit-learn")
    models = [label.replace(" (local)", " (local model)") for label, _ in rs._models()]
    if models:
        cats["AI models"] = [*models, *cats.get("AI models", [])]
    if dspy_shipped(root):
        cats.setdefault("AI models", []).append("DSPy")
    makefile = root / "Makefile"
    if makefile.is_file() and "cloudflared" in makefile.read_text(encoding="utf-8"):
        cats.setdefault("Data and infrastructure", []).append("Cloudflare Tunnel")
    web = cats.get("Web", [])
    fonts = [n for n in web if n.startswith("@fontsource-variable/")]
    if fonts:
        cats["Web"] = [n for n in web if n not in fonts] + ["Readex Pro (font)", "JetBrains Mono (font)"]
    order = [*FIRST, *[t for t in cats if t not in FIRST]]
    out = []
    for title in order:
        names = [n for n in cats.get(title, []) if n.lower() not in MINOR]
        if names:
            out.append((title, names))
    return out


def tools_line(root: Path = ROOT) -> str:
    seen: set[str] = set()
    flat = []
    for _title, names in shipped_tools(root):
        for name in names:
            key = re.sub(r"\s*\(.*\)$", "", name).lower()
            if key not in seen:
                seen.add(key)
                flat.append(name)
    return ", ".join(flat)


def build(root: Path = ROOT) -> tuple[str, list[str], dict[str, int]]:
    caps = caps_mod.detect(root)
    texts = {lang: descriptions.compose(caps, lang) for lang in ("en", "ar")}
    problems = [f"description_{lang}: {err}" for lang, text in texts.items() for err in descriptions.check(text)]
    tools = tools_line(root)
    if not tools:
        problems.append("tools line is empty")
    problems += [f"tools: {e}" for e in descriptions.wording_errors(tools)]
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", TITLE + tools + "".join(texts.values()) + "".join(n for n, _ in TEAM)):
        problems.append("an e-mail address appears in the card")
    count = {lang: descriptions.count_chars(text) for lang, text in texts.items()}
    sentences = {lang: len(descriptions.sentences(text)) for lang, text in texts.items()}
    team = "\n".join(f"- {name}, {role}" for name, role in TEAM)
    card = f"""# Project card: exact answers for the submission form

Generated by `make submission` (`submission/build/project_card.py`). Do not edit by hand: change the source and rebuild.
Each block below is meant to be copied as it is. The length lines are measured by the script, which fails the build when a text breaks the form limits.

## Project Title / Name

```text
{TITLE}
```

## Brief Description (English)

Length: {count["en"]} of {descriptions.MAX_CHARS} characters, {sentences["en"]} sentences. Limit: two to four sentences.

```text
{texts["en"]}
```

## Brief Description (Arabic)

Length: {count["ar"]} of {descriptions.MAX_CHARS} characters, {sentences["ar"]} sentences. Use it only if the form accepts Arabic.

```text
{texts["ar"]}
```

## Tools Used

Comma-separated. Generated from the lockfiles, the compose file, the source imports and the model defaults, so it lists only what the shipped code uses.

```text
{tools}
```

## Repository URL

```text
{REPO_URL}
```

## Presentation (.pptx or .pdf, at most 20 MB)

- File to upload: `submission/FalconLens_ScamShield.pptx` (PDF copy: `submission/FalconLens_ScamShield.pdf`).
- Google Slides: Google Drive, New, File upload, the .pptx; then right-click it, Open with, Google Slides. The deck uses Readex Pro, a Google Font, so it displays as designed. Check every slide once after the import.
- If the form asks for a link, share the Google Slides file as "Anyone with the link, Viewer" and paste it here:

```text
<PASTE THE GOOGLE SLIDES LINK HERE, OR LEAVE BLANK IF THE FORM TAKES THE FILE>
```

## Document (.docx or .pdf)

- File to upload: `submission/FalconLens_Project_Description.pdf` (or `.docx`), the project description document.

## Demo Video URL (one minute, recorded by the owner)

- Record it with `submission/DEMO_SCRIPT.md`: real screen, real voice. No AI-generated video or voice is accepted.
- Upload it as Unlisted on YouTube (or another host the form accepts), open the link once in a private window to check it plays, and paste it here:

```text
<PASTE THE VIDEO URL HERE AFTER RECORDING>
```

## Team (names only)

{team}

## Before you press submit

- Run `SUBMISSION_STRICT=1 make submission`: it fails when a number cannot be traced to an evaluation artifact or when the end-to-end check is not shipped.
- Read `submission/CHECKLIST.md` (capabilities, file sizes, owner checks).
- The independence line stays on every public page and slide: an independent project, not affiliated with or endorsed by Abu Dhabi Police, and not connected to any police system.
"""
    return card, problems, count


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument(
        "--check", action="store_true", help="do not write; fail when the file on disk differs from a fresh build"
    )
    args = ap.parse_args(argv)
    card, problems, count = build(args.root.resolve())
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    if args.check:
        if not args.out.is_file() or args.out.read_text(encoding="utf-8") != card:
            print(f"ERROR: {args.out} is out of date: run `make submission`", file=sys.stderr)
            return 1
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(card, encoding="utf-8")
    for lang in ("en", "ar"):
        print(f"description_{lang}: {count[lang]}/{descriptions.MAX_CHARS} characters")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
