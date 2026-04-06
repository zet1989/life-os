"""Хэндлеры бота Health — питание, тренировки, настройки."""

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.ai.router import chat
from src.ai.vision import analyze_photo
from src.ai.whisper import transcribe_voice
from src.core.context import build_messages, save_assistant_reply
from src.utils.telegram import safe_answer
from src.db.queries import create_event, get_today_meals, get_today_workouts, update_user_settings
from src.bots.health.prompts import (
    MEAL_PHOTO_PROMPT,
    NUTRITIONIST_SYSTEM,
    SETTINGS_HELP,
    TRAINER_SYSTEM,
)
from src.bots.health.keyboard import main_keyboard, Mode, get_user_mode, set_user_mode

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "health"
MSK = ZoneInfo("Europe/Moscow")


def _now_str() -> str:
    """Текущее время в MSK для промптов."""
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M")


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
        f"Я твой AI-нутрициолог и тренер.\n\n"
        f"📸 Отправь фото еды — посчитаю КБЖУ\n"
        f"🏋️ Напиши или надиктуй тренировку\n"
        f"⚙️ Настройки — задай свои параметры",
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


@router.message(F.text == "⚙️ Настройки")
async def mode_settings(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.SETTINGS)  # type: ignore[union-attr]
    await message.answer(SETTINGS_HELP, reply_markup=main_keyboard())


# === /settings ===

@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.SETTINGS)  # type: ignore[union-attr]
    await message.answer(SETTINGS_HELP, reply_markup=main_keyboard())


# === Фото → КБЖУ ===

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Анализирую фото...")

    photo = message.photo[-1]  # самое большое разрешение
    result = await analyze_photo(
        bot=bot,
        photo=photo,
        prompt=MEAL_PHOTO_PROMPT,
        task_type="meal_photo",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    # Пытаемся извлечь JSON из ответа
    json_data = _extract_json(result)

    # Сохраняем событие
    await create_event(
        user_id=user_id,
        event_type="meal",
        bot_source=BOT_SOURCE,
        raw_text=result,
        json_data=json_data,
        media_url=None,  # URL уже в Storage
    )

    display_text = _format_meal_response(result, json_data)

    await processing.delete()
    await safe_answer(message, display_text, reply_markup=main_keyboard())

    # Сохраняем в историю диалога
    await save_assistant_reply(user_id, BOT_SOURCE, result)


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
    elif mode == Mode.SETTINGS:
        await _process_settings(message, user_id, text)
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
    elif mode == Mode.SETTINGS:
        await _process_settings(message, user_id, text)
    else:
        await _process_food_text(message, user_id, text)


# === Внутренние обработчики ===

async def _process_food_text(message: Message, user_id: int, text: str) -> None:
    """Обработка текстового описания еды."""
    meals_ctx = await _today_meals_context(user_id)
    system = NUTRITIONIST_SYSTEM.format(
        current_time=_now_str(), today_meals_context=meals_ctx,
    )
    messages = await build_messages(user_id, BOT_SOURCE, system, text)
    result = await chat(messages=messages, task_type="meal_photo", user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)
    await create_event(
        user_id=user_id,
        event_type="meal",
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
    )

    display_text = _format_meal_response(result, json_data)
    await safe_answer(message, display_text, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _process_workout(message: Message, user_id: int, text: str) -> None:
    """Обработка описания тренировки."""
    workouts_ctx = await _today_workouts_context(user_id)
    system = TRAINER_SYSTEM.format(
        current_time=_now_str(), today_workouts_context=workouts_ctx,
    )
    messages = await build_messages(user_id, BOT_SOURCE, system, text)
    result = await chat(messages=messages, task_type="workout_parse", user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)
    await create_event(
        user_id=user_id,
        event_type="workout",
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
    )

    display_text = _format_workout_response(result, json_data)
    await safe_answer(message, display_text, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _process_settings(message: Message, user_id: int, text: str) -> None:
    """Сохранение настроек юзера (калории, диета, витамины)."""
    await update_user_settings(user_id, text)
    set_user_mode(user_id, Mode.FOOD)  # возвращаем в режим еды

    await message.answer(
        "✅ Настройки обновлены! Буду учитывать.\n\n"
        f"<i>{text}</i>",
        reply_markup=main_keyboard(),
    )


def _format_meal_response(raw_result: str, json_data: dict | None) -> str:
    """Формируем красивый ответ из КБЖУ JSON + комментарий LLM."""
    if not json_data or "calories" not in json_data:
        return raw_result

    desc = json_data.get("description", "Блюдо")
    pretty = (
        f"🍽 <b>{desc}</b>\n\n"
        f"🔥 Калории: <b>{json_data['calories']}</b> ккал\n"
        f"🥩 Белки: <b>{json_data.get('protein', '?')}</b> г\n"
        f"🧈 Жиры: <b>{json_data.get('fat', '?')}</b> г\n"
        f"🍞 Углеводы: <b>{json_data.get('carbs', '?')}</b> г"
    )
    # Убираем JSON-блок, оставляем комментарий LLM
    comment = re.sub(r'```json\s*\{[^}]*\}\s*```', '', raw_result).strip()
    if comment:
        pretty += f"\n\n{comment}"
    return pretty


def _format_workout_response(raw_result: str, json_data: dict | None) -> str:
    """Формируем красивый ответ из JSON тренировки + комментарий LLM."""
    if not json_data or "exercises" not in json_data:
        # Убираем JSON-блок если он есть, но не распарсился как ожидалось
        cleaned = re.sub(r'```json\s*.*?\s*```', '', raw_result, flags=re.DOTALL).strip()
        return cleaned or raw_result

    workout_type = {"strength": "💪 Силовая", "cardio": "🏃 Кардио", "flexibility": "🧘 Растяжка", "mixed": "🔄 Смешанная"}.get(
        json_data.get("type", ""), "🏋️ Тренировка"
    )
    duration = json_data.get("duration_min")
    pretty = f"{workout_type}"
    if duration:
        pretty += f" — {duration} мин"
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

    # Комментарий LLM
    comment = re.sub(r'```json\s*.*?\s*```', '', raw_result, flags=re.DOTALL).strip()
    if comment:
        pretty += f"\n{comment}"
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
