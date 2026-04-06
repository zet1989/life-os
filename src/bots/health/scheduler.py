"""Планировщик дневной/недельной/месячной сводки КБЖУ для бота Health."""

from datetime import datetime, timedelta
from calendar import monthrange
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ai.router import chat
from src.db.queries import get_active_user_ids, get_today_meals, get_meals_range
from src.utils.telegram import safe_send

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

WEEKLY_PROMPT = (
    "Ты — нутрициолог. Проанализируй питание пользователя за неделю.\n\n"
    "Тебе дана ПОЛНАЯ статистика за каждый день (общие калории, Б/Ж/У и кол-во приёмов пищи).\n"
    "Твоя задача:\n"
    "1. Показать средние КБЖУ за неделю.\n"
    "2. Найти дни-выбросы (переедание или недоедание).\n"
    "3. Оценить баланс БЖУ (норма: 25-35% Б, 25-35% Ж, 40-50% У).\n"
    "4. Дать 2-3 конкретные рекомендации по улучшению рациона.\n"
    "5. Поставить оценку недели по шкале 1-10.\n\n"
    "ВАЖНО: Используй ТОЛЬКО данные из списка ниже.\n"
    "Формат: текст, с эмодзи, без JSON. Кратко и по делу."
)

MONTHLY_PROMPT = (
    "Ты — нутрициолог. Проанализируй питание пользователя за месяц.\n\n"
    "Тебе дана ПОНЕДЕЛЬНАЯ статистика (средние КБЖУ за каждую неделю).\n"
    "Твоя задача:\n"
    "1. Показать динамику: улучшается ли питание от недели к неделе.\n"
    "2. Средние КБЖУ за весь месяц.\n"
    "3. Главные проблемы месяца (дефицит/избыток белка, калорий и т.д.).\n"
    "4. Дать 3-5 конкретных рекомендаций на следующий месяц.\n"
    "5. Поставить общую оценку месяца по шкале 1-10.\n\n"
    "ВАЖНО: Используй ТОЛЬКО данные из списка ниже.\n"
    "Формат: текст, с эмодзи, без JSON. Развёрнуто, но структурированно."
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

        await safe_send(bot, user_id, f"📊 <b>Дневная сводка КБЖУ</b>\n\n{result}")

    except Exception:
        logger.exception("summary_user_failed", user_id=user_id)


# === Недельная сводка ===

def _aggregate_meals_by_day(meals: list[dict]) -> dict[str, dict]:
    """Группирует приёмы пищи по дням и считает суммарные КБЖУ."""
    days: dict[str, dict] = {}
    for m in meals:
        ts = m.get("timestamp")
        if not ts:
            continue
        if hasattr(ts, "astimezone"):
            day_key = ts.astimezone(MSK).strftime("%d.%m.%Y")
        else:
            day_key = str(ts)[:10]
        if day_key not in days:
            days[day_key] = {"cal": 0, "prot": 0, "fat": 0, "carbs": 0, "count": 0}
        jd = m.get("json_data") or {}
        days[day_key]["cal"] += jd.get("calories", 0) or 0
        days[day_key]["prot"] += jd.get("protein", 0) or 0
        days[day_key]["fat"] += jd.get("fat", 0) or 0
        days[day_key]["carbs"] += jd.get("carbs", 0) or 0
        days[day_key]["count"] += 1
    return days


async def send_weekly_summary(bot: Bot) -> None:
    """Отправить недельную сводку КБЖУ всем активным health-юзерам."""
    try:
        user_ids = await get_active_user_ids()
        for uid in user_ids:
            await _send_weekly_to_user(bot, uid)
    except Exception:
        logger.exception("weekly_summary_failed")


async def _send_weekly_to_user(bot: Bot, user_id: int) -> None:
    """Недельная сводка для одного юзера."""
    try:
        now = datetime.now(MSK)
        date_to = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=6)).strftime("%Y-%m-%d")

        meals = await get_meals_range(user_id, date_from, date_to)
        if not meals:
            return

        days = _aggregate_meals_by_day(meals)
        lines = []
        for day, d in sorted(days.items()):
            lines.append(
                f"{day}: {d['cal']} ккал | Б:{d['prot']} Ж:{d['fat']} У:{d['carbs']} | {d['count']} приёмов"
            )
        days_text = "\n".join(lines)

        messages = [
            {"role": "system", "content": WEEKLY_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Период: {date_from} — {date_to}\n"
                    f"Статистика по дням ({len(days)} дн.):\n\n{days_text}"
                ),
            },
        ]

        result = await chat(
            messages=messages,
            task_type="daily_summary",
            user_id=user_id,
            bot_source="health",
        )

        await safe_send(bot, user_id, f"📊 <b>Недельная сводка питания</b>\n\n{result}")

    except Exception:
        logger.exception("weekly_user_failed", user_id=user_id)


