"""Unit tests for scripts/demo_mode.py: plan builder, state round-trip, restore idempotency, thresholds."""

from __future__ import annotations

import json
import signal
from pathlib import Path

import demo_mode as dm

COMPOSE_LS = json.dumps(
    [
        {"Name": "falcon", "Status": "running(20)"},
        {"Name": "neo", "Status": "running(3)"},
        {"Name": "old", "Status": "exited(2)"},
        {"Name": "siyaq", "Status": "running(1), exited(1)"},
    ]
)
PS = "\n".join(
    [
        "  100  2048 /Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing --x",
        "  101  1024 /Users/x/flowplan/bin/flowplan serve",
        "  102  9999 /usr/bin/python3 demo_mode.py flowplan",
        "  103  5000 /Applications/Safari.app/Safari",
        "  104  7000 /opt/ollama serve flowplan",
    ]
)
CFG = {
    "keep_projects": ["falcon"],
    "pause_processes": ["Google Chrome for Testing", "flowplan"],
    "protect_processes": ["python", "ollama"],
}


def test_plan_pauses_only_other_running_projects() -> None:
    plan = dm.build_plan(COMPOSE_LS, "", CFG)
    assert plan.projects == ["neo", "siyaq"]  # not falcon, not the exited project


def test_plan_processes_respect_config_protect_and_own() -> None:
    plan = dm.build_plan(COMPOSE_LS, PS, CFG, own={101})
    assert [p["pid"] for p in plan.processes] == [100]  # 101 own, 102 python-protected, 103 unlisted, 104 ollama
    plan2 = dm.build_plan(COMPOSE_LS, PS, CFG)
    assert [p["pid"] for p in plan2.processes] == [100, 101]


def test_plan_never_includes_falcon_even_if_config_omits_it() -> None:
    cfg = dm.load_config(Path("/nonexistent.yaml"))
    assert dm.build_plan(COMPOSE_LS, "", cfg).projects == ["neo", "siyaq"]


def test_shipped_config_lists_no_neo_siyaq_insytra() -> None:
    cfg = dm.load_config()
    assert not any(x.lower() in ("neo", "siyaq", "insytra") for x in cfg["pause_processes"])


def test_empty_plan_says_nothing_to_pause() -> None:
    plan = dm.build_plan("[]", "", CFG)
    assert plan.empty() and plan.lines() == ["nothing to pause"]


def test_state_round_trip_and_merge(tmp_path: Path) -> None:
    p = tmp_path / "s" / "state.json"
    assert dm.load_state(p) == {"projects": [], "processes": []}
    plan = dm.build_plan(COMPOSE_LS, PS, CFG)
    state = dm.merge_state(dm.load_state(p), plan)
    dm.save_state(state, p)
    assert dm.load_state(p) == state
    again = dm.merge_state(state, plan)
    assert again == state  # idempotent union


def test_apply_then_restore_is_exact_and_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    calls: list[list[str]] = []
    kills: list[tuple[int, int]] = []
    plan = dm.build_plan(COMPOSE_LS, PS, CFG)
    dm.apply_plan(plan, p, run=lambda c: calls.append(c) or "", kill=lambda pid, s: kills.append((pid, s)))
    assert calls == [["docker", "compose", "-p", "neo", "stop"], ["docker", "compose", "-p", "siyaq", "stop"]]
    assert kills == [(100, signal.SIGSTOP), (101, signal.SIGSTOP)]
    assert all("down" not in c and "rm" not in c for c in calls)

    calls.clear()
    kills.clear()
    done = dm.restore(p, run=lambda c: calls.append(c) or "", kill=lambda pid, s: kills.append((pid, s)), ps=lambda: PS)
    assert calls == [["docker", "compose", "-p", "neo", "start"], ["docker", "compose", "-p", "siyaq", "start"]]
    assert kills == [(100, signal.SIGCONT), (101, signal.SIGCONT)]
    assert len(done) == 4
    assert dm.restore(p, run=lambda c: calls.append(c) or "", kill=lambda *_: None, ps=lambda: PS) == []


def test_restore_skips_reused_pid(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    dm.save_state({"projects": [], "processes": [{"pid": 100, "match": "x", "command": "old command"}]}, p)
    kills: list[int] = []
    dm.restore(p, run=lambda c: "", kill=lambda pid, s: kills.append(pid), ps=lambda: PS)
    assert kills == []
    assert dm.load_state(p)["processes"] == []


def test_thresholds() -> None:
    assert dm.eval_free_mem(30).status == "OK"
    assert dm.eval_free_mem(10).status == "FAIL"
    assert dm.eval_free_mem(None).status == "WARN"
    assert dm.eval_swap(100).status == "OK" and dm.eval_swap(5000).status == "FAIL"
    assert dm.eval_cpu(80).status == "OK" and dm.eval_cpu(20).status == "FAIL"
    assert dm.eval_disk(100).status == "OK" and dm.eval_disk(3).status == "FAIL"
    assert dm.eval_thermal("Note: No thermal warning level has been recorded\nCPU_Speed_Limit = 100").status == "OK"
    assert dm.eval_thermal("CPU_Speed_Limit = 70").status == "FAIL"
    assert dm.eval_latency("x", 1200, 8000).status == "OK"
    assert dm.eval_latency("x", 9000, 8000).status == "FAIL"
    assert dm.eval_latency("x", None, 8000, "Timeout").detail == "Timeout"


def test_container_health() -> None:
    assert dm.eval_containers([]).status == "FAIL"
    assert dm.eval_containers(["a\tUp 2 minutes (healthy)", "b\tUp 1 hour"]).status == "OK"
    assert dm.eval_containers(["a\tUp 2 minutes (unhealthy)"]).status == "FAIL"
    assert dm.eval_containers(["a\tUp 5 seconds (health: starting)"]).status == "FAIL"
    assert dm.eval_containers(["a\tExited (1) 2 minutes ago"]).status == "FAIL"


def test_other_projects_block_ready() -> None:
    row = dm.eval_others([{"name": "falcon", "running": 20}, {"name": "neo", "running": 3, "mem": "900 MiB"}])
    assert row.status == "FAIL" and "neo (3 containers, 900 MiB)" in row.detail
    assert dm.eval_others([{"name": "falcon", "running": 20}]).status == "OK"


def test_board_ready_only_without_fail() -> None:
    ok = [dm.Row("a", "OK", "x"), dm.Row("b", "INFO", "y"), dm.Row("c", "WARN", "z", "why")]
    assert dm.board(ok)[1] == dm.READY
    bad = [*ok, dm.Row("d", "FAIL", "q", "because")]
    text, verdict = dm.board(bad)
    assert verdict == dm.NOT_READY and "because" in text and text.endswith("NOT READY")


def test_on_without_yes_does_nothing(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        dm, "sh", lambda cmd, timeout=20.0: COMPOSE_LS if cmd[:3] == ["docker", "compose", "ls"] else ""
    )
    monkeypatch.setattr(dm, "apply_plan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("acted")))
    assert dm.cmd_on(False) == 2
    assert "docker compose -p neo stop" in capsys.readouterr().out


def test_rehearsal_messages_fallback(tmp_path: Path) -> None:
    assert dm.rehearsal_messages(tmp_path / "missing") == dm.FIXTURE_MSGS
    for i in range(3):
        (tmp_path / f"{i}.txt").write_text(f"m{i}\n")
    assert dm.rehearsal_messages(tmp_path) == ["m0", "m1", "m2"]


def test_silent_wav_is_one_second() -> None:
    assert len(dm.silent_wav()) == 44 + 16000 * 2
