"""Cost estimation (USD per 1M tokens, OpenRouter default-route prices 2026-07)."""

PRICES: dict[str, tuple[float, float]] = {
    "qwen/qwen3-vl-235b-a22b-instruct": (0.20, 0.88),
    "qwen/qwen3-vl-235b-a22b-thinking": (0.26, 2.60),
    "qwen/qwen3-vl-30b-a3b-instruct": (0.13, 0.52),
    "qwen/qwen3-vl-30b-a3b-thinking": (0.13, 1.56),
    "qwen/qwen3-vl-32b-instruct": (0.104, 0.416),
    "qwen/qwen3-vl-8b-instruct": (0.117, 0.455),
    "qwen/qwen3-vl-8b-thinking": (0.117, 1.365),
    "qwen3-vl-plus": (0.20, 1.60),
    "qwen3-vl-flash": (0.05, 0.40),
}


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICES.get(model_name, (0.0, 0.0))
    return round((input_tokens * inp + output_tokens * out) / 1_000_000, 6)
