"""Token-derived estimates; provider invoices and prices remain authoritative."""

from decimal import Decimal

# USD per million tokens, Standard short-context, checked 2026-09-26.
# Update from https://developers.openai.com/api/docs/pricing before billing analysis.
RATES = {
    "gpt-4.1-mini": ("0.40", "0.10", "1.60"),
    "gpt-5.6-luna": ("0.20", "0.02", "1.20"),
    "gpt-5.6-terra": ("2.00", "0.20", "12.00"),
    "gpt-5.6-sol": ("4.00", "0.40", "20.00"),
    "gpt-6-luna": ("0.10", "0.01", "0.50"),
    "gpt-6-sol": ("2.00", "0.20", "10.00"),
}


def usage_cost(
    model: str, input_tokens: int | None, cached_input_tokens: int | None, output_tokens: int | None
) -> float | None:
    if input_tokens is None or output_tokens is None or model not in RATES:
        return None
    cached = min(input_tokens, max(0, cached_input_tokens or 0))
    input_rate, cached_rate, output_rate = map(Decimal, RATES[model])
    amount = (
        (input_tokens - cached) * input_rate + cached * cached_rate + output_tokens * output_rate
    ) / Decimal(1_000_000)
    return float(amount.quantize(Decimal("0.000000001")))
