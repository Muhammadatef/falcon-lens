"""Items 1 and 2 (offline parts): real vs synthetic split of the published metrics, and template faithfulness.

Needs the private item cache (``data/private/datasets/items.jsonl``) for the real URL items; the synthetic items
come from ``evals.gaps.corpus``. No network, no model call. Real URLs never appear in an artifact.

No tuning happens here: the fitted T1 model, thresholds and parameters are used as shipped; val/test items are only
scored, never used to fit anything.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import numpy as np

from evals.common import ITEMS_MANIFEST, PARAMS_YAML, read_jsonl
from evals.datasets.build import Item, load_private_items, verify_private_items
from evals.gaps import corpus
from evals.gaps.common import PUBLISHED, envelope, not_evaluated, rate, write_artifact
from evals.gaps.faithfulness import doc_from_result, mutation_report, summarise
from evals.harness import metrics as M
from evals.harness.message_path import score_message
from evals.train.pipeline import score_url
from falcon_core.scoring.params import load_params
from falcon_core.scoring.t1_model import load_t1_model


def _synthetic_url_items() -> list[Item]:
    """Falcon Demo Bank fixture URLs as labelled items (kind=synthetic), dedup by URL."""
    seen: dict[str, Item] = {}
    for it in [*corpus.ITEMS, *corpus.new_lookalike_set()]:
        if it.kind != "page" or not it.url or it.url in seen:
            continue
        seen[it.url] = Item(
            item_id=it.item_id,
            url=it.url,
            label=int(it.phish),
            domain_hmac="",
            first_seen="2026-11-23T00:00:00Z",
            category="synthetic_fixture_"
            + ("official" if "official" in it.tags else ("phish" if it.phish else "benign")),
            kind="synthetic",
            source="synthetic fixture",
            on_blocklist=False,
            zero_day=False,
            official="official" in it.tags,
        )
    return list(seen.values())


def _manifest_counts() -> dict[str, Any]:
    c: Counter[tuple[str, str, int]] = Counter()
    for r in read_jsonl(ITEMS_MANIFEST):
        c[(str(r["kind"]), str(r["split"]), int(r["label"]))] += 1  # type: ignore[call-overload]
    out: dict[str, Any] = {}
    for (kind, split, label), n in sorted(c.items()):
        out.setdefault(kind, {}).setdefault(split, {})["phishing" if label else "legit"] = n
    return out


def _score_set(items: list[Item], model: Any, params: Any) -> dict[str, Any]:
    p_clf = model.p_clf_many([i.url for i in items])
    scored = [score_url(i.url, float(pc), params, True) for i, pc in zip(items, p_clf, strict=True)]
    y = np.array([i.label for i in items])
    verdict = np.array([s.result.verdict for s in scored])
    warn = verdict != "no_warning_signs"
    dang = verdict == "dangerous"
    n_ph, n_lg = int(y.sum()), int((1 - y).sum())
    return {
        "n": len(items),
        "n_phishing": n_ph,
        "n_legit": n_lg,
        "recall_warning": rate(int((warn & (y == 1)).sum()), n_ph),
        "fpr_warning": rate(int((warn & (y == 0)).sum()), n_lg),
        "recall_dangerous": rate(int((dang & (y == 1)).sum()), n_ph),
        "fpr_dangerous": rate(int((dang & (y == 0)).sum()), n_lg),
        "precision_warning": rate(int((warn & (y == 1)).sum()), int(warn.sum())),
        "verdict_counts": dict(Counter(verdict.tolist())),
        "operating_point": "warning = suspicious or dangerous; offline T1 + arbiter on the URL only (no page tier, no LLM)",  # noqa: E501
    }


def synthetic_split() -> dict[str, Any]:
    items = load_private_items()
    rows = read_jsonl(ITEMS_MANIFEST)
    verify_private_items(items, rows)
    model = load_t1_model()
    params = load_params(PARAMS_YAML)
    counts = _manifest_counts()
    real_total = sum(sum(s.values()) for s in counts.get("real", {}).values())
    synth_total = sum(sum(s.values()) for s in counts.get("synthetic", {}).values())

    real_eval = {}
    for split in ("val", "test"):
        its = [i for i in items if i.split == split and i.kind == "real"]
        real_eval[split] = _score_set(its, model, params)
    syn_items = _synthetic_url_items()
    synthetic_eval = _score_set(syn_items, model, params)
    synthetic_eval["kinds"] = {
        "lookalike_or_generic_phishing_fixtures": sum(1 for i in syn_items if i.label == 1),
        "benign_fixtures_including_official": sum(1 for i in syn_items if i.label == 0),
    }
    synthetic_eval["caveat"] = (
        "The .test top-level domain itself raises the URL-only prior, so benign .test fixtures are flagged more "
        "often than benign real sites; read this FPR as an upper-bound artifact of reserved hosts, not as a field FPR."
    )

    # message-text path on the synthetic fixture messages (no link verdict: they carry no link)
    msgs = [i for i in corpus.ITEMS if i.kind == "message" and i.text]
    msg_ver = [score_message(i.text or "", "no_warning_signs", params) for i in msgs]
    y = np.array([int(i.phish) for i in msgs])
    w = np.array([v != "no_warning_signs" for v in msg_ver])
    message_synth = {
        "n": len(msgs),
        "n_phishing": int(y.sum()),
        "n_legit": int((1 - y).sum()),
        "recall_warning": rate(int((w & (y == 1)).sum()), int(y.sum())),
        "fpr_warning": rate(int((w & (y == 0)).sum()), int((1 - y).sum())),
        "scope": "offline message-text signals + arbiter (H5 floor needs a link), synthetic messages written for this suite",  # noqa: E501
        "model_used": "none (deterministic message signals only)",
    }

    main_files = sorted(PUBLISHED.glob("*.json"))
    main_metrics = json.loads(main_files[-1].read_text())["metrics"] if main_files else {}
    cap = json.loads((PUBLISHED / "fits" / "model_cap_fit.json").read_text()).get("chosen", {})
    fp_files = sorted((PUBLISHED / "fp_regress").glob("*.json"))
    latest_fp = json.loads(fp_files[-1].read_text()) if fp_files else {}
    table = [
        {
            "published_metric_family": "main eval, val and test (URL, T1 + arbiter)",
            "real": {"val_n": real_eval["val"]["n"], "test_n": real_eval["test"]["n"]},
            "synthetic": {"n": 0, "note": "the frozen manifest holds zero synthetic items by design"},
            "where": "evals/results/published/<timestamp>.json (unchanged)",
        },
        {
            "published_metric_family": "message_path (real URL items wrapped in 4 synthetic message templates)",
            "real": {
                "labels_and_urls": "real URL items",
                "n_val": main_metrics.get("val.message_path.n"),
                "n_test": main_metrics.get("test.message_path.n"),
            },
            "synthetic": {"message_text": "templates are synthetic and labelled so in the artifact"},
            "note": "mixed provenance by construction: real item, synthetic wrapper; it is not a synthetic-only metric",
        },
        {
            "published_metric_family": "fp_regress (held-out legit domains through the running stack)",
            "real": {
                "n": latest_fp.get("n"),
                "set": latest_fp.get("set"),
                "artifact": fp_files[-1].name if fp_files else None,
            },
            "synthetic": {"n": 0},
        },
        {
            "published_metric_family": "model_cap_fit (fits)",
            "real": {"n_legit": cap.get("n_legit"), "n_phishing": cap.get("n_phishing"), "split": "val"},
            "synthetic": {"n": 0},
        },
        {
            "published_metric_family": "red-team (PR #84 and the harness reference run)",
            "real": {"n": 0},
            "synthetic": {
                "n": "all cases",
                "note": "invented Falcon Demo Bank fixtures; reported by PR #84, not duplicated here",
            },
        },
    ]
    consistency = {
        split: {
            "recall_matches_main_artifact": abs(
                real_eval[split]["recall_warning"]["value"] - float(main_metrics.get(f"{split}.recall", -1))
            )
            < 1e-5,
            "fpr_matches_main_artifact": abs(
                real_eval[split]["fpr_warning"]["value"] - float(main_metrics.get(f"{split}.fpr", -1))
            )
            < 1e-5,
        }
        for split in ("val", "test")
    }
    body = {
        "consistency_with_main_artifact": {
            "artifact": main_files[-1].name if main_files else None,
            "note": "the real-item rows below re-score the same frozen split with the same shipped model; they must reproduce the headline",  # noqa: E501
            **consistency,
        },
        "manifest_counts_by_kind_split_label": counts,
        "manifest_totals": {"real": real_total, "synthetic": synth_total},
        "real_items_scored": real_eval,
        "synthetic_url_items_scored": synthetic_eval,
        "synthetic_messages_scored": message_synth,
        "provenance_table": table,
        "separation_rule": "real and synthetic numbers are never pooled; no model or threshold was fitted or tuned on any of these items",  # noqa: E501
    }
    return envelope(
        "synthetic_split",
        scope="real vs synthetic split of the offline metrics (URL T1 + arbiter, message text); no LLM, no page tier",
        provenance="real (manifest items) and synthetic (Falcon Demo Bank fixtures), reported side by side",
        n={
            "real_val": real_eval["val"]["n"],
            "real_test": real_eval["test"]["n"],
            "synthetic_urls": len(syn_items),
            "synthetic_messages": len(msgs),
        },
        route="none",
        model_ids={"t1": "t1_hgb (fitted artifact as shipped)", "llm": "none"},
        body=body,
        notes=["Real URLs are never written to an artifact; only counts and rates."],
    )


def faithfulness_offline() -> dict[str, Any]:
    """R1-R4 on every val and test verdict of the offline T1 + arbiter pipeline (386 real items)."""
    items = load_private_items()
    model = load_t1_model()
    params = load_params(PARAMS_YAML)
    out: dict[str, Any] = {}
    all_docs: list[dict[str, Any]] = []
    for split in ("val", "test"):
        its = [i for i in items if i.split == split and i.kind == "real"]
        p_clf = model.p_clf_many([i.url for i in its])
        docs = []
        for i, pc in zip(its, p_clf, strict=True):
            s = score_url(i.url, float(pc), params, True)
            docs.append(doc_from_result(s.result, s.result.verdict))
        out[split] = summarise(docs)
        out[split]["verdict_mix"] = dict(Counter(d["verdict"] for d in docs))
        all_docs += docs
    out["mutation_check"] = {
        "what": "deliberately unfaithful copies of the verdicts above; the checker must reject each",
        "caught": mutation_report(all_docs),
    }
    return out


def write_all() -> list[str]:
    paths = [write_artifact("synthetic_split", synthetic_split())]
    return [str(p) for p in paths]


__all__ = ["faithfulness_offline", "synthetic_split", "write_all", "not_evaluated", "M"]
