import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from falcon_core.signals import REGISTRY


@dataclass
class Ctx:
    url: str | None = None
    text: str | None = None
    input_type: str = "url"
    http: Any = None
    cache: Any = None
    mirror: Any = None
    clock: Any = None
    brands: Any = None


def run_signal(name: str, url: str) -> list:
    _spec, fn = REGISTRY[name]
    return asyncio.run(fn(Ctx(url=url)))


@pytest.fixture
def run():
    return run_signal
