"""Message-path eval: wrap every URL item of a split in synthetic message templates and score it end to end.

Each URL is put into a fixed set of SYNTHETIC English/Arabic message templates (labelled synthetic in the artifact;
the labels are the URL item's label). The message is scored the way the cascade scores it: `analyze_message`
evidence, plus a `message.link_verdict` evidence for the link whose verdict is the offline T1 + arbiter verdict of
that URL (the model-cap rule included), then the arbiter with `input_type="message"` (hard rule H5 floors the
message at its worst link). Positive class = phishing; warning = suspicious or dangerous.

Offline and URL-free outputs: no page tier, no LLM, no network. Numbers are computed here, never typed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from evals.harness import metrics as M
from evals.train.pipeline import score_url
from falcon_core.cascade.evidence import from_signal, make_evidence
from falcon_core.scoring.arbiter import ArbiterContext
from falcon_core.scoring.model_cap import score_with_model
from falcon_core.scoring.params import ScoringParams
from falcon_core.signals.message.analyze import analyze_message

TEMPLATES: tuple[str, ...] = (
    "TEST MESSAGE (synthetic). Your parcel is waiting, confirm the delivery fee here: {url}",
    "TEST MESSAGE (synthetic). Account notice, please review your details: {url}",
    "TEST MESSAGE (synthetic). Have a look at this page when you have a moment {url}",
    "رسالة تجريبية (اصطناعية). تنبيه بخصوص حسابك، يرجى المراجعة: {url}",
)


def score_message(text: str, link_verdict: str, params: ScoringParams) -> str:
    analysis = analyze_message(text)
    ev = [from_signal(e) for e in analysis.evidence]
    ev.append(make_evidence("message.link_verdict", "message", {"verdict": link_verdict}, tier="T2", source="computed"))
    ctx = ArbiterContext(input_type="message", params=params)
    return str(score_with_model(ev, None, ctx).verdict)


def evaluate_message_path(
    items: Sequence[Any], p_clf: Sequence[float], params: ScoringParams, n_boot: int, seed: int
) -> dict[str, Any]:
    y: list[int] = []
    warn: list[bool] = []
    dang: list[bool] = []
    for item, pc in zip(items, p_clf, strict=True):
        link = score_url(item.url, float(pc), params).result.verdict
        for t in TEMPLATES:
            v = score_message(t.format(url=item.url), link, params)
            y.append(int(item.label))
            warn.append(v != "no_warning_signs")
            dang.append(v == "dangerous")
    ya, wa, da = np.array(y), np.array(warn), np.array(dang)

    def ci(fn: Any, pred: np.ndarray, off: int) -> dict[str, Any]:
        return M.with_ci(lambda yy, pp: fn(yy, pp.astype(bool)), ya, pred, n_boot, seed + off)

    return {
        "kind": "synthetic",
        "note": "synthetic message templates around each URL item; labels are the URL item's labels",
        "n_messages": int(len(ya)),
        "n_templates": len(TEMPLATES),
        "n_phishing": int(ya.sum()),
        "n_legit": int((1 - ya).sum()),
        "recall": ci(M.recall, wa, 100),
        "fpr": ci(M.fpr, wa, 101),
        "dangerous_recall": ci(M.recall, da, 102),
        "dangerous_fpr": ci(M.fpr, da, 103),
    }
