# ruff: noqa: E501
import asyncio
import json
from collections.abc import Awaitable
from pathlib import Path

import jsonschema

from falcon_core.signals.base import Evidence


def _schema() -> dict[str, object]:
    root = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "contracts" / "evidence.schema.json").is_file()
    )
    return json.loads((root / "contracts" / "evidence.schema.json").read_text())  # type: ignore[no-any-return]


def validate_evidence(evs: list[Evidence]) -> None:
    schema = _schema()
    for e in evs:
        jsonschema.validate(e.to_dict(), schema)


def run_async[T](aw: Awaitable[T]) -> T:
    async def _w() -> T:
        return await aw

    return asyncio.run(_w())
