"""Hard input ceilings of the deterministic analysers (docs/SCORING.md §2, ``<family>.limit_exceeded``).

Below the ceiling every input is analysed fail-closed: links are extracted from ALL of it. Above it the
analysers refuse (``InputTooLarge``): the caller answers 413 and never produces a (lower) label. The public API
is stricter than these ceilings (message 8 KB, email 2 MB, ``services/api/app.py``); the ceilings only bound
the work for callers that do not go through the API (worker, evals, integration tests).
"""

from __future__ import annotations

HARD_MAX_EMAIL_BYTES = 10 * 1024 * 1024
HARD_MAX_MESSAGE_CHARS = 256 * 1024


class InputTooLarge(ValueError):
    """Input above the hard ceiling: reject (HTTP 413), never analyse a slice of it."""
