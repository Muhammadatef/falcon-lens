#!/usr/bin/env python3
# ruff: noqa: E501
"""Score message texts with the deterministic message path; one variant per process (the lure flag is read at import).

    FL_UAE_LURES=0 FALCON_BRANDS_YAML=work/brands_main.yaml python -m evals.uae_coverage.messages IN.jsonl OUT.jsonl
    FL_UAE_LURES=1 FALCON_BRANDS_YAML=data/brands.yaml      python -m evals.uae_coverage.messages IN.jsonl OUT.jsonl

Input rows need ``text`` and ``label`` (scam|legitimate). Output rows keep ``id``/``label``/``subtype``/``source`` and add
``verdict``; no text is written. No LLM, no network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from falcon_core.cascade.evidence import from_signal
from falcon_core.scoring.arbiter import ArbiterContext
from falcon_core.scoring.model_cap import score_with_model
from falcon_core.scoring.params import load_params
from falcon_core.signals.message.analyze import analyze_message


def verdict(text: str) -> str:
    ev = [from_signal(e) for e in analyze_message(text).evidence]
    return str(score_with_model(ev, None, ArbiterContext(input_type="message", params=load_params())).verdict)


def main(src: str, dst: str) -> int:
    out = []
    for i, ln in enumerate(Path(src).read_text().splitlines()):
        if not ln.strip():
            continue
        r = json.loads(ln)
        out.append({"id": r.get("id", i), "label": r["label"], "subtype": r.get("subtype"), "source": r.get("source"),
                    "verdict": verdict(r["text"])})  # fmt: skip
    Path(dst).write_text("".join(json.dumps(x) + "\n" for x in out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
