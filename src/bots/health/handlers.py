"""Хэндлеры бота Health — питание, тренировки, настройки."""

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.ai.router import chat
from src.ai.vision import analyze_photo
from src.ai.whisper import transcribe_voice
from src.core.context import build_messages, save_assistant_reply
from src.utils.telegram import safe_answer, safe_answer_voice, safe_edit
from src.db.queries import create_event, get_active_goals, get_today_meals, get_today_water, get_today_workouts, get_user, get_weight_history, update_user_settings
from src.bots.health.prompts import (
    DOCTOR_PHOTO_PROMPT,
    DOCTOR_SYSTEM,
    MEAL_PHOTO_PROMPT,
    NUTRITIONIST_SYSTEM,
    PROFILE_HELP,
    TRAINER_SYSTEM,
    WIFE_NUTRITIONIST_SYSTEM,
)
from src.bots.health.keyboard import main_keyboard, Mode, get_user_mode, set_user_mode
from src.integrations.obsidian.writer import obsidian

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "health"
MSK = ZoneInfo("Europe/Moscow")


def _now_str() -> str:
    """Текущее время в MSK для промптов."""
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M")


async def _get_user_settings(user_id: int) -> str:
    """Загрузить персональные настройки пользователя из БД."""
    user = await get_user(user_id)
    overrides = (user or {}).get("system_prompt_overrides") or ""
    if overrides:
        return f"⚙️ ПЕРСОНАЛЬНЫЙ ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n{overrides}"
    return "⚙️ ПРОФИЛЬ: не задан (использую стандартные нормы)."


async def _is_wife(user_id: int) -> bool:
    """Проверить, является ли пользователь женой."""
    user = await get_user(user_id)
    return (user or {}).get("role") == "wife"


async def _watch_context(user_id: int) -> str:
    """Собрать контекст данных с часов для AI-промптов."""
    from src.db.queries import get_today_watch_metrics

    metrics = await get_today_watch_metrics(user_id)
    if not metrics:
        return ""

    last = metrics[0].get("json_data") or {}
    parts = []
    if "steps" in last:
        parts.append(f"Шаги: {last['steps']}")
    if "calories_burned" in last:
        parts.append(f"Сожжено: {last['calories_burned']} ккал")
    hr = last.get("heart_rate")
    if hr:
        parts.append(f"Пульс: {hr.get('avg', '?')} (мин {hr.get('min', '?')}, макс {hr.get('max', '?')})")
    sp = last.get("spo2")
    if sp:
        parts.append(f"SpO2: {sp.get('avg', '?')}%")
    st = last.get("stress")
    if st:
        parts.append(f"Стресс: {st.get('avg', '?')}/100")
    sl = last.get("sleep")
    if sl:
        parts.append(f"Сон: {sl.get('total_hours', '?')}ч, глубокий {sl.get('deep_min', 0)} мин")

    if not parts:
        return ""
    return "⌚ ДАННЫЕ ЧАСОВ СЕГОДНЯ:\n" + "\n".join(f"  {p}" for p in parts)


async def _today_meals_context(user_id: int) -> str:
    """Собрать контекст сегодняшних приёмов пищи из БД."""
    meals = await get_today_meals(user_id, bot_source="health")
    if not meals:
        return "📋 СЪЕДЕНО СЕГОДНЯ: ничего не записано."

    lines = []
    total_cal, total_prot, total_fat, total_carbs = 0, 0, 0, 0
    for i, m in enumerate(meals, 1):
        jd = m.get("json_data") or {}
        desc = jd.get("description") or (m.get("raw_text") or "")[:60]
        cal = jd.get("calories", 0) or 0
        prot = jd.get("protein", 0) or 0
        fat = jd.get("fat", 0) or 0
        carbs = jd.get("carbs", 0) or 0
        lines.append(f"{i}. {desc} — {cal} ккал (Б:{prot} Ж:{fat} У:{carbs})")
        total_cal += cal
        total_prot += prot
        total_fat += fat
        total_carbs += carbs

    header = f"📋 СЪЕДЕНО СЕГОДНЯ ({len(meals)} приёмов):"
    footer = f"ИТОГО за сегодня: {total_cal} ккал, Б:{total_prot} Ж:{total_fat} У:{total_carbs}"
    return header + "\n" + "\n".join(lines) + "\n" + footer


async def _today_workouts_context(user_id: int) -> str:
    """Собрать контекст сегодняшних тренировок из БД."""
    workouts = await get_today_workouts(user_id, bot_source="health")
    if not workouts:
        return "🏋️ ТРЕНИРОВКИ СЕГОДНЯ: нет записей."

    lines = []
    for i, w in enumerate(workouts, 1):
        jd = w.get("json_data") or {}
        raw = (w.get("raw_text") or "")[:80]
        wtype = jd.get("type", "")
        dur = jd.get("duration_min", "")
        desc = raw
        if wtype and dur:
            desc = f"{wtype}, {dur} мин"
        elif dur:
            desc = f"{dur} мин"
        lines.append(f"{i}. {desc}")

    return f"🏋️ ТРЕНИРОВКИ СЕГОДНЯ ({len(workouts)} шт.):\n" + "\n".join(lines)


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    await message.answer(
        f"Привет, {name}! 👋\n"
        f"Я твой AI-нутрициолог, тренер и доктор.\n\n"
        f"🍽 Еда — фото или текст → КБЖУ + советы\n"
        f"🏋️ Тренировка — лог и анализ\n"
        f"🩺 Доктор — медицинские вопросы\n"
        f"📋 Мой профиль — расскажи о себе",
        reply_markup=main_keyboard(),
    )


