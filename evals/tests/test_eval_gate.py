import copy
import json

from evals import gate


def _doc(recall=0.95, fpr=0.01, fd=0):
    return {
        "dataset_hash": "h",
        "git_sha": "s",
        "created_at": "t",
        "splits": {
            "val": {
                "overall": {"recall": {"value": recall}, "fpr": {"value": fpr}},
                "verified_official": {"false_dangerous": fd},
            }
        },
    }


def test_same_result_passes_with_llm_metrics_skipped():
    base = gate.make_baseline(_doc())
    fails, skipped = gate.compare(base, _doc())
    assert fails == [] and len(skipped) == 2


def test_regressions_fail():
    base = gate.make_baseline(_doc())
    assert gate.compare(base, _doc(recall=0.92))[0]
    assert gate.compare(base, _doc(fpr=0.03))[0]
    assert gate.compare(base, _doc(fd=1))[0]
    bad = copy.deepcopy(_doc())
    bad["injection_attack_success_rate"] = 0.02
    assert gate.compare(base, bad)[0]
    assert gate.compare(base, _doc(recall=0.94, fpr=0.015))[0] == []


def test_cli_fails_on_regressed_file(tmp_path):
    res, bl = tmp_path / "r.json", tmp_path / "b.json"
    bl.write_text(json.dumps(gate.make_baseline(_doc())))
    res.write_text(json.dumps(_doc(recall=0.5)))
    assert gate.main(["--result", str(res), "--baseline", str(bl)]) == 1
    res.write_text(json.dumps(_doc()))
    assert gate.main(["--result", str(res), "--baseline", str(bl)]) == 0
