from shared.config import ModelPrice


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int, prices: dict[str, ModelPrice]
) -> float:
    """Cost of one model's usage. Unknown models cost 0 rather than failing a review."""
    price = prices.get(model)
    if price is None:
        return 0.0
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000
