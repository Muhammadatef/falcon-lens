#!/usr/bin/env python3
"""Fit the cosine threshold of the voice FAQ semantic fallback on the labelled paraphrase set.

    OLLAMA_BASE_URL=http://localhost:11434 uv run python scripts/voice_faq_fit.py

Embeds the FAQ question bank and every labelled utterance (tests/voice/data/voice_faq_labelled.json in falcon_core,
24 off-topic or injection negatives and 44 paraphrases incl. Emirati) with the local embedding model, then picks the
threshold: the LOWEST value with zero off-topic false positives, with a small safety margin above the best negative.
Writes evals/results/published/fits/voice_faq_threshold_fit.json. The data are synthetic and single-author.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages/falcon_core/src"))

from falcon_core.voice.faq import match_rules  # noqa: E402
from falcon_core.voice.faq_semantic import DEFAULT_MODEL, FaqSemantic, ollama_embedder  # noqa: E402

DATA = ROOT / "packages/falcon_core/tests/voice/data/voice_faq_labelled.json"
OUT = ROOT / "evals/results/published/fits/voice_faq_threshold_fit.json"
MARGIN = 0.01


async def main() -> int:
    items = json.loads(DATA.read_text(encoding="utf-8"))
    embed = ollama_embedder()
    sem = FaqSemantic(embed, timeout_s=30.0)
    if not await sem.warm():
        print("embedding model unreachable (OLLAMA_BASE_URL, qwen3-embedding:4b)", file=sys.stderr)
        return 2
    rows = []
    for it in items:
        ranked = await sem.scores(it["text"])
        rows.append({"label": it["label"], "style": it["style"], "top": ranked[0][0], "score": round(ranked[0][1], 4)})
    neg = [r["score"] for r in rows if r["label"] is None]
    pos = [r for r in rows if r["label"] is not None]
    best_neg = max(neg)
    thr = round(best_neg + MARGIN, 2)
    hits = [r for r in pos if r["score"] >= thr and r["top"] == r["label"]]
    wrong = [r for r in pos if r["score"] >= thr and r["top"] != r["label"]]
    rule_hits = sum(1 for it in items if it["label"] and match_rules(it["text"]) == it["label"])
    combined = sum(
        1
        for it, r in zip(items, rows, strict=True)
        if it["label"] and (match_rules(it["text"]) == it["label"] or (r["score"] >= thr and r["top"] == it["label"]))
    )
    grid = []
    for t in [round(0.40 + 0.02 * i, 2) for i in range(0, 21)]:
        grid.append(
            {
                "threshold": t,
                "recall": round(sum(1 for r in pos if r["score"] >= t and r["top"] == r["label"]) / len(pos), 4),
                "wrong_answer_rate": round(
                    sum(1 for r in pos if r["score"] >= t and r["top"] != r["label"]) / len(pos), 4
                ),
                "offtopic_false_positive_rate": round(sum(1 for s in neg if s >= t) / len(neg), 4),
            }
        )
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: S607
    out = {
        "kind": "voice_faq_semantic_threshold_fit",
        "label": "synthetic, single-author labelled paraphrases (Emirati, MSA, English); not a held-out external set",
        "procedure": "lowest cosine threshold with zero off-topic false positives, plus a 0.01 margin above the best negative",  # noqa: E501
        "model": DEFAULT_MODEL,
        "git_sha": sha,
        "dataset_hash": hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "n_paraphrases": len(pos),
        "n_offtopic": len(neg),
        "best_offtopic_score": best_neg,
        "chosen": {
            "threshold": thr,
            "recall": round(len(hits) / len(pos), 4),
            "wrong_answer_rate": round(len(wrong) / len(pos), 4),
            "offtopic_false_positive_rate": round(sum(1 for s in neg if s >= thr) / len(neg), 4),
        },
        "keyword_rules_alone_recall": round(rule_hits / len(pos), 4),
        "rules_then_embedding_recall": round(combined / len(pos), 4),
        "grid": grid,
        "scores": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["chosen"]), "rules-only recall", out["keyword_rules_alone_recall"], "best negative", best_neg)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
