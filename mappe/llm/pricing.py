"""Estimated cost per call (USD per million tokens, Claude API list prices)."""

from __future__ import annotations

from mappe.llm.client import Usage

# model: (input, output, cache read, 5-minute cache write)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def cost_usd(model: str, usage: Usage) -> float:
    prices = PRICES.get(model)
    if prices is None:
        return 0.0
    inp, out, cache_read, cache_write = prices
    return (
        usage.input_tokens * inp
        + usage.output_tokens * out
        + usage.cache_read_input_tokens * cache_read
        + usage.cache_creation_input_tokens * cache_write
    ) / 1_000_000
