"""Хэндлеры бота Psychology — дневник, привычки, ретроспектива.

Доступ: только Алексей (admin). Жена и партнёр не видят этого бота.
Все записи дневника → events + RAG embedding для долгосрочной рефлексии.
Кросс-бот контекст: психолог видит данные ВСЕХ ботов Life OS.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.ai.rag import rag_answer, store_event_embedding
from src.ai.router import chat
from src.ai.whisper import transcribe_voice
from src.core.context import build_messages, save_assistant_reply
from src.utils.telegram import safe_answer
from src.db.queries import create_event, get_active_goals, get_cross_bot_summary
from src.bots.psychology.keyboard import (
    Mode,
    get_user_mode,
    habits_inline,
    main_keyboard,
    mood_inline,
    set_user_mode,
)
from src.bots.psychology.prompts import (
    DIARY_PROMPT,
    HABIT_CHECK_PROMPT,
    MOOD_LABELS,
    PSYCHOLOGY_SYSTEM,
    RETROSPECTIVE_PROMPT,
)

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "psychology"
MSK = ZoneInfo("Europe/Moscow")

BOT_LABELS = {
    "health": "🏥 Здоровье",
    "assets": "🏠 Дом/Авто",
    "business": "💼 Бизнес",
    "family": "👨‍👩‍👧‍👦 Семья",
    "master": "🧠 Мастер",
    "partner": "🤝 Партнёр",
    "mentor": "📈 Ментор",
}


async def _build_life_context(user_id: int) -> str:
    """Собрать краткий контекст из всех ботов за последнюю неделю."""
    events = await get_cross_bot_summary(user_id, days=7)
    if not events:
        return "Нет данных из других ботов за последнюю неделю."

    lines = []
    for ev in events[:30]:
        bot = BOT_LABELS.get(ev["bot_source"], ev["bot_source"])
        event_type = ev.get("event_type", "")
        raw = (ev.get("raw_text") or "")[:100]
        jd = ev.get("json_data") or {}
        ts = ev.get("timestamp", "")
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%d.%m %H:%M")

        detail = raw
        if event_type == "meal" and jd.get("description"):
            detail = f"{jd['description']} ({jd.get('calories', '?')} ккал)"
        elif event_type == "business_task" and jd.get("title"):
            detail = jd["title"]

        lines.append(f"[{ts}] {bot} | {event_type}: {detail}")

    return "\n".join(lines)


async def _psychology_system(user_id: int) -> str:
    """Собрать полный system prompt для психолога с контекстом жизни."""
    now_str = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
    life_context = await _build_life_context(user_id)
    return PSYCHOLOGY_SYSTEM.format(current_time=now_str, life_context=life_context)


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    await message.answer(
        f"Привет, {name} 🧠\n\n"
        f"Я твой AI-психолог и дневник рефлексии.\n\n"
        f"📝 Дневник — записать мысли текстом\n"
        f"🎙 Голос — надиктовать запись\n"
        f"✅ Привычки — отметить прогресс\n"
        f"😊 Настроение — оценить день\n"
        f"🔮 Ретроспектива — анализ за неделю\n\n"
        f"Просто напиши или надиктуй — всё попадёт в дневник.",
        reply_markup=main_keyboard(),
    )


# === Reply-клавиатура: режимы ===

@router.message(F.text == "📝 Дневник")
async def mode_diary(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.DIARY)  # type: ignore[union-attr]
    await message.answer(
        "📝 Режим <b>Дневник</b>.\nПиши что на душе — всё сохранится и пойдёт в анализ.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🎙 Голос")
async def mode_voice_hint(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.DIARY)  # type: ignore[union-attr]
    await message.answer(
        "🎙 Отправь голосовое сообщение — я транскрибирую и сохраню в дневник.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "✅ Привычки")
async def mode_habits(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.HABITS)

    goals = await get_active_goals(user_id)
    habits = [g for g in goals if g.get("type") == "habit_target"]

    if not habits:
        await message.answer(
            "Нет активных привычек для трекинга.\n"
            "Добавь через /add_habit &lt;название&gt;",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer(
        "✅ Отметь прогресс по привычкам:",
        reply_markup=habits_inline(habits),
    )


@router.message(F.text == "😊 Настроение")
async def mode_mood(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.MOOD)  # type: ignore[union-attr]
    await message.answer(
        "😊 Как ты себя сейчас чувствуешь?",
        reply_markup=mood_inline(),
    )


@router.message(F.text == "🔮 Ретроспектива")
async def mode_retro(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.RETRO)

    processing = await message.answer("⏳ Анализирую записи за неделю...")

    system = await _psychology_system(user_id)
    result = await rag_answer(
        query="Мои записи в дневнике и привычки за последнюю неделю",
        user_id=user_id,
        system_prompt=system + "\n\n" + RETROSPECTIVE_PROMPT,
        top_k=15,
        bot_source=BOT_SOURCE,
    )

    await processing.edit_text(f"🔮 <b>Ретроспектива</b>\n\n{result}")
    await save_assistant_reply(user_id, BOT_SOURCE, result)


@router.message(F.text == "➕ Привычка")
async def mode_add_habit(message: Message, db_user: dict) -> None:
    set_user_mode(message.from_user.id, Mode.ADD_HABIT)  # type: ignore[union-attr]
    await message.answer(
        "✏️ Напиши название новой привычки:",
        reply_markup=main_keyboard(),
    )


# === /add_habit ===

@router.message(Command("add_habit"))
async def cmd_add_habit(message: Message, db_user: dict) -> None:
    from src.db.queries import create_goal

    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/add_habit", "").strip()

    if not args:
        await message.answer("Использование: /add_habit Не курить")
        return

    await create_goal(
        user_id=user_id,
        goal_type="habit_target",
        title=args,
    )

    await message.answer(
        f"✅ Привычка добавлена: <b>{args}</b>\n"
        f"Теперь отмечай прогресс через кнопку «✅ Привычки».",
        reply_markup=main_keyboard(),
    )


# === Callback: привычки ===

@router.callback_query(F.data.startswith("psy:ok:") | F.data.startswith("psy:fail:"))
async def cb_habit(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")  # type: ignore[union-attr]
    status = "success" if parts[1] == "ok" else "relapse"
    goal_id = int(parts[2])
    user_id = callback.from_user.id

    # Получаем привычку
    from src.db.queries import get_goal, get_recent_events

    goal = await get_goal(goal_id)
    habit_title = goal.get("title", "привычка") if goal else "привычка"

    # Считаем серию (streak) — сколько подряд success
    recent_evts = await get_recent_events(
        user_id=user_id,
        event_type="habit",
        bot_source=BOT_SOURCE,
        limit=30,
    )

    streak = 0
    for ev in recent_evts:
        jd = ev.get("json_data") or {}
        if jd.get("goal_id") == goal_id and jd.get("status") == "success":
            streak += 1
        elif jd.get("goal_id") == goal_id:
            break

    if status == "success":
        streak += 1

    # Сохраняем событие
    event = await create_event(
        user_id=user_id,
        event_type="habit",
        bot_source=BOT_SOURCE,
        raw_text=f"{habit_title}: {status}",
        json_data={"goal_id": goal_id, "status": status, "streak": streak},
    )

    # Генерируем реакцию LLM
    prompt = HABIT_CHECK_PROMPT.format(
        habit=habit_title,
        status="держится" if status == "success" else "сорвался",
        streak=streak,
    )
    system = await _psychology_system(user_id)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    reply = await chat(
        messages=messages,
        task_type="psychology_habit",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    emoji = "✅" if status == "success" else "❌"
    status_text = "Держишься!" if status == "success" else "Срыв"
    text = (
        f"{emoji} <b>{habit_title}</b>: {status_text}\n"
        f"🔥 Серия: {streak} дн.\n\n"
        f"{reply}"
    )

    await callback.answer(f"{emoji} {status_text}")
    if callback.message:
        await safe_answer(callback.message, text, reply_markup=main_keyboard())  # type: ignore[union-attr]

    await store_event_embedding(event["id"], f"{habit_title}: {status}, серия {streak} дней", user_id, BOT_SOURCE)
    await save_assistant_reply(user_id, BOT_SOURCE, reply)


# === Callback: настроение ===

@router.callback_query(F.data.startswith("psy:mood:"))
async def cb_mood(callback: CallbackQuery) -> None:
    score = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    user_id = callback.from_user.id
    label = MOOD_LABELS.get(score, f"Настроение: {score}")

    event = await create_event(
        user_id=user_id,
        event_type="diary",
        bot_source=BOT_SOURCE,
        raw_text=f"Настроение: {label} ({score}/5)",
        json_data={"mood_score": score},
    )

    await store_event_embedding(event["id"], f"Настроение: {label}", user_id, BOT_SOURCE)

    await callback.answer(label)
    if callback.message:
        await callback.message.answer(  # type: ignore[union-attr]
            f"{label}\n\nЗаписал. Хочешь добавить что-нибудь к этому дню?",
            reply_markup=main_keyboard(),
        )


# === Голосовое → дневник ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Транскрибирую...")

    text = await transcribe_voice(bot=bot, voice=message.voice, user_id=user_id, bot_source=BOT_SOURCE)
    await processing.edit_text(f"🎤 <i>{text}</i>\n\n⏳ Анализирую...")
    await _process_diary(message, user_id, text)


# === Текст → дневник ===

@router.message(F.text)
async def handle_text(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    text = message.text or ""

    # Режим «Новая привычка» — создаём привычку из текста
    if get_user_mode(user_id) == Mode.ADD_HABIT:
        from src.db.queries import create_goal

        name = text.strip()
        if not name:
            await message.answer("Название не может быть пустым.", reply_markup=main_keyboard())
            return
        await create_goal(user_id=user_id, goal_type="habit_target", title=name)
        set_user_mode(user_id, Mode.DIARY)
        await message.answer(
            f"✅ Привычка добавлена: <b>{name}</b>\n"
            f"Теперь отмечай прогресс через кнопку «✅ Привычки».",
            reply_markup=main_keyboard(),
        )
        return

    await _process_diary(message, user_id, text)


# === Обработка дневниковой записи ===

async def _process_diary(message: Message, user_id: int, text: str) -> None:
    """Сохранить запись в events + embedding, получить обратную связь от LLM."""
    # Сохраняем событие
    event = await create_event(
        user_id=user_id,
        event_type="diary",
        bot_source=BOT_SOURCE,
        raw_text=text,
    )

    # RAG embedding для долгосрочной рефлексии
    await store_event_embedding(event["id"], text, user_id, BOT_SOURCE)

    # Обратная связь от психолога
    system = await _psychology_system(user_id)
    messages = await build_messages(
        user_id=user_id,
        bot_source=BOT_SOURCE,
        system_prompt=system + "\n\n" + DIARY_PROMPT,
        user_text=text,
    )
    reply = await chat(
        messages=messages,
        task_type="psychology_diary",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    await safe_answer(message, reply, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, reply)
