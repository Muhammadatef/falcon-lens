"""pytest fixtures for scoring tests."""

from __future__ import annotations

import pytest
from scoring_helpers import Factory, make_evidence


@pytest.fixture
def mk() -> Factory:
    return make_evidence
