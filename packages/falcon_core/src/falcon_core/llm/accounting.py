"""Token usage and cost accounting.

Prices are USD per million tokens from docs/research/VERIFIED_VERSIONS.md §2 (checked 2026-11-22).
Local (Ollama) calls cost 0. Unknown cloud models are costed at the Sonnet 5.5 rate (conservative).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Price:
    input: float
    output: float
    cache_write_5m: float
    cache_read: float


_SONNET_5_5 = Price(input=2.0, output=10.0, cache_write_5m=2.50, cache_read=0.10)
_HAIKU_5_5_SMALL = Price(input=0.10, output=0.50, cache_write_5m=0.125, cache_read=0.01)
_HAIKU_5_5_LARGE = Price(input=0.50, output=2.50, cache_write_5m=0.625, cache_read=0.05)
HAIKU_TIER_TOKENS = 100_000

PRICES: dict[str, Price] = {"claude-sonnet-5-5": _SONNET_5_5, "claude-haiku-5-5": _HAIKU_5_5_SMALL}


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


def price_for(model: str, usage: Usage) -> Price:
    if model.startswith("claude-haiku-5-5"):
        return _HAIKU_5_5_LARGE if usage.prompt_tokens > HAIKU_TIER_TOKENS else _HAIKU_5_5_SMALL
    return PRICES.get(model, _SONNET_5_5)


def cost_usd(route: str, model: str, usage: Usage) -> float:
    if route != "cloud":
        return 0.0
    p = price_for(model, usage)
    return (
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_write_tokens * p.cache_write_5m
        + usage.cache_read_tokens * p.cache_read
    ) / 1_000_000
