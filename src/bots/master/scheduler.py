"""Планировщик для бота Master Intelligence.

Задачи:
- Ежемесячный аудит (1-го числа в 10:00 MSK)
- Утренний брифинг (08:00 MSK)
- Вечерний обзор (21:00 MSK)
- Напоминания о задачах (каждую минуту)
"""

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.ai.rag import search
from src.ai.router import chat
from src.db.queries import (
    get_active_goals,
    get_admin_users,
    get_completed_today_count,
    get_finance_summary,
    get_obsidian_pending_reminders,
    get_overdue_tasks,
    get_pending_task_reminders,
    get_today_tasks,
    get_unclosed_tasks,
    get_user_projects,
    mark_obsidian_reminder_sent,
    mark_reminder_sent,
)
from src.bots.master.prompts import AUDIT_PROMPT, EVENING_REVIEW_HEADER, MASTER_SYSTEM, VISION_CONTEXT

logger = structlog.get_logger()


async def send_monthly_audit(bot: Bot) -> None:
    """Отправить ежемесячный аудит всем admin-пользователям."""
    try:
        admins = await get_admin_users()

        for admin in admins:
            uid = admin["user_id"]
            await _send_audit_to_user(bot, uid)

    except Exception:
        logger.exception("monthly_audit_failed")


async def _send_audit_to_user(bot: Bot, user_id: int) -> None:
    """Аудит для одного пользователя."""
    try:
        # Финансы по всем проектам (SQL only)
        projects = await get_user_projects(user_id)
        finance_lines = []
        for proj in projects:
            summary = await get_finance_summary(proj["project_id"])
            if not summary:
                continue
            income = sum(float(r["total"]) for r in summary if r["transaction_type"] == "income")
            expense = sum(float(r["total"]) for r in summary if r["transaction_type"] == "expense")
            finance_lines.append(
                f"{proj['name']} [{proj['type']}]: доход {income:,.0f} ₽, расход {expense:,.0f} ₽"
            )
        finances_text = "\n".join(finance_lines) if finance_lines else "Нет данных."

        # Цели
        goals = await get_active_goals(user_id)
        goals_text = ""
        for g in goals:
            goals_text += f"- [{g['type']}] {g['title']} — {g.get('progress_pct', 0)}%\n"
        if not goals_text:
            goals_text = "Целей нет."

        # Дневник (RAG последние записи)
        diary_entries = await search(
            query="настроение состояние привычки дневник",
            user_id=user_id,
            top_k=15,
            bot_source="master",
        )
        diary_text = "\n".join(
            f"[{d.get('timestamp', '')}] {d.get('raw_text', '')[:120]}"
            for d in diary_entries
        ) or "Записей нет."

        # System prompt с целями
        system = MASTER_SYSTEM
        if goals:
            gl = ""
            for g in goals:
                gl += f"- [{g['type']}] {g['title']} — {g.get('progress_pct', 0)}%\n"
            system += VISION_CONTEXT.format(goals=gl)

        # LLM аудит
        prompt = AUDIT_PROMPT.format(
            finances=finances_text,
            goals=goals_text,
            diary=diary_text,
        )
        result = await chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            task_type="master_audit",
            user_id=user_id,
            bot_source="master",
        )

        await bot.send_message(
            user_id,
            f"📋 <b>Ежемесячный аудит Life OS</b>\n\n{result}",
        )

    except Exception:
        logger.exception("audit_user_failed", user_id=user_id)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Планировщик Master-бота."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # Ежемесячный аудит — 1-го числа в 10:00
    scheduler.add_job(
        send_monthly_audit,
        trigger=CronTrigger(day=1, hour=10, minute=0),
        args=[bot],
        id="monthly_life_audit",
        replace_existing=True,
    )

    # Утренний брифинг — 08:00 каждый день
    scheduler.add_job(
        send_morning_briefing,
        trigger=CronTrigger(hour=8, minute=0),
        args=[bot],
        id="morning_briefing",
        replace_existing=True,
    )

    # Вечерний обзор — 21:00 каждый день
    scheduler.add_job(
        send_evening_review,
        trigger=CronTrigger(hour=21, minute=0),
        args=[bot],
        id="evening_review",
        replace_existing=True,
    )

    # Напоминания о задачах — каждую минуту
    scheduler.add_job(
        send_task_reminders,
        trigger=IntervalTrigger(minutes=1),
        args=[bot],
        id="task_reminders",
        replace_existing=True,
    )

    # Obsidian задачи — каждую минуту
    scheduler.add_job(
        send_obsidian_reminders,
        trigger=IntervalTrigger(minutes=1),
        args=[bot],
        id="obsidian_reminders",
        replace_existing=True,
    )

    return scheduler


# === Утренний брифинг ===

async def send_morning_briefing(bot: Bot) -> None:
    """Утренний брифинг для admin-пользователей."""
    try:
        admins = await get_admin_users()
        for admin in admins:
            await _send_briefing_to_user(bot, admin["user_id"])
    except Exception:
        logger.exception("morning_briefing_failed")