# === /voice — голосовые ответы AI ===

@router.message(Command("voice"))
async def cmd_voice_toggle(message: Message, db_user: dict) -> None:
    from src.ai.tts import toggle_voice_mode

    user_id = message.from_user.id  # type: ignore[union-attr]
    enabled = toggle_voice_mode(user_id)
    emoji = "🔊" if enabled else "🔇"
    state = "включены" if enabled else "выключены"
    await message.answer(
        f"{emoji} Голосовые ответы <b>{state}</b>.\n/voice — переключить.",
        reply_markup=main_keyboard(),
    )


# === Reply-клавиатура: переключение режимов ===

@router.message(F.text == "🍽 Еда")
async def mode_food(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.FOOD)  # type: ignore[union-attr]
    await message.answer(
        "🍽 Режим <b>Еда</b>.\n"
        "Отправь фото блюда — посчитаю КБЖУ.\n"
        "Или опиши текстом что съел.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🏋️ Тренировка")
async def mode_workout(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.WORKOUT)  # type: ignore[union-attr]
    await message.answer(
        "🏋️ Режим <b>Тренировка</b>.\n"
        "Напиши или надиктуй что делал.\n"
        'Например: "Жим лёжа 4×10 по 80 кг, затем 30 мин на дорожке"',
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📋 Мой профиль")
async def mode_profile(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROFILE)
    await _show_profile(message, user_id)


@router.message(F.text == "🩺 Доктор")
async def mode_doctor(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.DOCTOR)  # type: ignore[union-attr]
    await message.answer(
        "🩺 Режим <b>Доктор</b>.\n"
        "Я твой личный врач-терапевт.\n\n"
        "Опиши симптомы, задай вопрос о здоровье,\n"
        "пришли результаты анализов (фото или текст).\n\n"
        "💊 Учитываю твой профиль, болезни и питание.",
        reply_markup=main_keyboard(),
    )


# === 💧 Вода ===

WATER_GOAL_ML = 2500  # Дневная цель (мл)

WATER_QUICK_BUTTONS = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🥤 200 мл", callback_data="water:200"),
        InlineKeyboardButton(text="🥤 250 мл", callback_data="water:250"),
        InlineKeyboardButton(text="🥤 300 мл", callback_data="water:300"),
    ],
    [
        InlineKeyboardButton(text="🫗 500 мл", callback_data="water:500"),
        InlineKeyboardButton(text="🍶 750 мл", callback_data="water:750"),
        InlineKeyboardButton(text="💧 Другое", callback_data="water:custom"),
    ],
])


@router.message(F.text == "💧 Вода")
async def mode_water(message: Message) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.WATER)
    water_text = await _water_status(user_id)
    await message.answer(
        f"💧 <b>Водный баланс</b>\n\n{water_text}\n\n"
        "Выбери количество или напиши в мл:",
        reply_markup=main_keyboard(),
    )
    await message.answer("Быстрое добавление:", reply_markup=WATER_QUICK_BUTTONS)


