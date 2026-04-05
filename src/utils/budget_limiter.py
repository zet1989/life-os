"""Бюджетный лимитер API-расходов (daily/monthly cap).

Проверяет api_costs перед каждым LLM-вызовом.
Если лимит превышен — блокирует вызов.
"""

from datetime import datetime, timezone

import structlog

from src.config import settings
from src.db.supabase_client import get_supabase

logger = structlog.get_logger()


class BudgetExceededError(Exception):
    """Лимит API-расходов превышен."""
    pass


async def check_budget() -> None:
    """Проверить дневной и месячный лимиты. Бросает BudgetExceededError если превышен."""
    now = datetime.now(timezone.utc)

    # Дневной лимит
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    daily_resp = (
        get_supabase()
        .rpc("sum_api_costs", {"p_since": day_start})
        .execute()
    )
    daily_total = float(daily_resp.data or 0)

    if daily_total >= settings.api_daily_limit_usd:
        logger.warning("budget_daily_exceeded", daily=daily_total, limit=settings.api_daily_limit_usd)
        raise BudgetExceededError(
            f"Дневной лимит API ({settings.api_daily_limit_usd} USD) исчерпан. "
            f"Потрачено: ${daily_total:.4f}"
        )

    # Месячный лимит
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    monthly_resp = (
        get_supabase()
        .rpc("sum_api_costs", {"p_since": month_start})
        .execute()
    )
    monthly_total = float(monthly_resp.data or 0)

    if monthly_total >= settings.api_monthly_limit_usd:
        logger.warning("budget_monthly_exceeded", monthly=monthly_total, limit=settings.api_monthly_limit_usd)
        raise BudgetExceededError(
            f"Месячный лимит API ({settings.api_monthly_limit_usd} USD) исчерпан. "
            f"Потрачено: ${monthly_total:.4f}"
        )