# === Месячная сводка ===

async def send_monthly_summary(bot: Bot) -> None:
    """Отправить месячную сводку КБЖУ всем активным health-юзерам."""
    try:
        user_ids = await get_active_user_ids()
        for uid in user_ids:
            await _send_monthly_to_user(bot, uid)
    except Exception:
        logger.exception("monthly_summary_failed")


async def _send_monthly_to_user(bot: Bot, user_id: int) -> None:
    """Месячная сводка для одного юзера."""
    try:
        now = datetime.now(MSK)
        # Весь прошедший месяц
        first_day = now.replace(day=1)
        last_day_num = monthrange(now.year, now.month)[1]
        date_from = first_day.strftime("%Y-%m-%d")
        date_to = now.replace(day=last_day_num).strftime("%Y-%m-%d")

        meals = await get_meals_range(user_id, date_from, date_to)
        if not meals:
            return

        days = _aggregate_meals_by_day(meals)

        # Группировка по неделям (пн-вс)
        weeks: dict[int, dict] = {}
        for day_str, d in days.items():
            dt = datetime.strptime(day_str, "%d.%m.%Y")
            week_num = dt.isocalendar()[1]
            if week_num not in weeks:
                weeks[week_num] = {"cal": 0, "prot": 0, "fat": 0, "carbs": 0, "days": 0}
            weeks[week_num]["cal"] += d["cal"]
            weeks[week_num]["prot"] += d["prot"]
            weeks[week_num]["fat"] += d["fat"]
            weeks[week_num]["carbs"] += d["carbs"]
            weeks[week_num]["days"] += 1

        lines = []
        for w_num in sorted(weeks):
            w = weeks[w_num]
            n = max(w["days"], 1)
            lines.append(
                f"Неделя #{w_num} ({n} дн.): "
                f"~{w['cal'] // n} ккал/день | "
                f"Б:{w['prot'] // n} Ж:{w['fat'] // n} У:{w['carbs'] // n}"
            )
        weeks_text = "\n".join(lines)

        messages = [
            {"role": "system", "content": MONTHLY_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Месяц: {now.strftime('%B %Y')}\n"
                    f"Всего дней с записями: {len(days)}\n"
                    f"Всего приёмов пищи: {len(meals)}\n\n"
                    f"Статистика по неделям:\n{weeks_text}"
                ),
            },
        ]

        result = await chat(
            messages=messages,
            task_type="daily_summary",
            user_id=user_id,
            bot_source="health",
        )

        await safe_send(bot, user_id, f"📊 <b>Месячная сводка питания</b>\n\n{result}")

    except Exception:
        logger.exception("monthly_user_failed", user_id=user_id)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Создать и запустить планировщик с дневной/недельной/месячной сводкой."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # Ежедневно в 21:00 MSK
    scheduler.add_job(
        send_daily_summary,
        trigger=CronTrigger(hour=21, minute=0, timezone=MSK),
        args=[bot],
        id="daily_kbzhu_summary",
        replace_existing=True,
    )

    # Каждое воскресенье в 20:00 MSK
    scheduler.add_job(
        send_weekly_summary,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=MSK),
        args=[bot],
        id="weekly_kbzhu_summary",
        replace_existing=True,
    )

    # Последний день каждого месяца в 20:00 MSK (day="last")
    scheduler.add_job(
        send_monthly_summary,
        trigger=CronTrigger(day="last", hour=20, minute=0, timezone=MSK),
        args=[bot],
        id="monthly_kbzhu_summary",
        replace_existing=True,
    )

    return scheduler