async def _send_briefing_to_user(bot: Bot, user_id: int) -> None:
    """Утренний брифинг для одного пользователя."""
    try:
        tasks = await get_today_tasks(user_id)
        overdue = await get_overdue_tasks(user_id)
        goals = await get_active_goals(user_id)

        total = len(tasks)
        urgent = sum(1 for t in tasks if t.get("priority") == "urgent")

        text = "☀️ <b>Доброе утро!</b>\n\n"

        # Задачи на сегодня
        if tasks:
            text += f"📋 Задачи на сегодня: <b>{total}</b>"
            if urgent:
                text += f" (🔴 срочных: {urgent})"
            text += "\n\n"

            for t in tasks:
                if not t["is_done"]:
                    prio = {"low": "⬜", "normal": "🔵", "high": "🟠", "urgent": "🔴"}.get(
                        t.get("priority", "normal"), ""
                    )
                    time_str = t["due_time"].strftime("%H:%M") if t.get("due_time") else ""
                    time_part = f"<b>{time_str}</b> — " if time_str else ""
                    text += f"  {prio} {time_part}{t['task_text']}\n"
        else:
            text += "📋 На сегодня задач нет.\n"

        # Просроченные
        if overdue:
            text += f"\n🔴 Просрочено: <b>{len(overdue)}</b>\n"
            for t in overdue[:3]:
                d = t["due_date"].strftime("%d.%m") if t.get("due_date") else ""
                text += f"  ⚠️ [{d}] {t['task_text']}\n"

        # Главная цель
        if goals:
            top_goal = goals[0]
            text += f"\n🎯 Фокус: <b>{top_goal['title']}</b> — {top_goal.get('progress_pct', 0)}%"

        await bot.send_message(user_id, text)

    except Exception:
        logger.exception("briefing_user_failed", user_id=user_id)


# === Вечерний обзор ===

async def send_evening_review(bot: Bot) -> None:
    """Вечерний обзор для admin-пользователей."""
    try:
        admins = await get_admin_users()
        for admin in admins:
            await _send_evening_to_user(bot, admin["user_id"])
    except Exception:
        logger.exception("evening_review_failed")


async def _send_evening_to_user(bot: Bot, user_id: int) -> None:
    """Вечерний обзор для одного пользователя."""
    try:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tasks = await get_today_tasks(user_id)
        done_count = sum(1 for t in tasks if t["is_done"])
        total = len(tasks)
        unclosed = [t for t in tasks if not t["is_done"]]

        text = EVENING_REVIEW_HEADER

        if total == 0:
            text += "Сегодня задач не было.\n"
        else:
            text += f"✅ Выполнено: <b>{done_count}/{total}</b>\n\n"

            if unclosed:
                text += "❌ <b>Не выполнено:</b>\n"
                for t in unclosed:
                    text += f"  • {t['task_text']}\n"

        if unclosed:
            tomorrow = (datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(days=1)).strftime("%Y-%m-%d")
            buttons = []
            for t in unclosed[:5]:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"📅 {t['task_text'][:25]}→завтра",
                        callback_data=f"task_reschedule:{t['id']}:{tomorrow}",
                    ),
                    InlineKeyboardButton(
                        text="🗑",
                        callback_data=f"task_delete:{t['id']}",
                    ),
                ])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await bot.send_message(user_id, text, reply_markup=keyboard)
        else:
            if total > 0:
                text += "\n🎉 Все задачи выполнены! Отличный день."
            await bot.send_message(user_id, text)

    except Exception:
        logger.exception("evening_user_failed", user_id=user_id)


# === Напоминания о задачах ===

async def send_task_reminders(bot: Bot) -> None:
    """Отправить напоминания о задачах, у которых наступило время."""
    try:
        pending = await get_pending_task_reminders()
        for task in pending:
            try:
                time_str = task["due_time"].strftime("%H:%M") if task.get("due_time") else ""
                text = (
                    f"⏰ <b>Напоминание</b>\n\n"
                    f"{task['task_text']}\n"
                    f"🕐 {time_str}"
                )
                await bot.send_message(task["user_id"], text)
                await mark_reminder_sent(task["id"])
            except Exception:
                logger.exception("reminder_send_failed", task_id=task["id"])
    except Exception:
        logger.exception("task_reminders_failed")


# === Obsidian-задачи — напоминания ===

async def send_obsidian_reminders(bot: Bot) -> None:
    """Отправить напоминания о задачах из Obsidian."""
    try:
        pending = await get_obsidian_pending_reminders()
        for task in pending:
            try:
                time_str = task["due_time"].strftime("%H:%M") if task.get("due_time") else ""
                text = (
                    f"⏰ <b>Obsidian-задача</b>\n\n"
                    f"{task['task_text']}\n"
                    f"🕐 {time_str}\n"
                    f"📂 {task['source_file']}"
                )
                await bot.send_message(task["user_id"], text)
                await mark_obsidian_reminder_sent(task["id"])
            except Exception:
                logger.exception("obsidian_reminder_failed", task_id=task["id"])
    except Exception:
        logger.exception("obsidian_reminders_failed")