@router.callback_query(F.data.startswith("water:"))
async def cb_water(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    value = callback.data.split(":")[1]  # type: ignore[union-attr]

    if value == "custom":
        set_user_mode(user_id, Mode.WATER)
        await callback.answer()
        await callback.message.answer(  # type: ignore[union-attr]
            "Напиши количество воды в мл (например: 350):",
            reply_markup=main_keyboard(),
        )
        return

    ml = int(value)
    await _add_water(user_id, ml)
    water_text = await _water_status(user_id)
    await callback.answer(f"💧 +{ml} мл")
    await safe_edit(callback.message, f"💧 <b>Водный баланс</b>\n\n{water_text}", reply_markup=WATER_QUICK_BUTTONS)


async def _add_water(user_id: int, ml: int) -> None:
    """Добавить запись о выпитой воде."""
    await create_event(
        user_id=user_id,
        event_type="water",
        bot_source="health",
        raw_text=f"{ml} мл воды",
        json_data={"ml": ml},
    )


async def _water_status(user_id: int) -> str:
    """Текущий статус водного баланса за день."""
    records = await get_today_water(user_id)
    total_ml = sum((r.get("json_data") or {}).get("ml", 0) for r in records)
    pct = min(100, round(total_ml / WATER_GOAL_ML * 100))
    filled = round(pct / 100 * 10)
    bar = "💧" * filled + "⬜" * (10 - filled)

    text = f"{bar} {total_ml} / {WATER_GOAL_ML} мл ({pct}%)"
    if pct >= 100:
        text += "\n🎉 Дневная норма выполнена!"
    elif pct >= 70:
        text += "\n👍 Почти у цели!"

    if records:
        last = records[-1]
        ts = last.get("timestamp")
        if hasattr(ts, "strftime"):
            text += f"\n⏰ Последний приём: {ts.strftime('%H:%M')}"

    return text


# === ⚖️ Вес и замеры ===

@router.message(F.text == "⚖️ Вес")
async def mode_weight(message: Message) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.WEIGHT)
    history = await get_weight_history(user_id, limit=10)

    text = "⚖️ <b>Вес и замеры тела</b>\n\n"

    if history:
        text += "<b>Последние записи:</b>\n"
        for h in history:
            jd = h.get("json_data") or {}
            ts = h.get("timestamp")
            date_str = ts.strftime("%d.%m.%Y") if hasattr(ts, "strftime") else ""
            weight = jd.get("weight_kg")
            if weight:
                text += f"  📅 {date_str} — <b>{weight} кг</b>"
                if jd.get("fat_pct"):
                    text += f" | жир: {jd['fat_pct']}%"
                if jd.get("waist_cm"):
                    text += f" | талия: {jd['waist_cm']} см"
                text += "\n"

        # Тренд
        if len(history) >= 2:
            first_jd = history[0].get("json_data") or {}
            last_jd = history[-1].get("json_data") or {}
            w_now = first_jd.get("weight_kg")
            w_prev = last_jd.get("weight_kg")
            if w_now and w_prev:
                diff = w_now - w_prev
                emoji = "📈" if diff > 0 else "📉" if diff < 0 else "➡️"
                text += f"\n{emoji} Тренд: <b>{diff:+.1f} кг</b> за {len(history)} записей\n"
    else:
        text += "Записей пока нет.\n"

    text += (
        "\n<b>Формат записи:</b>\n"
        "<code>85.5</code> — только вес\n"
        "<code>85.5 жир 18.5 талия 90</code> — с замерами"
    )
    await message.answer(text, reply_markup=main_keyboard())


