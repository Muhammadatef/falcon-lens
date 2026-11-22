import json

import pytest

from falcon_core.scoring.t1_model import ModelError, load_t1_model


def test_tampered_model_refused(tmp_path):
    (tmp_path / "t1_hgb.joblib").write_bytes(b"not a model")
    (tmp_path / "t1_hgb.meta.json").write_text(json.dumps({"model_sha256": "0" * 64, "feature_names": []}))
    with pytest.raises(ModelError):
        load_t1_model(tmp_path)


def test_committed_model_loads_and_scores():
    m = load_t1_model()
    assert m.meta["model_id"] == "t1_hgb"
    p = m.p_clf_many(["https://www.adpolice.gov.ae/", "http://secure-login-verify.example.xyz/a/b/c?x=1&y=2"])
    assert all(0.0 <= v <= 1.0 for v in p)
