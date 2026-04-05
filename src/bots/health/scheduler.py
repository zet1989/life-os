"""Планировщик дневной сводки КБЖУ для бота Health."""

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ai.router import chat
from src.db.queries import get_active_user_ids, get_recent_events

logger = structlog.get_logger()

SUMMARY_PROMPT = (
    "Проанализируй питание пользователя за сегодня. "
    "Подведи итого по КБЖУ (калории, белки, жиры, углеводы). "
    "Если данных мало — отметь это. "
    "Дай краткую рекомендацию. Формат: текст, без JSON."
)


async def send_daily_summary(bot: Bot) -> None:
    """Отправить вечернюю сводку КБЖУ всем активным health-юзерам."""
    try:
        user_ids = await get_active_user_ids()
        for uid in user_ids:
            await _send_summary_to_user(bot, uid)
    except Exception:
        logger.exception("daily_summary_failed")


async def _send_summary_to_user(bot: Bot, user_id: int) -> None:
    """Сводка для одного юзера."""
    try:
        meals = await get_recent_events(
            user_id=user_id,
            event_type="meal",
            bot_source="health",
            limit=20,
        )

        if not meals:
            return  # Нет данных — не беспокоим

        # Собираем сводку из всех приёмов пищи
        meals_text = "\n".join(
            f"- {m.get('raw_text', '')}" for m in meals
        )

        messages = [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": f"Приёмы пищи за сегодня:\n{meals_text}"},
        ]

        result = await chat(
            messages=messages,
            task_type="daily_summary",
            user_id=user_id,
            bot_source="health",
        )

        await bot.send_message(user_id, f"📊 <b>Дневная сводка КБЖУ</b>\n\n{result}")

    except Exception:
        logger.exception("summary_user_failed", user_id=user_id)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Создать и запустить планировщик с дневной сводкой в 21:00 MSK."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        send_daily_summary,
        trigger=CronTrigger(hour=21, minute=0),
        args=[bot],
        id="daily_kbzhu_summary",
        replace_existing=True,
    )
    return scheduler
