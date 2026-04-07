"""Планировщик для бота Master Intelligence.

Задачи:
- Ежемесячный аудит (1-го числа в 10:00 MSK)
- Утренний брифинг (08:00 MSK)
- Вечерний обзор (21:00 MSK)
- Напоминания о задачах (каждую минуту)
- Автобэкап PostgreSQL (ежедневно в 03:00 MSK)
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
    get_recurring_tasks_due,
    get_today_tasks,
    get_unclosed_tasks,
    get_user_projects,
    get_week_events_by_type,
    get_week_summary,
    mark_obsidian_reminder_sent,
    mark_reminder_sent,
    spawn_recurring_task,
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

    # Автобэкап PostgreSQL — 03:00 каждый день
    scheduler.add_job(
        run_pg_backup,
        trigger=CronTrigger(hour=3, minute=0),
        id="pg_backup",
        replace_existing=True,
    )

    # Повторяющиеся задачи — 06:00 каждый день (до утреннего брифинга)
    scheduler.add_job(
        spawn_recurring_tasks,
        trigger=CronTrigger(hour=6, minute=0),
        id="recurring_tasks",
        replace_existing=True,
    )

    # Еженедельный обзор — воскресенье 20:00
    scheduler.add_job(
        send_weekly_review,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0),
        args=[bot],
        id="weekly_review",
        replace_existing=True,
    )

    # Weekly Notes Obsidian — воскресенье 20:30 (после weekly review)
    scheduler.add_job(
        generate_weekly_obsidian_note,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=30),
        id="weekly_obsidian_note",
        replace_existing=True,
    )

    # Мониторинг здоровья сервиса — каждые 5 минут
    scheduler.add_job(
        check_service_health,
        trigger=IntervalTrigger(minutes=5),
        args=[bot],
        id="service_health_check",
        replace_existing=True,
    )

    return scheduler


# === Автобэкап PostgreSQL ===

BACKUP_DIR = Path("/app/backups")
BACKUP_KEEP_DAYS = 7


async def run_pg_backup() -> None:
    """pg_dump → /app/backups/lifeos_YYYY-MM-DD.sql.gz, хранить 7 дней."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        filename = f"lifeos_{now.strftime('%Y-%m-%d_%H%M')}.sql.gz"
        filepath = BACKUP_DIR / filename

        db_host = os.getenv("POSTGRES_HOST", "postgres")
        db_user = os.getenv("POSTGRES_USER", "lifeos")
        db_name = os.getenv("POSTGRES_DB", "lifeos")
        db_pass = os.getenv("POSTGRES_PASSWORD", "lifeos")

        cmd = (
            f"PGPASSWORD={db_pass} pg_dump -h {db_host} -U {db_user} {db_name} "
            f"| gzip > {filepath}"
        )
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error("pg_backup_failed", stderr=stderr.decode()[:500])
            return

        size_mb = filepath.stat().st_size / (1024 * 1024)
        logger.info("pg_backup_ok", file=filename, size_mb=round(size_mb, 2))

        # Удаляем старые бэкапы
        cutoff = now.timestamp() - BACKUP_KEEP_DAYS * 86400
        for old in BACKUP_DIR.glob("lifeos_*.sql.gz"):
            if old.stat().st_mtime < cutoff:
                old.unlink()
                logger.info("pg_backup_cleanup", deleted=old.name)

    except Exception:
        logger.exception("pg_backup_error")


# === Повторяющиеся задачи ===

async def spawn_recurring_tasks() -> None:
    """Создать экземпляры повторяющихся задач на сегодня."""
    try:
        today = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")
        templates = await get_recurring_tasks_due(today)
        for tpl in templates:
            await spawn_recurring_task(tpl, today)
            logger.info(
                "recurring_task_spawned",
                task_id=tpl["id"],
                text=tpl["task_text"][:50],
            )
        if templates:
            logger.info("recurring_tasks_done", count=len(templates))
    except Exception:
        logger.exception("recurring_tasks_error")


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


# === Еженедельный обзор ===

async def send_weekly_review(bot: Bot) -> None:
    """Еженедельный обзор для admin-пользователей (воскресенье 20:00)."""
    try:
        admins = await get_admin_users()
        for admin in admins:
            await _send_weekly_to_user(bot, admin["user_id"])
    except Exception:
        logger.exception("weekly_review_failed")


