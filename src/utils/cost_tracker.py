"""Логирование расходов на API в таблицу api_costs."""

from src.db.supabase_client import get_supabase

# Примерные цены за 1M токенов (input/output) — обновлять при изменении прайса
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini":        (0.15,  0.60),
    "gpt-4o":             (2.50, 10.00),
    "claude-3.5-sonnet":  (3.00, 15.00),
    "whisper-1":          (0.006, 0.0),     # $0.006 за минуту, считаем по tokens_in
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Примерная стоимость вызова в USD."""
    prices = MODEL_PRICES.get(model, (0.15, 0.60))
    cost = (tokens_in / 1_000_000 * prices[0]) + (tokens_out / 1_000_000 * prices[1])
    return round(cost, 6)


async def log_api_cost(
    user_id: int | None,
    bot_source: str | None,
    model: str,
    tokens_in: int,
    tokens_out: int,
    task_type: str | None = None,
) -> None:
    """Записать расход в таблицу api_costs."""
    cost = _estimate_cost(model, tokens_in, tokens_out)
    get_supabase().table("api_costs").insert({
        "user_id": user_id,
        "bot_source": bot_source,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
        "task_type": task_type,
    }).execute()
