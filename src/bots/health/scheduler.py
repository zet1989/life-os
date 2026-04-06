"""Планировщик дневной сводки КБЖУ для бота Health."""

from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ai.router import chat
from src.db.queries import get_active_user_ids, get_today_meals

logger = structlog.get_logger()

MSK = ZoneInfo("Europe/Moscow")

SUMMARY_PROMPT = (
    "Ты — нутрициолог. Проанализируй питание пользователя за сегодня.\n\n"
    "Тебе даны ВСЕ приёмы пищи с точными КБЖУ (калории, белки, жиры, углеводы).\n"
    "Твоя задача:\n"
    "1. Перечислить КАЖДОЕ блюдо (ни одно не пропускай!).\n"
    "2. Показать КБЖУ по каждому блюду.\n"
    "3. Посчитать ИТОГО КБЖУ за день (суммируй из предоставленных данных).\n"
    "4. Сравнить с нормой пользователя или ≈2000-2500 ккал для мужчины.\n"
    "5. Дать краткую рекомендацию.\n\n"
    "ВАЖНО: Используй ТОЛЬКО данные из списка ниже. "
    "Не пропускай блюда. Не путай описания. Не придумывай блюда.\n"
    "Формат: текст, без JSON."
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
    """Сводка для одного юзера — на основе json_data за сегодня."""
    try:
        meals = await get_today_meals(user_id=user_id, bot_source="health")

        if not meals:
            return

        meals_lines = []
        total_cal, total_prot, total_fat, total_carbs = 0, 0, 0, 0

        for i, m in enumerate(meals, 1):
            jd = m.get("json_data") or {}
            desc = jd.get("description") or m.get("raw_text", "Неизвестное блюдо")[:80]
            cal = jd.get("calories", 0) or 0
            prot = jd.get("protein", 0) or 0
            fat = jd.get("fat", 0) or 0
            carbs = jd.get("carbs", 0) or 0

            meals_lines.append(
                f"{i}. {desc}\n"
                f"   - Калории: {cal}\n"
                f"   - Белки: {prot} г\n"
                f"   - Жиры: {fat} г\n"
                f"   - Углеводы: {carbs} г"
            )
            total_cal += cal
            total_prot += prot
            total_fat += fat
            total_carbs += carbs

        meals_text = "\n\n".join(meals_lines)
        totals = (
            f"\n\nСУММАРНО за день: Калории={total_cal}, "
            f"Белки={total_prot} г, Жиры={total_fat} г, Углеводы={total_carbs} г"
        )

        now = datetime.now(MSK)
        date_str = now.strftime("%d.%m.%Y")

        messages = [
            {"role": "system", "content": SUMMARY_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Дата: {date_str}\n"
                    f"Приёмы пищи за сегодня ({len(meals)} шт.):\n\n"
                    f"{meals_text}{totals}"
                ),
            },
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
        trigger=CronTrigger(hour=21, minute=0, timezone=MSK),
        args=[bot],
        id="daily_kbzhu_summary",
        replace_existing=True,
    )
    return scheduler
