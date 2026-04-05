"""Планировщик ежемесячного аудита для бота Master Intelligence.

Cron: 1-го числа каждого месяца в 10:00 MSK.
Аудит: финансы (SQL) + цели + дневник (RAG) → LLM анализ.
"""

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ai.rag import search
from src.ai.router import chat
from src.db.queries import get_active_goals, get_finance_summary, get_user_projects
from src.db.supabase_client import get_supabase
from src.bots.master.prompts import AUDIT_PROMPT, MASTER_SYSTEM, VISION_CONTEXT

logger = structlog.get_logger()


async def send_monthly_audit(bot: Bot) -> None:
    """Отправить ежемесячный аудит всем admin-пользователям."""
    try:
        resp = (
            get_supabase()
            .table("users")
            .select("user_id, display_name")
            .eq("is_active", True)
            .eq("role", "admin")
            .execute()
        )
        admins = resp.data or []

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
    """Планировщик: аудит 1-го числа в 10:00 MSK."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        send_monthly_audit,
        trigger=CronTrigger(day=1, hour=10, minute=0),
        args=[bot],
        id="monthly_life_audit",
        replace_existing=True,
    )
    return scheduler