async def _process_weight_text(message: Message, user_id: int, text: str) -> None:
    """Обработка записи веса/замеров."""
    import re

    # Парсим вес
    weight_match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not weight_match:
        await message.answer(
            "Введи вес числом, например: <code>85.5</code>",
            reply_markup=main_keyboard(),
        )
        return

    weight = float(weight_match.group(1).replace(",", "."))
    if weight < 20 or weight > 300:
        await message.answer("Введи реальный вес (20-300 кг).", reply_markup=main_keyboard())
        return

    json_data: dict = {"weight_kg": weight}

    # Опциональные замеры
    fat_match = re.search(r"жир\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if fat_match:
        json_data["fat_pct"] = float(fat_match.group(1).replace(",", "."))

    waist_match = re.search(r"тали[яю]\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if waist_match:
        json_data["waist_cm"] = float(waist_match.group(1).replace(",", "."))

    await create_event(
        user_id=user_id,
        event_type="weight",
        bot_source="health",
        raw_text=text,
        json_data=json_data,
    )

    response = f"⚖️ Записано: <b>{weight} кг</b>"
    if json_data.get("fat_pct"):
        response += f" | жир: {json_data['fat_pct']}%"
    if json_data.get("waist_cm"):
        response += f" | талия: {json_data['waist_cm']} см"

    # Сравнение с предыдущей записью
    history = await get_weight_history(user_id, limit=2)
    if len(history) >= 2:
        prev_jd = history[1].get("json_data") or {}
        prev_w = prev_jd.get("weight_kg")
        if prev_w:
            diff = weight - prev_w
            emoji = "📈" if diff > 0 else "📉" if diff < 0 else "➡️"
            response += f"\n{emoji} Изменение: <b>{diff:+.1f} кг</b>"

    await message.answer(response, reply_markup=main_keyboard())
    set_user_mode(user_id, Mode.FOOD)


# === /settings (backward compat) ===

@router.message(Command("settings"))
async def cmd_settings(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROFILE)
    await _show_profile(message, user_id)


# === 💊 Лекарства ===

@router.message(Command("med_add"))
async def cmd_med_add(message: Message, db_user: dict) -> None:
    """Добавить лекарство: /med_add Витамин D 09:00,21:00"""
    from src.db.queries import create_goal

    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/med_add", "").strip()

    if not args:
        await message.answer(
            "💊 <b>Добавить лекарство</b>\n\n"
            "Формат: /med_add <i>Название Время1,Время2</i>\n\n"
            "Примеры:\n"
            "<code>/med_add Витамин D 09:00</code>\n"
            "<code>/med_add Омега-3 09:00,21:00</code>\n"
            "<code>/med_add Магний 22:00</code>",
            reply_markup=main_keyboard(),
        )
        return

    # Парсим: последний аргумент — время через запятую
    parts = args.rsplit(" ", 1)
    if len(parts) == 2 and re.match(r"^[\d:,]+$", parts[1]):
        med_name = parts[0].strip()
        times_str = parts[1].strip()
    else:
        med_name = args.strip()
        times_str = "09:00"

    # Валидация времени
    times = [t.strip() for t in times_str.split(",") if t.strip()]
    valid_times = []
    for t in times:
        if re.match(r"^\d{1,2}:\d{2}$", t):
            valid_times.append(t)

    if not valid_times:
        valid_times = ["09:00"]

    await create_goal(
        user_id=user_id,
        goal_type="medication",
        title=med_name,
        description=",".join(valid_times),
    )

    await message.answer(
        f"✅ Лекарство добавлено: <b>{med_name}</b>\n"
        f"⏰ Напоминания: {', '.join(valid_times)}\n\n"
        f"📋 Список: /med_list\n"
        f"🗑 Удалить: /med_del",
        reply_markup=main_keyboard(),
    )


@router.message(Command("med_list"))
async def cmd_med_list(message: Message, db_user: dict) -> None:
    """Список лекарств с расписанием."""
    user_id = message.from_user.id  # type: ignore[union-attr]
    goals = await get_active_goals(user_id)
    medications = [g for g in goals if g.get("type") == "medication"]

    if not medications:
        await message.answer(
            "💊 Нет активных лекарств.\n"
            "Добавь: /med_add <i>Название Время</i>",
            reply_markup=main_keyboard(),
        )
        return

    text = "💊 <b>Мои лекарства:</b>\n\n"
    for m in medications:
        times = m.get("description", "09:00")
        text += f"• <b>{m['title']}</b> — ⏰ {times} (ID: {m['id']})\n"
    text += "\n🗑 Удалить: /med_del <code>ID</code>"

    await message.answer(text, reply_markup=main_keyboard())


@router.message(Command("med_del"))
async def cmd_med_del(message: Message, db_user: dict) -> None:
    """Удалить лекарство: /med_del ID"""
    from src.db.queries import update_goal

    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/med_del", "").strip()

    if not args or not args.isdigit():
        await message.answer(
            "Использование: /med_del <ID лекарства>\n"
            "Узнать ID: /med_list",
            reply_markup=main_keyboard(),
        )
        return

    goal_id = int(args)
    await update_goal(goal_id, user_id, status="achieved")
    await message.answer(f"✅ Лекарство #{goal_id} удалено.", reply_markup=main_keyboard())


# === Callback: приём/пропуск лекарства ===

@router.callback_query(F.data.startswith("med:taken:") | F.data.startswith("med:skip:"))
async def cb_medication(callback: CallbackQuery) -> None:
    """Обработка кнопок ✅ Принял / ⏭ Пропустил."""
    parts = callback.data.split(":")  # type: ignore[union-attr]
    action = parts[1]  # taken or skip
    goal_id = int(parts[2])
    user_id = callback.from_user.id

    from src.db.queries import get_goal

    goal = await get_goal(goal_id)
    med_name = goal.get("title", "лекарство") if goal else "лекарство"

    event_type = "medication_taken" if action == "taken" else "medication_skipped"
    await create_event(
        user_id=user_id,
        event_type=event_type,
        bot_source=BOT_SOURCE,
        raw_text=f"{med_name}: {'принято' if action == 'taken' else 'пропущено'}",
        json_data={"goal_id": goal_id, "medication": med_name},
    )

    if action == "taken":
        await callback.answer("✅ Отмечено!")
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]
                f"✅ <b>{med_name}</b> — принято!",
            )
    else:
        await callback.answer("⏭ Пропущено")
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]
                f"⏭ <b>{med_name}</b> — пропущено.",
            )


# === /med_history — история приёмов лекарств ===

@router.message(Command("med_history"))
async def cmd_med_history(message: Message, db_user: dict) -> None:
    """Показать историю приёмов лекарств за последние 7 дней."""
    from src.db.queries import get_recent_events

    user_id = message.from_user.id  # type: ignore[union-attr]
    taken = await get_recent_events(user_id, "medication_taken", BOT_SOURCE, limit=50)
    skipped = await get_recent_events(user_id, "medication_skipped", BOT_SOURCE, limit=50)

    all_events = sorted(taken + skipped, key=lambda e: e["timestamp"], reverse=True)

    if not all_events:
        await message.answer(
            "📋 Нет записей о приёмах лекарств.\n"
            "Они появятся, когда ты нажмёшь ✅/⏭ в напоминании.",
            reply_markup=main_keyboard(),
        )
        return

    text = "📋 <b>История приёмов лекарств:</b>\n\n"
    # Сгруппируем по дате
    from collections import defaultdict

    by_date: dict[str, list[dict]] = defaultdict(list)
    for ev in all_events[:30]:
        ts = ev["timestamp"]
        day = ts.strftime("%d.%m.%Y") if hasattr(ts, "strftime") else str(ts)[:10]
        by_date[day].append(ev)

    for day, events in by_date.items():
        text += f"<b>{day}:</b>\n"
        for ev in events:
            ts = ev["timestamp"]
            time_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else ""
            jd = ev.get("json_data") or {}
            med = jd.get("medication", "?")
            emoji = "✅" if ev["event_type"] == "medication_taken" else "⏭"
            text += f"  {emoji} {time_str} — {med}\n"
        text += "\n"

    # Статистика
    total = len(all_events)
    taken_count = len(taken)
    pct = round(taken_count / total * 100) if total > 0 else 0
    text += f"📊 Итого: {taken_count}/{total} принято ({pct}%)"

    await message.answer(text, reply_markup=main_keyboard())


