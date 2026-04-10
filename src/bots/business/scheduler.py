"""Планировщик напоминаний о рабочем таймере — только для admin."""

from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings
from src.db.queries import get_active_work_session

logger = structlog.get_logger()

MSK = ZoneInfo("Europe/Moscow")


def _start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▶️ Начать сейчас", callback_data="wt:start_now"),
            InlineKeyboardButton(text="🕐 Указать время", callback_data="wt:start_custom"),
        ],
    ])


def _stop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏹ Остановить сейчас", callback_data="wt:stop_now"),
            InlineKeyboardButton(text="🕐 Указать время", callback_data="wt:stop_custom"),
        ],
    ])


async def remind_start_work(bot: Bot) -> None:
    """10:00 МСК (пн-пт) — напомнить включить таймер, если не запущен."""
    user_id = settings.admin_user_id
    if not user_id:
        return
    try:
        active = await get_active_work_session(user_id)
        if not active:
            await bot.send_message(
                user_id,
                "⏰ <b>Доброе утро!</b>\n\n"
                "Не забудь включить рабочий таймер.",
                reply_markup=_start_kb(),
            )
    except Exception:
        logger.exception("remind_start_work_failed")


async def remind_stop_work(bot: Bot) -> None:
    """18:00 МСК (пн-пт) — напомнить выключить таймер, если запущен."""
    user_id = settings.admin_user_id
    if not user_id:
        return
    try:
        active = await get_active_work_session(user_id)
        if active:
            start_msk = active["start_time"].astimezone(MSK)
            start_str = start_msk.strftime("%H:%M")
            now = datetime.now(MSK)
            elapsed = int((now - active["start_time"]).total_seconds() // 60)
            h, m = divmod(max(elapsed, 0), 60)
            await bot.send_message(
                user_id,
                f"⏰ <b>Конец рабочего дня!</b>\n\n"
                f"Таймер запущен с {start_str} ({h}ч {m}мин)",
                reply_markup=_stop_kb(),
            )
    except Exception:
        logger.exception("remind_stop_work_failed")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        remind_start_work,
        trigger=CronTrigger(hour=10, minute=0, day_of_week="mon-fri", timezone=MSK),
        args=[bot],
        id="work_timer_start_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        remind_stop_work,
        trigger=CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone=MSK),
        args=[bot],
        id="work_timer_stop_reminder",
        replace_existing=True,
    )
    return scheduler
