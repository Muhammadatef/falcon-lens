"""msg-huge: an input over the hard ceiling is REJECTED (413), which the shipped red-team harness counts as held."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.redteam import shipped  # noqa: E402
from evals.redteam.generators import as_bytes, generate  # noqa: E402
from falcon_core.signals.limits import HARD_MAX_MESSAGE_CHARS  # noqa: E402
from falcon_core.signals.message.analyze import analyze_message  # noqa: E402

CASE = SimpleNamespace(floor="suspicious")
CLEAN = shipped.Side(verdict="dangerous", score=90)


def test_rejection_is_held_not_harmful() -> None:
    assert shipped.harmful(CASE, shipped.Side(rejected="413:InputTooLarge"), CLEAN, [], []) == []


def test_msg_huge_is_held_through_run_side() -> None:
    class _Cascade:
        d = SimpleNamespace(guard_policy=None)

        async def run_input(self, vid: str, kind: str, data: bytes, sink: Any, source: str = "live") -> Any:
            analyze_message(data.decode("utf-8", "replace"))  # the real analyser refuses the 1 MB message

    rig = SimpleNamespace(
        cascade=_Cascade(),
        metrics=SimpleNamespace(get=lambda _n: 0.0),
        tool_calls=[],
        llm_log=SimpleNamespace(ok=0, failed=[]),
        link_page="",
        sandbox=SimpleNamespace(default_html=""),
    )
    data = as_bytes(generate({"gen": "huge_message"}))
    assert len(data) > HARD_MAX_MESSAGE_CHARS
    side = asyncio.run(shipped.run_side(rig, "message", url=None, html=None, data=data))  # type: ignore[arg-type]
    assert side.rejected and side.error is None
    assert shipped.harmful(CASE, side, CLEAN, [], []) == []


def test_just_under_the_message_ceiling_is_judged_fully() -> None:
    link = "https://falcon-demo-bank-verify.example/login"
    pad = (HARD_MAX_MESSAGE_CHARS - len(link) - 2) // 2
    res = analyze_message("A" * pad + f" {link} " + "B" * pad)
    assert link in {c.value for c in res.children}
