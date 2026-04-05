"""Бюджетный лимитер API-расходов (daily/monthly cap).

Проверяет api_costs перед каждым LLM-вызовом.
Если лимит превышен — блокирует вызов.
"""

from datetime import datetime, timezone

import structlog

from src.config import settings
from src.db.queries import sum_api_costs

logger = structlog.get_logger()


class BudgetExceededError(Exception):
    """Лимит API-расходов превышен."""
    pass


async def check_budget() -> None:
    """Проверить дневной и месячный лимиты. Бросает BudgetExceededError если превышен."""
    now = datetime.now(timezone.utc)

    # Дневной лимит
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_total = await sum_api_costs(day_start)

    if daily_total >= settings.api_daily_limit_usd:
        logger.warning("budget_daily_exceeded", daily=daily_total, limit=settings.api_daily_limit_usd)
        raise BudgetExceededError(
            f"Дневной лимит API ({settings.api_daily_limit_usd} USD) исчерпан. "
            f"Потрачено: ${daily_total:.4f}"
        )

    # Месячный лимит
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_total = await sum_api_costs(month_start)

    if monthly_total >= settings.api_monthly_limit_usd:
        logger.warning("budget_monthly_exceeded", monthly=monthly_total, limit=settings.api_monthly_limit_usd)
        raise BudgetExceededError(
            f"Месячный лимит API ({settings.api_monthly_limit_usd} USD) исчерпан. "
            f"Потрачено: ${monthly_total:.4f}"
        )
