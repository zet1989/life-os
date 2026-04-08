"""Хэндлеры бота Assets — AI-Прораб (дом) и AI-Механик (авто)."""

import json
import re

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.ai.rag import rag_answer, store_event_embedding
from src.ai.router import chat
from src.ai.vision import analyze_photo
from src.ai.whisper import transcribe_voice
from src.core.context import build_messages, save_assistant_reply
from src.utils.telegram import safe_answer
from src.db.queries import create_event, create_finance
from src.bots.assets.keyboard import (
    Mode,
    get_user_mode,
    inline_category,
    main_keyboard,
    set_user_mode,
)
from src.bots.assets.prompts import (
    BLUEPRINT_PROMPT,
    FOREMAN_SYSTEM,
    MECHANIC_SYSTEM,
    ORDER_OCR_PROMPT,
    PART_PHOTO_PROMPT,
    RECEIPT_OCR_PROMPT,
)

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "assets"

# ID проектов из seed-данных (projects table)
# Если ID неизвестен — будет None; хэндлер пропустит запись в finances
PROJECT_HOUSE: int | None = None
PROJECT_AUTO: int | None = None

# Маппинг режимов → промпт/event_type
_MODE_CONFIG: dict[Mode, dict] = {
    Mode.MEASUREMENT: {
        "system": FOREMAN_SYSTEM,
        "event_type": "measurement",
        "task_type": "rag_answer",
    },
    Mode.RECEIPT: {
        "system": FOREMAN_SYSTEM,
        "event_type": "measurement",
        "task_type": "receipt_ocr",
        "photo_prompt": RECEIPT_OCR_PROMPT,
    },
    Mode.MAINTENANCE: {
        "system": MECHANIC_SYSTEM,
        "event_type": "auto_maintenance",
        "task_type": "rag_answer",
    },
    Mode.PART: {
        "system": MECHANIC_SYSTEM,
        "event_type": "auto_maintenance",
        "task_type": "part_photo",
        "photo_prompt": PART_PHOTO_PROMPT,
    },
    Mode.QUESTION: {
        "system": MECHANIC_SYSTEM,
        "event_type": "auto_maintenance",
        "task_type": "rag_answer",
    },
    Mode.BLUEPRINT: {
        "system": FOREMAN_SYSTEM,
        "event_type": "measurement",
        "task_type": "blueprint",
        "photo_prompt": BLUEPRINT_PROMPT,
    },
}


async def _init_project_ids() -> None:
    """Загрузить ID проектов House Renovation и Hyundai Sonata из БД."""
    global PROJECT_HOUSE, PROJECT_AUTO
    if PROJECT_HOUSE is not None:
        return
    try:
        from src.db.postgres import get_pool
        rows = await get_pool().fetch("SELECT project_id, name FROM projects WHERE status = 'active'")
        for row in rows:
            name_lower = row["name"].lower()
            if "house" in name_lower or "renovation" in name_lower:
                PROJECT_HOUSE = row["project_id"]
            elif "hyundai" in name_lower or "sonata" in name_lower:
                PROJECT_AUTO = row["project_id"]
    except Exception:
        logger.warning("project_ids_not_loaded")


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    await _init_project_ids()
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    await message.answer(
        f"Привет, {name}! 🏠🚗\n"
        f"Я помогаю с домом и автомобилем.\n\n"
        f"📐 Замер — надиктуй или напиши замеры комнат\n"
        f"🧾 Чек — отправь фото чека из строймага\n"
        f"� План дома — отправь фото чертежа/плана\n"
        f"�🔧 ТО — запиши в бортжурнал авто\n"
        f"⚙️ Запчасть — фото упаковки или заказ-наряда\n"
        f"❓ Спросить — найду в базе знаний",
        reply_markup=main_keyboard(),
    )


# === Reply-клавиатура: переключение режимов ===

@router.message(F.text == "📐 Замер")
async def mode_measurement(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.MEASUREMENT)  # type: ignore[union-attr]
    await message.answer(
        "📐 Режим <b>Замер</b>.\nНадиктуй или напиши замеры помещения.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🧾 Чек")
