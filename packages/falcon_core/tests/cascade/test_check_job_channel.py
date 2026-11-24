"""The optional `channel` client marker on the job stream (docs/CONTRACTS.md, Channel)."""

from __future__ import annotations

from falcon_core.cascade import CheckJob
from falcon_core.cascade.ids import new_verdict_id

VID = new_verdict_id()


def fields(**extra: str) -> dict[str, str]:
    return {"verdict_id": VID, "input_type": "message", "payload_json": "{}", **extra}


def test_channel_round_trips_through_the_stream_fields() -> None:
    job = CheckJob.from_fields(fields(channel="voice"))
    assert job.channel == "voice"
    assert job.to_fields()["channel"] == "voice"


def test_absent_channel_is_none_and_not_written_back() -> None:
    job = CheckJob.from_fields(fields())
    assert job.channel is None
    assert "channel" not in job.to_fields()


def test_unknown_channel_is_dropped_not_fatal() -> None:
    assert CheckJob.from_fields(fields(channel="telegram")).channel is None
