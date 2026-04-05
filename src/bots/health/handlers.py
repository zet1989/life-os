"""Хэндлеры бота Health — питание, тренировки, настройки."""

import json

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.ai.router import chat
from src.ai.vision import analyze_photo
from src.ai.whisper import transcribe_voice
from src.core.context import build_messages, save_assistant_reply
from src.utils.telegram import safe_answer
from src.db.queries import create_event, update_user_settings
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

    await processing.delete()
    await safe_answer(message, result, reply_markup=main_keyboard())

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
    messages = await build_messages(user_id, BOT_SOURCE, NUTRITIONIST_SYSTEM, text)
    result = await chat(messages=messages, task_type="meal_photo", user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)
    await create_event(
        user_id=user_id,
        event_type="meal",
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
    )

    await safe_answer(message, result, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _process_workout(message: Message, user_id: int, text: str) -> None:
    """Обработка описания тренировки."""
    messages = await build_messages(user_id, BOT_SOURCE, TRAINER_SYSTEM, text)
    result = await chat(messages=messages, task_type="workout_parse", user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)
    await create_event(
        user_id=user_id,
        event_type="workout",
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
    )

    await safe_answer(message, result, reply_markup=main_keyboard())
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
