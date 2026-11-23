# ruff: noqa: E501, S603, S607
"""Build every Part B document, then check them. Regenerates when the published eval artifacts change.

    uv run --no-project --with-requirements submission/build/requirements.txt --with pyyaml python submission/build/build_all.py

Outputs (committed): submission/FalconLens_Project_Description.docx and .pdf, submission/FalconLens_Cookbook.pdf.
Scratch (gitignored): work/submission-build/ (PNG renders, HTML), submission/build/cookbook.rendered.md.
Needs Chromium for Playwright once: `uv run --no-project --with playwright==1.65.2 python -m playwright install chromium`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_cookbook  # noqa: E402
import build_description  # noqa: E402
import check  # noqa: E402


def main() -> int:
    build_description.main()
    build_cookbook.main()
    return check.main()


if __name__ == "__main__":
    raise SystemExit(main())