async def mode_receipt(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.RECEIPT)  # type: ignore[union-attr]
    await message.answer(
        "🧾 Режим <b>Чек</b>.\nОтправь фото чека из строительного магазина.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🔧 ТО")
async def mode_maintenance(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.MAINTENANCE)  # type: ignore[union-attr]
    await message.answer(
        "🔧 Режим <b>Бортжурнал</b>.\n"
        "Напиши или надиктуй: что делал, пробег, какие запчасти.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "⚙️ Запчасть")
async def mode_part(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.PART)  # type: ignore[union-attr]
    await message.answer(
        "⚙️ Режим <b>Запчасть</b>.\n"
        "Отправь фото упаковки запчасти или заказ-наряда из сервиса.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "❓ Спросить")
async def mode_question(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.QUESTION)  # type: ignore[union-attr]
    await message.answer(
        "❓ Режим <b>Вопрос</b>.\n"
        'Задай вопрос: "Когда менял масло?", "Какие замеры кухни?"',
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🗓 План дома")
async def mode_blueprint(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.BLUEPRINT)  # type: ignore[union-attr]
    await message.answer(
        "🗓 Режим <b>План дома</b>.\n"
        "Отправь фото чертежа, плана или схемы помещения.\n"
        "Я проанализирую и сохраню в базу знаний.",
        reply_markup=main_keyboard(),
    )


# === Inline callback: переключение режима ===

@router.callback_query(F.data.startswith("asset_mode:"))
async def cb_mode(callback: CallbackQuery) -> None:
    mode_str = callback.data.split(":")[1]  # type: ignore[union-attr]
    try:
        mode = Mode(mode_str)
    except ValueError:
        await callback.answer("Неизвестный режим")
        return

    set_user_mode(callback.from_user.id, mode)
    await callback.answer(f"Режим: {mode.value}")


# === Фото ===

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, db_user: dict) -> None:
    await _init_project_ids()
    user_id = message.from_user.id  # type: ignore[union-attr]
    mode = get_user_mode(user_id)
    processing = await message.answer("⏳ Анализирую фото...")

    photo = message.photo[-1]

    # Выбираем промпт в зависимости от режима
    if mode == Mode.RECEIPT:
        prompt = RECEIPT_OCR_PROMPT
        task = "receipt_ocr"
    elif mode == Mode.PART:
        prompt = PART_PHOTO_PROMPT
        task = "part_photo"
    elif mode == Mode.MAINTENANCE:
        prompt = ORDER_OCR_PROMPT
        task = "order_ocr"
    elif mode == Mode.BLUEPRINT:
        prompt = BLUEPRINT_PROMPT
        task = "blueprint"
    else:
        # По умолчанию — чек (самый частый кейс для фото)
        prompt = RECEIPT_OCR_PROMPT
        task = "receipt_ocr"

    result = await analyze_photo(
        bot=bot, photo=photo, prompt=prompt,
        task_type=task, user_id=user_id, bot_source=BOT_SOURCE,
    )

    json_data = _extract_json(result)

    # Определяем event_type и project_id
    if mode in (Mode.MAINTENANCE, Mode.PART):
        event_type = "auto_maintenance"
        project_id = PROJECT_AUTO
    else:
        event_type = "measurement"
        project_id = PROJECT_HOUSE

    event = await create_event(
        user_id=user_id,
        event_type=event_type,
        bot_source=BOT_SOURCE,
        raw_text=result,
        json_data=json_data,
        project_id=project_id,
    )

    # Если в JSON есть total — создаём запись в finances
    if json_data and project_id and "total" in json_data:
        total = json_data["total"]
        if isinstance(total, (int, float)) and total > 0:
            category = "auto_service" if mode in (Mode.MAINTENANCE, Mode.PART) else "materials"
            await create_finance(
                user_id=user_id,
                project_id=project_id,
                transaction_type="expense",
                amount=total,
                category=category,
                description=result[:200],
                source_event_id=event["id"],
            )

    # Сохраняем эмбеддинг для RAG-поиска
    await store_event_embedding(event["id"], result, user_id=user_id, bot_source=BOT_SOURCE)

    await processing.delete()
    await safe_answer(message, _strip_json_block(result), reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Голосовое ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
    await _init_project_ids()
    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Транскрибирую...")

    text = await transcribe_voice(bot=bot, voice=message.voice, user_id=user_id, bot_source=BOT_SOURCE)
    await processing.edit_text(f"🎤 <i>{text}</i>\n\n⏳ Обрабатываю...")

    mode = get_user_mode(user_id)
    await _process_text(message, user_id, text, mode)


# === Текст ===

@router.message(F.text)
async def handle_text(message: Message, db_user: dict) -> None:
    await _init_project_ids()
    user_id = message.from_user.id  # type: ignore[union-attr]
    text = message.text or ""
    mode = get_user_mode(user_id)
    await _process_text(message, user_id, text, mode)


# === Внутренняя обработка текста/голоса ===

async def _process_text(message: Message, user_id: int, text: str, mode: Mode) -> None:
    """Маршрутизация текста по режиму."""

    # Режим «Вопрос» — RAG-поиск
    if mode == Mode.QUESTION:
        await _process_question(message, user_id, text)
        return

    # Определяем конфигурацию
    cfg = _MODE_CONFIG[mode]
    system_prompt = cfg["system"]
    event_type = cfg["event_type"]
    task_type = cfg["task_type"]

    if mode in (Mode.MAINTENANCE, Mode.PART):
        project_id = PROJECT_AUTO
    else:
        project_id = PROJECT_HOUSE

    # Генерируем ответ через контекст
    messages = await build_messages(user_id, BOT_SOURCE, system_prompt, text)
    result = await chat(messages=messages, task_type=task_type, user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)

    event = await create_event(
        user_id=user_id,
        event_type=event_type,
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
        project_id=project_id,
    )

    # RAG embedding для будущих поисков
    await store_event_embedding(event["id"], text, user_id=user_id, bot_source=BOT_SOURCE)

    # Финансы из текста (если LLM вернул стоимость)
    if json_data and project_id and "cost" in json_data:
        cost = json_data["cost"]
        if isinstance(cost, (int, float)) and cost > 0:
            category = "auto_service" if mode in (Mode.MAINTENANCE, Mode.PART) else "materials"
            await create_finance(
                user_id=user_id,
                project_id=project_id,
                transaction_type="expense",
                amount=cost,
                category=category,
                description=text[:200],
                source_event_id=event["id"],
            )

    await safe_answer(message, _strip_json_block(result), reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _process_question(message: Message, user_id: int, query: str) -> None:
    """RAG-поиск по замерам, бортжурналу, запчастям."""
    # Сохраняем сообщение как событие + embedding для будущих поисков
    event = await create_event(
        user_id=user_id,
        event_type="auto_maintenance",
        bot_source=BOT_SOURCE,
        raw_text=query,
    )
    await store_event_embedding(event["id"], query, user_id=user_id, bot_source=BOT_SOURCE)

    # RAG-поиск с полным контекстом об активах
    result = await rag_answer(
        query=query,
        user_id=user_id,
        system_prompt=(
            "Ты — ассистент по дому и автомобилю пользователя.\n\n"
            f"Контекст об автомобиле:\n{MECHANIC_SYSTEM}\n\n"
            f"Контекст о доме:\n{FOREMAN_SYSTEM}\n\n"
            "Отвечай на вопрос пользователя, используя контекст из базы знаний "
            "и свои знания об его активах. Отвечай на русском."
        ),
        top_k=5,
        bot_source=BOT_SOURCE,
    )

    await safe_answer(message, result, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


def _strip_json_block(text: str) -> str:
    """Убрать JSON-блоки из текста для пользователя. JSON сохраняется в БД, но не показывается."""
    cleaned = re.sub(r'```json\s*.*?\s*```', '', text, flags=re.DOTALL).strip()
    return cleaned if cleaned else text


def _extract_json(text: str) -> dict | None:
    """Попытаться извлечь JSON из ответа LLM."""
    try:
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
