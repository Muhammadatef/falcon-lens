"""T1 classifier loader: HistGradientBoosting + Platt (sigmoid) calibration fitted by ``make fit-thresholds``.

The artifact is a joblib pickle, so it is only loaded after its sha256 matches the committed metadata file
(``model/t1_hgb.meta.json``). scikit-learn is an optional dependency (extra ``t1`` / dev group): import is lazy.
Features come from ``falcon_core.signals.url.lexical.extract_features`` (pure, offline).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from falcon_core.signals.url.lexical import FEATURE_NAMES, extract_features

MODEL_DIR = Path(__file__).with_name("model")
MODEL_FILE = "t1_hgb.joblib"
META_FILE = "t1_hgb.meta.json"


class ModelError(RuntimeError):
    """Model artifact missing, tampered with, or built for a different feature set."""


@dataclass(frozen=True)
class T1Model:
    hgb: Any
    platt: Any  # LogisticRegression on logit(raw score)
    meta: dict[str, Any]

    def predict_raw(self, matrix: Any) -> Any:
        return self.hgb.predict_proba(matrix)[:, 1]

    def calibrate(self, raw: Any) -> Any:
        import numpy as np

        r = np.clip(np.asarray(raw, dtype=float), 1e-6, 1 - 1e-6)
        return self.platt.predict_proba(np.log(r / (1 - r)).reshape(-1, 1))[:, 1]

    def p_clf_many(self, urls: list[str]) -> list[float]:
        import numpy as np

        x = np.array([[extract_features(u)[n] for n in FEATURE_NAMES] for u in urls], dtype=float)
        return [float(v) for v in self.calibrate(self.predict_raw(x))]

    def p_clf(self, url: str) -> float:
        return self.p_clf_many([url])[0]


@lru_cache(maxsize=2)
def _load(directory: str) -> T1Model:
    import joblib

    d = Path(directory)
    try:
        meta = json.loads((d / META_FILE).read_text(encoding="utf-8"))
        blob = (d / MODEL_FILE).read_bytes()
    except OSError as exc:
        raise ModelError(f"T1 model not found in {d}: run `make fit-thresholds`") from exc
    if hashlib.sha256(blob).hexdigest() != meta.get("model_sha256"):
        raise ModelError("T1 model sha256 does not match its metadata; refusing to unpickle")
    if list(meta.get("feature_names", [])) != list(FEATURE_NAMES):
        raise ModelError("T1 model was trained on a different feature set; refit")
    obj = joblib.load(d / MODEL_FILE)  # noqa: S301 - integrity checked above
    return T1Model(hgb=obj["hgb"], platt=obj["platt"], meta=meta)


def load_t1_model(directory: Path | None = None) -> T1Model:
    return _load(str(directory or MODEL_DIR))
