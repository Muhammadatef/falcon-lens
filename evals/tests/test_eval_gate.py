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
    assert fails == [] and len([n for n in skipped if not n.startswith("message_")]) == 2


def _msg_doc(recall: float, fpr: float):
    d = _doc()
    d["splits"]["val"]["message_path"] = {"recall": {"value": recall}, "fpr": {"value": fpr}}
    return d


def test_message_path_regression_fails():
    base = gate.make_baseline(_msg_doc(0.95, 0.01))
    assert gate.compare(base, _msg_doc(0.95, 0.01))[0] == []
    assert gate.compare(base, _msg_doc(0.90, 0.01))[0]
    assert gate.compare(base, _msg_doc(0.95, 0.05))[0]


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
