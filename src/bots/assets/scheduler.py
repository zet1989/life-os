"""Планировщик напоминаний по пробегу для бота Assets."""

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ai.router import chat
from src.db.supabase_client import get_client

logger = structlog.get_logger()

# Стандартные интервалы ТО для Hyundai Sonata (км)
SERVICE_INTERVALS = {
    "масло двигателя": 10_000,
    "масло АКПП": 60_000,
    "тормозная жидкость": 40_000,
    "антифриз": 60_000,
    "свечи зажигания": 30_000,
    "воздушный фильтр": 15_000,
    "салонный фильтр": 15_000,
    "тормозные колодки передние": 30_000,
    "тормозные колодки задние": 40_000,
    "ремень ГРМ": 60_000,
}

CHECK_PROMPT = (
    "Ты AI-механик. Проанализируй данные бортжурнала автомобиля.\n"
    "Определи, какие работы просрочены по километражу.\n"
    "Дай список рекомендаций: что пора менять, с учётом последнего пробега.\n"
    "Формат: краткий список со смайликами. Без JSON."
)


async def check_mileage_reminders(bot: Bot) -> None:
    """Проверить бортжурнал и отправить напоминания, если ТО просрочено."""
    try:
        supabase = get_client()

        # Получаем активных юзеров
        users_resp = (
            supabase.table("users")
            .select("telegram_id")
            .eq("is_active", True)
            .execute()
        )

        for user in users_resp.data or []:
            uid = user["telegram_id"]
            await _check_for_user(bot, supabase, uid)

    except Exception:
        logger.exception("mileage_check_failed")


async def _check_for_user(bot: Bot, supabase, user_id: int) -> None:
    """Проверка для одного юзера."""
    try:
        # Последние записи бортжурнала
        resp = (
            supabase.table("events")
            .select("raw_text, json_data, created_at")
            .eq("user_id", user_id)
            .eq("event_type", "auto_maintenance")
            .eq("bot_source", "assets")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        records = resp.data or []
        if not records:
            return

        # Собираем текст бортжурнала
        journal = "\n".join(
            f"[{r.get('created_at', '')}] {r.get('raw_text', '')}" for r in records
        )

        intervals_text = "\n".join(
            f"- {item}: каждые {km} км" for item, km in SERVICE_INTERVALS.items()
        )

        messages = [
            {"role": "system", "content": CHECK_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Интервалы ТО:\n{intervals_text}\n\n"
                    f"Бортжурнал (последние записи):\n{journal}\n\n"
                    f"Определи, что просрочено или скоро потребуется."
                ),
            },
        ]

        result = await chat(
            messages=messages,
            task_type="mileage_reminder",
            user_id=user_id,
            bot_source="assets",
        )

        # Отправляем только если есть просроченные работы
        if any(word in result.lower() for word in ["пора", "просроч", "рекоменд", "нужно", "замен"]):
            await bot.send_message(
                user_id,
                f"🔧 <b>Напоминание по ТО</b>\n\n{result}",
            )

    except Exception:
        logger.exception("mileage_user_check_failed", user_id=user_id)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Планировщик: проверка пробега каждое воскресенье в 10:00 MSK."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        check_mileage_reminders,
        trigger=CronTrigger(day_of_week="sun", hour=10, minute=0),
        args=[bot],
        id="mileage_reminder",
        replace_existing=True,
    )
    return scheduler