async def _send_weekly_to_user(bot: Bot, user_id: int) -> None:
    """Еженедельный GTD-обзор для одного пользователя."""
    try:
        summary = await get_week_summary(user_id)
        goals = await get_active_goals(user_id)
        overdue = await get_overdue_tasks(user_id)

        text = "📋 <b>ЕЖЕНЕДЕЛЬНЫЙ ОБЗОР</b>\n\n"

        text += f"✅ Выполнено: <b>{summary['completed']}</b>\n"
        text += f"➕ Создано: <b>{summary['created']}</b>\n"
        if overdue:
            text += f"🔴 Просрочено: <b>{len(overdue)}</b>\n"
        text += "\n"

        if goals:
            text += "🎯 <b>Цели:</b>\n"
            for g in goals:
                pct = g.get("progress_pct", 0)
                filled = round(pct / 100 * 8)
                bar = "▓" * filled + "░" * (8 - filled)
                emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}.get(g["type"], "📌")
                text += f"  {emoji} {g['title']} {bar} {pct}%\n"
            text += "\n"

        text += f"💰 <b>Финансы за неделю:</b>\n"
        text += f"  💵 Доход: <b>{summary['week_income']:,.0f} ₽</b>\n"
        text += f"  💸 Расход: <b>{summary['week_expense']:,.0f} ₽</b>\n"
        balance = summary["week_income"] - summary["week_expense"]
        b_emoji = "✅" if balance >= 0 else "🔴"
        text += f"  {b_emoji} Баланс: <b>{balance:,.0f} ₽</b>\n\n"

        if overdue:
            text += "⚠️ <b>Просроченные:</b>\n"
            for t in overdue[:5]:
                d = t["due_date"].strftime("%d.%m") if t.get("due_date") else ""
                text += f"  [{d}] {t['task_text']}\n"
            text += "\n"

        text += "💡 <i>Спланируй следующую неделю, обнови прогресс целей.</i>"

        await bot.send_message(user_id, text)

    except Exception:
        logger.exception("weekly_user_failed", user_id=user_id)


# === Weekly Notes Obsidian ===

async def generate_weekly_obsidian_note() -> None:
    """Сгенерировать Weekly Note в Obsidian для каждого admin."""
    try:
        from src.integrations.obsidian.writer import obsidian

        admins = await get_admin_users()
        for admin in admins:
            user_id = admin["user_id"]
            summary = await get_week_summary(user_id)
            events_by_type = await get_week_events_by_type(user_id)
            goals = await get_active_goals(user_id)
            await obsidian.generate_weekly_note(summary, events_by_type, goals)
            logger.info("weekly_obsidian_note_generated", user_id=user_id)
    except Exception:
        logger.exception("weekly_obsidian_note_failed")


# === Мониторинг здоровья сервиса ===

# Состояние: не слать алерт каждые 5 минут, а только при изменении
_last_health_ok: bool = True


async def check_service_health(bot: Bot) -> None:
    """Проверить здоровье сервиса и послать алерт при проблемах."""
    global _last_health_ok

    issues: list[str] = []

    # 1. Проверка PostgreSQL
    try:
        from src.db.postgres import get_pool
        result = await get_pool().fetchval("SELECT 1")
        if result != 1:
            issues.append("❌ PostgreSQL: запрос вернул некорректный результат")
    except Exception as e:
        issues.append(f"❌ PostgreSQL: {str(e)[:100]}")

    # 2. Проверка Redis
    try:
        from src.config import settings
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url)
        pong = await r.ping()
        await r.aclose()
        if not pong:
            issues.append("❌ Redis: не отвечает на PING")
    except Exception as e:
        issues.append(f"❌ Redis: {str(e)[:100]}")

    # 3. Проверка дискового пространства
    try:
        import shutil
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1.0:
            issues.append(f"⚠️ Диск: осталось {free_gb:.1f} GB свободно")
    except Exception:
        pass  # Не критично

    if issues:
        if _last_health_ok:  # Переход ok → fail: послать алерт
            _last_health_ok = False
            try:
                admins = await get_admin_users()
                text = "🚨 <b>АЛЕРТ: проблемы с сервисом</b>\n\n" + "\n".join(issues)
                for admin in admins:
                    await bot.send_message(admin["user_id"], text)
                logger.warning("service_health_alert_sent", issues=issues)
            except Exception:
                logger.exception("service_health_alert_send_failed")
    else:
        if not _last_health_ok:  # Переход fail → ok: послать восстановление
            _last_health_ok = True
            try:
                admins = await get_admin_users()
                for admin in admins:
                    await bot.send_message(admin["user_id"], "✅ <b>Сервис восстановлен</b>\n\nВсе компоненты работают нормально.")
                logger.info("service_health_recovered")
            except Exception:
                logger.exception("service_health_recovery_send_failed")
