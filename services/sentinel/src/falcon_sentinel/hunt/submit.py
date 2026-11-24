"""Submit a candidate to the existing Investigator cascade through the public API (HUNTER.md section 2).

``POST /v1/check/url`` with ``channel: "hunt"`` and the hunt key. That reuses URL validation, single-flight, the
verdict cache, rate limits and the audit trail. ``Idempotency-Key`` = candidate_id, so a crash between the POST
and the store write replays the same verdict_id instead of looking like somebody else's check.
``X-Verdict-State: cached | attached`` means a person got there first -> ``already_known`` (never "found before
a report"); its verdict_id belongs to that person's check and is NOT stored on the candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx
from sentinel_core.hunt.candidates import Candidate

Outcome = Literal["submitted", "already_known", "error"]


@dataclass(frozen=True)
class SubmitResult:
    outcome: Outcome
    verdict_id: str | None = None
    detail: str = ""


class Submitter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def submit(self, c: Candidate) -> SubmitResult:
        url = f"{c.scheme}://{c.domain}/"
        headers = {"Idempotency-Key": c.candidate_id}
        if c.provenance.get("source") == "fixture":
            headers["X-Falcon-Source"] = "fixture"  # truth label: a fixture-fed check stays `fixture`
        try:
            resp = await self.client.post("/v1/check/url", json={"url": url, "channel": "hunt"}, headers=headers)
        except httpx.HTTPError as exc:
            return SubmitResult("error", detail=type(exc).__name__)
        if resp.status_code not in (200, 202):
            return SubmitResult("error", detail=f"http_{resp.status_code}")
        try:
            vid = str(resp.json()["verdict_id"])
        except (ValueError, KeyError, TypeError):
            return SubmitResult("error", detail="bad_response")
        state = resp.headers.get("x-verdict-state", "")
        replay = resp.headers.get("idempotent-replay") == "true"
        if state in ("cached", "attached") and not replay:
            return SubmitResult("already_known", detail=state)
        return SubmitResult("submitted", verdict_id=vid)