# === Фото → КБЖУ ===

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]

    # Доктор — фото анализов, симптомов, лекарств
    if get_user_mode(user_id) == Mode.DOCTOR:
        await _process_doctor_photo(message, bot, user_id)
        return

    processing = await message.answer("⏳ Анализирую фото...")

    photo = message.photo[-1]  # самое большое разрешение
    caption = message.caption or ""
    result = await analyze_photo(
        bot=bot,
        photo=photo,
        prompt=MEAL_PHOTO_PROMPT,
        task_type="meal_photo",
        user_id=user_id,
        bot_source=BOT_SOURCE,
        caption=caption,
    )

    # Пытаемся извлечь JSON из ответа
    json_data = _extract_json(result)

    # Сохраняем событие ТОЛЬКО если есть КБЖУ
    if json_data and "calories" in json_data:
        raw = caption or "[фото еды]"
        await create_event(
            user_id=user_id,
            event_type="meal",
            bot_source=BOT_SOURCE,
            raw_text=raw,
            json_data=json_data,
            media_url=None,
        )
        await obsidian.log_meal(json_data, raw)

    display_text = _format_meal_response(result, json_data)

    await processing.delete()
    await safe_answer(message, display_text, reply_markup=main_keyboard())


# === Голосовое сообщение ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Транскрибирую аудио...")

    text = await transcribe_voice(
        bot=bot,
        voice=message.voice,
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    await processing.edit_text(f"🎤 <i>{text}</i>\n\n⏳ Обрабатываю...")

    # Определяем по режиму юзера
    mode = get_user_mode(user_id)
    if mode == Mode.WORKOUT:
        await _process_workout(message, user_id, text)
    elif mode == Mode.DOCTOR:
        await _process_doctor(message, user_id, text)
    elif mode == Mode.PROFILE:
        await _process_profile(message, user_id, text)
    elif mode == Mode.WATER:
        await _process_water_text(message, user_id, text)
    elif mode == Mode.WEIGHT:
        await _process_weight_text(message, user_id, text)
    else:
        await _process_food_text(message, user_id, text)


# === Текстовое сообщение ===

@router.message(F.text)
async def handle_text(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    text = message.text or ""

    mode = get_user_mode(user_id)
    if mode == Mode.WORKOUT:
        await _process_workout(message, user_id, text)
    elif mode == Mode.DOCTOR:
        await _process_doctor(message, user_id, text)
    elif mode == Mode.PROFILE:
        await _process_profile(message, user_id, text)
    elif mode == Mode.WATER:
        await _process_water_text(message, user_id, text)
    elif mode == Mode.WEIGHT:
        await _process_weight_text(message, user_id, text)
    else:
        await _process_food_text(message, user_id, text)


# === Внутренние обработчики ===

async def _process_water_text(message: Message, user_id: int, text: str) -> None:
    """Обработка текстового ввода воды (в мл)."""
    # Извлекаем число из текста
    import re
    match = re.search(r"(\d+)", text)
    if not match:
        await message.answer(
            "Напиши количество воды в мл (числом), например: 300",
            reply_markup=main_keyboard(),
        )
        return

    ml = int(match.group(1))
    if ml <= 0 or ml > 5000:
        await message.answer("Введи разумное количество (1-5000 мл).", reply_markup=main_keyboard())
        return

    await _add_water(user_id, ml)
    water_text = await _water_status(user_id)
    await message.answer(
        f"💧 +{ml} мл\n\n{water_text}",
        reply_markup=main_keyboard(),
    )

async def _process_food_text(message: Message, user_id: int, text: str) -> None:
    """Обработка текстового описания еды — STATELESS."""
    meals_ctx = await _today_meals_context(user_id)
    settings = await _get_user_settings(user_id)
    prompt_template = WIFE_NUTRITIONIST_SYSTEM if await _is_wife(user_id) else NUTRITIONIST_SYSTEM
    system = prompt_template.format(
        current_time=_now_str(),
        today_meals_context=meals_ctx,
        user_settings=settings,
    )
    # STATELESS: только system prompt + текущее сообщение, НОЛЬ истории
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    result = await chat(messages=messages, task_type="meal_photo", user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)

    # Создаём event ТОЛЬКО если есть КБЖУ данные
    if json_data and "calories" in json_data:
        await create_event(
            user_id=user_id,
            event_type="meal",
            bot_source=BOT_SOURCE,
            raw_text=text,
            json_data=json_data,
        )
        await obsidian.log_meal(json_data, text)

    display_text = _format_meal_response(result, json_data, user_id)
    await safe_answer(message, display_text, reply_markup=main_keyboard())


async def _process_workout(message: Message, user_id: int, text: str) -> None:
    """Обработка описания тренировки — STATELESS."""
    workouts_ctx = await _today_workouts_context(user_id)
    system = TRAINER_SYSTEM.format(
        current_time=_now_str(), today_workouts_context=workouts_ctx,
    )
    # STATELESS: только system prompt + текущее сообщение
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    result = await chat(messages=messages, task_type="workout_parse", user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)

    if json_data and "exercises" in json_data:
        await create_event(
            user_id=user_id,
            event_type="workout",
            bot_source=BOT_SOURCE,
            raw_text=text,
            json_data=json_data,
        )
        await obsidian.log_workout(json_data, text)

    display_text = _format_workout_response(result, json_data)
    await safe_answer(message, display_text, reply_markup=main_keyboard())


PROFILE_MERGE_SYSTEM = (
    "Ты — редактор профиля пользователя. Профиль — это ТОЛЬКО факты о человеке, "
    "которые нужны AI-ассистенту для персонализации ответов.\n\n"
    "Правила:\n"
    "1. Извлекай ТОЛЬКО фактическую информацию о пользователе: возраст, имя, рост, вес, "
    "привычки, зависимости, болезни, лекарства, режим дня, цели, контекст работы и т.д.\n"
    "2. УДАЛЯЙ всё, что НЕ является фактом о пользователе: вопросы к боту, просьбы, "
    "приветствия, обращения, комментарии, рассуждения.\n"
    "3. Если есть СУЩЕСТВУЮЩИЙ профиль — объедини с новыми данными. "
    "При противоречиях используй НОВЫЕ данные (они актуальнее).\n"
    "4. Сохрани всю остальную информацию из старого профиля без потерь.\n"
    "5. Верни ТОЛЬКО итоговый текст профиля, без комментариев и пояснений.\n"
    "6. Пиши на русском. Формат — краткий структурированный текст от третьего лица."
)


async def _merge_profile(existing: str, new_text: str, user_id: int) -> str:
    """Слить новые данные с существующим профилем через AI."""
    if existing:
        user_content = f"СУЩЕСТВУЮЩИЙ ПРОФИЛЬ:\n{existing}\n\nНОВЫЕ СВЕДЕНИЯ:\n{new_text}"
    else:
        user_content = f"НОВЫЕ СВЕДЕНИЯ:\n{new_text}"

    result = await chat(
        messages=[
            {"role": "system", "content": PROFILE_MERGE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        task_type="general_chat",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )
    return result.strip()


async def _process_profile(message: Message, user_id: int, text: str) -> None:
    """Сохранение профиля пользователя через AI-мерж с существующими данными."""
    user = await get_user(user_id)
    existing = (user or {}).get("system_prompt_overrides") or ""

    merged = await _merge_profile(existing, text, user_id)

    await update_user_settings(user_id, merged)
    set_user_mode(user_id, Mode.FOOD)

    await message.answer(
        "✅ Профиль обновлён!\n\n"
        f"<i>{merged[:500]}</i>\n\n"
        "Буду учитывать во всех рекомендациях.",
        reply_markup=main_keyboard(),
    )


async def _show_profile(message: Message, user_id: int) -> None:
    """Показать текущий профиль пользователя."""
    user = await get_user(user_id)
    overrides = (user or {}).get("system_prompt_overrides") or ""
    if overrides:
        text = (
            "📋 <b>Мой профиль</b>\n\n"
            f"{overrides}\n\n"
            "━━━━━━━━━━━━━━━\n"
            "Чтобы обновить — просто напиши новый текст."
        )
    else:
        text = PROFILE_HELP
    await message.answer(text, reply_markup=main_keyboard())


async def _process_doctor(message: Message, user_id: int, text: str) -> None:
    """Обработка запроса к доктору — с историей, на gpt-4o."""
    from src.db.queries import get_work_summary_text
    meals_ctx = await _today_meals_context(user_id)
    workouts_ctx = await _today_workouts_context(user_id)
    profile = await _get_user_settings(user_id)
    work_ctx = await get_work_summary_text(user_id, days=7)
    watch_ctx = await _watch_context(user_id)
    system = DOCTOR_SYSTEM.format(
        current_time=_now_str(),
        today_meals_context=meals_ctx,
        today_workouts_context=workouts_ctx,
        user_profile=profile,
    )
    if work_ctx:
        system += f"\n\n{work_ctx}"
    if watch_ctx:
        system += f"\n\n{watch_ctx}"
    messages = await build_messages(
        user_id=user_id,
        bot_source=BOT_SOURCE,
        system_prompt=system,
        user_text=text,
    )
    result = await chat(
        messages=messages,
        task_type="doctor_consult",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )
    await safe_answer_voice(message, result, user_id, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _process_doctor_photo(message: Message, bot: Bot, user_id: int) -> None:
    """Анализ фото для доктора (анализы, симптомы, лекарства)."""
    processing = await message.answer("⏳ Анализирую...")
    photo = message.photo[-1]
    profile = await _get_user_settings(user_id)
    prompt = DOCTOR_PHOTO_PROMPT.format(user_profile=profile)

    result = await analyze_photo(
        bot=bot,
        photo=photo,
        prompt=prompt,
        task_type="doctor_consult",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    await processing.delete()
    await safe_answer_voice(message, result, user_id, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)

    # Автоэкспорт в Obsidian + event для RAG
    try:
        from src.ai.rag import store_event_embedding

        # Определяем тип анализа из первой строки ответа
        first_line = result.split("\n")[0].strip("# *🩺📋").strip()
        analysis_type = first_line[:80] if first_line else "Анализ"

        relative_path = await obsidian.log_medical_analysis(result, analysis_type)

        event = await create_event(
            user_id=user_id,
            event_type="health_record",
            bot_source=BOT_SOURCE,
            raw_text=result[:4000],
            json_data={"type": "medical_analysis", "source_file": relative_path or ""},
        )
        await store_event_embedding(event["id"], f"[Анализ: {analysis_type}]\n{result}", user_id=user_id, bot_source=BOT_SOURCE)
    except Exception:
        logger.exception("doctor_photo.export_error")


def _format_meal_response(raw_result: str, json_data: dict | None, user_id: int = 0) -> str:
    """Строим богатую карточку КБЖУ + оценка + советы из json_data."""
    if not json_data or "calories" not in json_data:
        # LLM не дал КБЖУ — показываем текст как есть (вопрос/ответ)
        cleaned = re.sub(r'```json\s*\{.*?\}\s*```', '', raw_result, flags=re.DOTALL).strip()
        return cleaned or raw_result

    desc = json_data.get("description", "Блюдо")
    cal = json_data["calories"]
    prot = json_data.get("protein", "?")
    fat = json_data.get("fat", "?")
    carbs = json_data.get("carbs", "?")
    fiber = json_data.get("fiber")
    health_score = json_data.get("health_score")
    verdict = json_data.get("verdict", "")
    comment = json_data.get("comment", "")
    tip = json_data.get("tip", "")
    today_status = json_data.get("today_status", "")

    # === Основная карточка ===
    card = f"🍽 <b>{desc}</b>\n"

    # Вердикт (цветной)
    if verdict:
        card += f"{verdict}\n"

    # КБЖУ
    card += (
        f"\n🔥 Калории: <b>{cal}</b> ккал\n"
        f"🥩 Белки: <b>{prot}</b> г\n"
        f"🧈 Жиры: <b>{fat}</b> г\n"
        f"🍞 Углеводы: <b>{carbs}</b> г"
    )
    if fiber:
        card += f"\n🥬 Клетчатка: <b>{fiber}</b> г"

    # Health score
    if health_score is not None:
        score_bar = "●" * health_score + "○" * (10 - health_score)
        card += f"\n\n💚 Полезность: {score_bar} {health_score}/10"

    # Комментарий нутрициолога
    if comment:
        card += f"\n\n💬 {comment}"

    # Совет
    if tip:
        card += f"\n\n💡 <b>Совет:</b> {tip}"

    # Статус дня
    if today_status:
        card += f"\n\n📊 <i>{today_status}</i>"

    return card


def _format_workout_response(raw_result: str, json_data: dict | None) -> str:
    """Формируем красивый ответ из JSON тренировки."""
    if not json_data or "exercises" not in json_data:
        cleaned = re.sub(r'```json\s*.*?\s*```', '', raw_result, flags=re.DOTALL).strip()
        return cleaned or raw_result

    workout_type = {"strength": "💪 Силовая", "cardio": "🏃 Кардио", "flexibility": "🧘 Растяжка", "mixed": "🔄 Смешанная"}.get(
        json_data.get("type", ""), "🏋️ Тренировка"
    )
    duration = json_data.get("duration_min")
    cal_burned = json_data.get("calories_burned")

    pretty = f"{workout_type}"
    if duration:
        pretty += f" — {duration} мин"
    if cal_burned:
        pretty += f" — ~{cal_burned} ккал"
    pretty += "\n\n"

    for ex in json_data["exercises"]:
        name = ex.get("name", "Упражнение")
        parts = []
        if ex.get("sets"):
            parts.append(f"{ex['sets']}×{ex.get('reps', '?')}")
        if ex.get("weight_kg"):
            parts.append(f"{ex['weight_kg']} кг")
        if ex.get("duration_min"):
            parts.append(f"{ex['duration_min']} мин")
        detail = ", ".join(parts)
        pretty += f"▪️ <b>{name}</b>"
        if detail:
            pretty += f" — {detail}"
        pretty += "\n"

    comment = json_data.get("comment", "")
    if comment:
        pretty += f"\n💬 {comment}"

    tip = json_data.get("tip", "")
    if tip:
        pretty += f"\n💡 <b>Совет:</b> {tip}"

    return pretty


def _extract_json(text: str) -> dict | None:
    """Попытаться извлечь JSON из ответа LLM."""
    try:
        # Ищем JSON между ```json и ```
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        # Ищем первый { ... }
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


# === ⌚ Часы (Amazfit Balance 2 — push API) ===

@router.message(F.text == "⌚ Часы")
async def mode_watch(message: Message, db_user: dict) -> None:
    """Показать текущие данные с часов или предложить подключить."""
    from src.db.queries import get_watch_token, get_today_watch_metrics

    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.WATCH)

    token = await get_watch_token(user_id)
    if not token:
        await message.answer(
            "⌚ <b>Смарт-часы не подключены</b>\n\n"
            "Подключи Amazfit Balance 2 для автоматического трекинга:\n"
            "• 🫀 Пульс и SpO2\n"
            "• 🚶 Шаги и калории\n"
            "• 😴 Анализ сна\n"
            "• 😰 Уровень стресса\n"
            "• 🌡 Температура кожи\n\n"
            "Для подключения: /watch_connect",
            reply_markup=main_keyboard(),
        )
        return

    # Показать последние данные
    metrics = await get_today_watch_metrics(user_id)
    if not metrics:
        last_push = token.get("last_push_at")
        last_str = last_push.strftime("%d.%m %H:%M") if last_push and hasattr(last_push, "strftime") else "никогда"
        await message.answer(
            f"⌚ Часы подключены (<b>{token.get('device_name', 'Amazfit Balance 2')}</b>)\n"
            f"Последний push: {last_str}\n"
            f"Интервал: каждые {token.get('push_interval_min', 15)} мин\n\n"
            "Сегодня данных пока нет. Часы отправят данные автоматически.\n\n"
            "/watch_disconnect — отвязать часы",
            reply_markup=main_keyboard(),
        )
        return

    # Собрать сводку из последних метрик
    last = metrics[0].get("json_data") or {}
    text = "⌚ <b>Данные с часов сегодня</b>\n\n"

    if "steps" in last:
        text += f"🚶 Шаги: <b>{last['steps']}</b>\n"
    if "distance_km" in last:
        text += f"📏 Дистанция: <b>{last['distance_km']} км</b>\n"
    if "calories_burned" in last:
        text += f"🔥 Сожжено: <b>{last['calories_burned']} ккал</b>\n"

    hr = last.get("heart_rate")
    if hr:
        text += f"🫀 Пульс: <b>{hr.get('avg', '?')}</b> (мин {hr.get('min', '?')}, макс {hr.get('max', '?')})\n"

    sp = last.get("spo2")
    if sp:
        text += f"🩸 SpO2: <b>{sp.get('avg', '?')}%</b>\n"

    st = last.get("stress")
    if st:
        level = st.get("avg", 0)
        emoji = "😌" if level < 30 else "😐" if level < 60 else "😰"
        text += f"{emoji} Стресс: <b>{level}/100</b>\n"

    if "skin_temperature" in last:
        text += f"🌡 Температура: <b>{last['skin_temperature']}°C</b>\n"

    sl = last.get("sleep")
    if sl:
        text += (
            f"\n😴 <b>Сон:</b> {sl.get('total_hours', '?')}ч\n"
            f"  Глубокий: {sl.get('deep_min', 0)} мин\n"
            f"  REM: {sl.get('rem_min', 0)} мин\n"
            f"  Качество: {sl.get('quality_pct', '?')}%\n"
        )

    text += (
        f"\n⏰ Обновлено: {metrics[0]['timestamp'].strftime('%H:%M') if hasattr(metrics[0]['timestamp'], 'strftime') else '?'}\n"
        f"\n/watch_disconnect — отвязать часы"
    )
    await message.answer(text, reply_markup=main_keyboard())


@router.message(Command("watch_connect"))
async def cmd_watch_connect(message: Message, db_user: dict) -> None:
    """Сгенерировать API-ключ для push-интеграции с Amazfit Balance 2."""
    from src.integrations.amazfit import generate_watch_api_key
    from src.db.queries import get_watch_token, save_watch_token
    from src.config import settings

    user_id = message.from_user.id  # type: ignore[union-attr]

    # Если уже подключены — показать ключ
    existing = await get_watch_token(user_id)
    if existing:
        await message.answer(
            "⌚ <b>Часы уже подключены</b>\n\n"
            f"Устройство: {existing.get('device_name', 'Amazfit Balance 2')}\n"
            f"API-ключ: <code>{existing['api_key']}</code>\n\n"
            "Чтобы переподключить, сначала отвяжи: /watch_disconnect",
            reply_markup=main_keyboard(),
        )
        return

    api_key = generate_watch_api_key()
    webhook_host = settings.webhook_host or "https://your-server.com"
    push_url = f"{webhook_host}/api/watch/push"

    await save_watch_token(user_id=user_id, api_key=api_key)

    await message.answer(
        "⌚ <b>Подключение Amazfit Balance 2</b>\n\n"
        "1. Установи мини-приложение Life OS на часы (Zepp OS)\n"
        "2. Введи в настройках приложения:\n\n"
        f"   <b>URL:</b> <code>{push_url}</code>\n"
        f"   <b>API-ключ:</b> <code>{api_key}</code>\n\n"
        "3. Часы будут автоматически отправлять данные каждые 15 мин\n\n"
        "💡 Формат push-запроса: POST с JSON-телом и заголовком\n"
        "<code>Authorization: Bearer {api_key}</code>",
        reply_markup=main_keyboard(),
    )


@router.message(Command("watch_disconnect"))
async def cmd_watch_disconnect(message: Message, db_user: dict) -> None:
    """Отвязать часы."""
    from src.db.queries import delete_watch_token

    user_id = message.from_user.id  # type: ignore[union-attr]
    await delete_watch_token(user_id)
    await message.answer("⌚ Часы отвязаны.", reply_markup=main_keyboard())
