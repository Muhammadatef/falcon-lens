"""Build the offline scam-script corpus from TRAIN scam items only, and fit its similarity threshold on VAL.

Usage: ``uv run python -m evals.message_text.build_scripts``
Writes signals/message/scam_scripts.jsonl (id, label, lang, text, source, synthetic=true) and script_theta.json.
theta = max similarity of any legitimate TRAIN/VAL message to the corpus + 0.02 (floored at 0.5), so no legitimate
message in train or val matches. Test is never read.
"""

from __future__ import annotations

import json
import sys

from evals.message_text.data import dataset_hash, items
from falcon_core.signals.message import scripts as S


def main() -> int:
    train = [r for r in items("train") if r["label"] == "scam"]
    rows = [
        {
            "id": r["id"],
            "label": r["subtype"],
            "lang": r["language"],
            "text": r["text"],
            "source": "message_text/train",
            "synthetic": True,
        }
        for r in train
    ]
    S.CORPUS_FILE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    idx = S.LocalScriptIndex(rows)
    legit = [r for r in [*items("train"), *items("val")] if r["label"] != "scam"]
    worst = max((idx.nearest(r["text"], 1)[0].similarity for r in legit), default=0.0)
    theta = round(max(0.5, worst + 0.02), 4)
    S.OFFLINE_THETA_FILE.write_text(
        json.dumps(
            {
                "theta": theta,
                "max_legit_similarity": round(worst, 4),
                "n_corpus": len(rows),
                "dataset_hash": dataset_hash(),
                "fit": "legit train+val",
            },
            indent=1,
        )
        + "\n"
    )
    val = [r for r in items("val") if r["label"] == "scam"]
    hit = sum(idx.nearest(r["text"], 1)[0].similarity >= theta for r in val)
    print(f"corpus={len(rows)} theta={theta} (max legit sim {worst:.3f}); val scams matched {hit}/{len(val)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
