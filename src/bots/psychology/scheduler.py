"""Планировщик для бота Psychology.

Задачи:
- Месячный психологический отчёт (последний день месяца, 20:00 MSK)
"""

import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ai.router import chat
from src.db.queries import (
    get_active_goals,
    get_admin_users,
    get_monthly_diary_entries,
    get_monthly_habit_stats,
    get_monthly_mood_data,
)

logger = structlog.get_logger()

MSK = ZoneInfo("Europe/Moscow")

MONTHLY_REPORT_PROMPT = (
    "Составь месячный психологический отчёт на основе данных.\n\n"
    "ДАННЫЕ НАСТРОЕНИЯ:\n{mood_data}\n\n"
    "ЗАПИСИ ДНЕВНИКА (выдержки):\n{diary_data}\n\n"
    "ПРИВЫЧКИ:\n{habit_data}\n\n"
    "ЦЕЛИ:\n{goals_data}\n\n"
    "Структура отчёта:\n"
    "1. 📊 ТРЕНД НАСТРОЕНИЯ: средний балл, динамика (рост/падение), лучшие и худшие дни.\n"
    "2. 🔄 ПАТТЕРНЫ: повторяющиеся темы из дневника, корреляции настроения с привычками.\n"
    "3. ✅ ПРИВЫЧКИ: какие держатся, какие проседают, рекомендация.\n"
    "4. 🎯 СВЕРКА С ЦЕЛЯМИ: насколько действия за месяц приближали к целям.\n"
    "5. 💡 РЕКОМЕНДАЦИЯ: одна конкретная фокус-точка на следующий месяц.\n\n"
    "Пиши аналитически, не банально. Тон — поддерживающий, но честный."
)


async def send_monthly_psychology_report(bot: Bot) -> None:
    """Месячный психологический отчёт для admin-пользователей."""
    try:
        admins = await get_admin_users()
        for admin in admins:
            await _send_monthly_report(bot, admin["user_id"])
    except Exception:
        logger.exception("monthly_psychology_report_failed")


async def _send_monthly_report(bot: Bot, user_id: int) -> None:
    """Отправить месячный психологический отчёт одному пользователю."""
    try:
        now = datetime.now(MSK)
        year, month = now.year, now.month

        # Настроения
        moods = await get_monthly_mood_data(user_id, year, month)
        if moods:
            scores = [m["score"] for m in moods if m.get("score")]
            avg = sum(scores) / len(scores) if scores else 0
            mood_text = f"Записей: {len(moods)}, средний балл: {avg:.1f}/5\n"
            for m in moods:
                day = m["day"].strftime("%d.%m") if hasattr(m["day"], "strftime") else str(m["day"])
                mood_text += f"  {day}: {m['score']}/5\n"
        else:
            mood_text = "Настроение не отмечалось в этом месяце."

        # Дневник
        entries = await get_monthly_diary_entries(user_id, year, month)
        if entries:
            diary_text = f"Записей: {len(entries)}\n"
            for e in entries[:15]:
                ts = e["timestamp"].strftime("%d.%m") if hasattr(e["timestamp"], "strftime") else str(e["timestamp"])
                raw = (e.get("raw_text") or "")[:120]
                diary_text += f"  [{ts}] {raw}\n"
        else:
            diary_text = "Дневниковых записей нет."

        # Привычки
        habits = await get_monthly_habit_stats(user_id, year, month)
        if habits:
            habit_text = ""
            for h in habits:
                habit_text += f"  {h['title']}: {h['done_count']}/{h['total_count']} отмечено\n"
        else:
            habit_text = "Привычки не отмечались."

        # Цели
        goals = await get_active_goals(user_id)
        if goals:
            goals_text = ""
            for g in goals:
                goals_text += f"  [{g['type']}] {g['title']} — {g.get('progress_pct', 0)}%\n"
        else:
            goals_text = "Целей нет."

        prompt = MONTHLY_REPORT_PROMPT.format(
            mood_data=mood_text,
            diary_data=diary_text,
            habit_data=habit_text,
            goals_data=goals_text,
        )

        result = await chat(
            messages=[
                {"role": "system", "content": "Ты — опытный клинический психолог. Составь аналитический месячный отчёт."},
                {"role": "user", "content": prompt},
            ],
            task_type="psychology_report",
            user_id=user_id,
            bot_source="psychology",
        )

        month_names = [
            "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
        ]

        await bot.send_message(
            user_id,
            f"🧠 <b>Психологический отчёт: {month_names[month]} {year}</b>\n\n{result}",
        )
        logger.info("monthly_psychology_report_sent", user_id=user_id)

    except Exception:
        logger.exception("monthly_psychology_report_user_failed", user_id=user_id)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Планировщик Psychology-бота."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # Месячный психологический отчёт — последний день месяца в 20:00
    scheduler.add_job(
        send_monthly_psychology_report,
        trigger=CronTrigger(day="last", hour=20, minute=0, timezone=MSK),
        args=[bot],
        id="monthly_psychology_report",
        replace_existing=True,
    )

    return scheduler
