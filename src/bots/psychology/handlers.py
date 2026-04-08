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
from src.utils.telegram import safe_answer, safe_answer_voice
from src.db.queries import create_event, get_active_goals, get_cross_bot_summary, get_gratitude_today, get_life_profile, get_user, update_user_settings
from src.bots.psychology.keyboard import (
    Mode,
    energy_inline,
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
    PSY_PROFILE_HELP,
    PSYCHOLOGY_SYSTEM,
    RETROSPECTIVE_PROMPT,
)
from src.integrations.obsidian.writer import obsidian

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

    # Профиль жизни — авто, дом, активы (без лимита по дате)
    profile_events = await get_life_profile(user_id)

    if not events and not profile_events:
        return "Нет данных из других ботов."

    lines = []

    # Профиль: авто, дом и т.д.
    if profile_events:
        lines.append("📌 ПРОФИЛЬ (активы, имущество):")
        for ev in profile_events:
            bot = BOT_LABELS.get(ev["bot_source"], ev["bot_source"])
            raw = (ev.get("raw_text") or "")[:150]
            jd = ev.get("json_data") or {}
            detail = jd.get("description") or jd.get("title") or raw
            lines.append(f"  {bot}: {detail}")
        lines.append("")

    # Последние события за неделю
    if events:
        lines.append("📡 СОБЫТИЯ ЗА НЕДЕЛЮ:")
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
            elif event_type == "auto_maintenance" and jd.get("description"):
                detail = jd["description"]

            lines.append(f"  [{ts}] {bot} | {event_type}: {detail}")

    return "\n".join(lines)


async def _build_user_goals(user_id: int) -> str:
    """Собрать глобальные цели пользователя для контекста."""
    goals = await get_active_goals(user_id)
    if not goals:
        return "Нет активных целей."
    lines = []
    for g in goals:
        goal_type = g.get("type", "")
        title = g.get("title", "")
        progress = g.get("progress_pct", 0) or 0
        emoji = {"🌟": "dream", "🎯": "yearly_goal", "✅": "habit_target"}.get(goal_type, "📌")
        # Инвертируем маппинг
        emoji = "🌟" if goal_type == "dream" else "🎯" if goal_type == "yearly_goal" else "✅"
        lines.append(f"  {emoji} {title} ({progress}%)")
    return "\n".join(lines)


async def _psychology_system(user_id: int) -> str:
    """Собрать полный system prompt для психолога с контекстом жизни."""
    now_str = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
    life_context = await _build_life_context(user_id)
    user_goals = await _build_user_goals(user_id)
    return PSYCHOLOGY_SYSTEM.format(
        current_time=now_str, life_context=life_context, user_goals=user_goals,
    )


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
        f"🔮 Ретроспектива — анализ за неделю\n"
        f"📋 Мой профиль — расскажи о себе\n\n"
        f"Просто напиши или надиктуй — всё попадёт в дневник.",
        reply_markup=main_keyboard(),
    )


# === /voice — голосовые ответы AI ===

@router.message(Command("voice"))
async def cmd_voice_toggle(message: Message, db_user: dict) -> None:
    """Переключить режим голосовых ответов."""
    from src.ai.tts import toggle_voice_mode

    user_id = message.from_user.id  # type: ignore[union-attr]
    enabled = toggle_voice_mode(user_id)
    if enabled:
        await message.answer(
            "🔊 <b>Голосовые ответы включены!</b>\n\n"
            "Теперь AI будет отвечать текстом + голосом.\n"
            "Повтори /voice чтобы выключить.",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(
            "🔇 Голосовые ответы выключены.\n"
            "Повтори /voice чтобы включить.",
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
    user_goals = await _build_user_goals(user_id)
    retro_prompt = RETROSPECTIVE_PROMPT.format(user_goals=user_goals)
    result = await rag_answer(
        query="Мои записи в дневнике и привычки за последнюю неделю",
        user_id=user_id,
        system_prompt=system + "\n\n" + retro_prompt,
        top_k=15,
        bot_source=BOT_SOURCE,
    )

    await processing.edit_text(f"🔮 <b>Ретроспектива</b>\n\n{result}")
    await save_assistant_reply(user_id, BOT_SOURCE, result)

    # Голосовой ответ если включён
    from src.ai.tts import is_voice_mode, text_to_voice

    if is_voice_mode(user_id):
        voice_path = await text_to_voice(result)
        if voice_path:
            try:
                from aiogram.types import FSInputFile
                await message.answer_voice(FSInputFile(str(voice_path)))
            except Exception:
                logger.exception("voice_retro_failed")
            finally:
                voice_path.unlink(missing_ok=True)


@router.message(F.text == "➕ Привычка")
async def mode_add_habit(message: Message, db_user: dict) -> None:
    set_user_mode(message.from_user.id, Mode.ADD_HABIT)  # type: ignore[union-attr]
    await message.answer(
        "✏️ Напиши название новой привычки:",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🙏 Благодарности")
async def mode_gratitude(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.GRATITUDE)

    entries = await get_gratitude_today(user_id)
    count = len(entries)

    if count >= 3:
        text = "🙏 <b>Благодарности за сегодня:</b>\n\n"
        for i, e in enumerate(entries, 1):
            text += f"{i}. {e.get('raw_text', '')}\n"
        text += f"\n✅ Отлично! Ты записал {count} благодарност{'и' if 2 <= count <= 4 else 'ей'}."
    elif count > 0:
        text = "🙏 <b>Благодарности за сегодня:</b>\n\n"
        for i, e in enumerate(entries, 1):
            text += f"{i}. {e.get('raw_text', '')}\n"
        text += f"\n✏️ Осталось ещё {3 - count}. За что ты ещё благодарен сегодня?"
    else:
        text = (
            "🙏 <b>Журнал благодарностей</b>\n\n"
            "Напиши 3 вещи, за которые ты благодарен сегодня.\n"
            "Это могут быть мелочи: вкусный кофе, хорошая погода, "
            "поддержка близких.\n\n"
            "✏️ Просто напиши — по одной за раз."
        )

    await message.answer(text, reply_markup=main_keyboard())


@router.message(F.text == "⚡ Энергия")
async def mode_energy(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.ENERGY)
    await message.answer(
        "⚡ <b>Трекер энергии</b>\n\n"
        "Оцени свой текущий уровень энергии от 1 до 10:",
        reply_markup=energy_inline(),
    )


@router.message(F.text == "📋 Мой профиль")
async def mode_profile(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROFILE)
    await _show_profile_psy(message, user_id)


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


# === Callback: энергия ===

ENERGY_LABELS = {
    1: "🪫 1 — Полностью разряжен",
    2: "😴 2 — Очень устал",
    3: "😑 3 — Мало сил",
    4: "🙁 4 — Ниже среднего",
    5: "😐 5 — Нормально",
    6: "🙂 6 — Неплохо",
    7: "😊 7 — Хорошо",
    8: "💪 8 — Много энергии",
    9: "🔥 9 — Отлично",
    10: "⚡ 10 — На максимуме!",
}


@router.callback_query(F.data.startswith("psy:energy:"))
async def cb_energy(callback: CallbackQuery) -> None:
    score = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    user_id = callback.from_user.id
    label = ENERGY_LABELS.get(score, f"Энергия: {score}")

    event = await create_event(
        user_id=user_id,
        event_type="energy",
        bot_source=BOT_SOURCE,
        raw_text=f"Энергия: {label} ({score}/10)",
        json_data={"energy_score": score},
    )

    await store_event_embedding(event["id"], f"Энергия: {label}", user_id, BOT_SOURCE)

    await callback.answer(label)
    if callback.message:
        await callback.message.answer(  # type: ignore[union-attr]
            f"{label}\n\n⚡ Записал уровень энергии. Отслеживай в течение дня!",
            reply_markup=main_keyboard(),
        )


# === /export_diary — экспорт дневника в PDF ===

@router.message(Command("export_diary"))
async def cmd_export_diary(message: Message, db_user: dict) -> None:
    """Экспорт всех дневниковых записей в PDF."""
    import tempfile
    from pathlib import Path

    from aiogram.types import FSInputFile
    from fpdf import FPDF

    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Генерирую PDF...")

    # Собираем дневниковые записи, настроение, энергию, благодарности
    from src.db.queries import get_recent_events

    diary = await get_recent_events(user_id, "diary", BOT_SOURCE, limit=500)
    gratitude = await get_recent_events(user_id, "gratitude", BOT_SOURCE, limit=200)
    energy = await get_recent_events(user_id, "energy", BOT_SOURCE, limit=200)

    all_entries = sorted(diary + gratitude + energy, key=lambda e: e["timestamp"])

    if not all_entries:
        await processing.edit_text(
            "📋 Нет записей для экспорта.\n"
            "Начни вести дневник — записи появятся здесь.",
        )
        return

    # Создаём PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Добавляем шрифт с поддержкой кириллицы
    font_path = Path(__file__).parent.parent.parent / "assets" / "DejaVuSans.ttf"
    if font_path.exists():
        pdf.add_font("DejaVu", "", str(font_path), uni=True)
        pdf.add_font("DejaVu", "B", str(font_path.parent / "DejaVuSans-Bold.ttf"), uni=True)
        font_name = "DejaVu"
    else:
        # Fallback — работает только с латиницей, но не упадёт
        font_name = "Helvetica"

    pdf.add_page()
    pdf.set_font(font_name, "B", 16)
    pdf.cell(0, 10, "Life OS - Dnevnik", ln=True, align="C")
    pdf.set_font(font_name, "", 10)

    first_date = all_entries[0]["timestamp"]
    last_date = all_entries[-1]["timestamp"]
    period = f"{first_date.strftime('%d.%m.%Y')} - {last_date.strftime('%d.%m.%Y')}"
    pdf.cell(0, 8, f"Period: {period} | Entries: {len(all_entries)}", ln=True, align="C")
    pdf.ln(5)

    current_day = ""
    for entry in all_entries:
        ts = entry["timestamp"]
        day = ts.strftime("%d.%m.%Y")
        time_str = ts.strftime("%H:%M")

        if day != current_day:
            current_day = day
            pdf.ln(3)
            pdf.set_font(font_name, "B", 12)
            pdf.cell(0, 8, day, ln=True)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(2)

        event_type = entry.get("event_type", "")
        jd = entry.get("json_data") or {}
        raw = entry.get("raw_text") or ""

        # Иконка типа
        type_labels = {
            "diary": "[Diary]",
            "gratitude": "[Gratitude]",
            "energy": "[Energy]",
        }
        label = type_labels.get(event_type, f"[{event_type}]")

        # Доп. данные
        extra = ""
        if event_type == "diary" and jd.get("mood_score"):
            extra = f" (mood: {jd['mood_score']}/5)"
        elif event_type == "energy" and jd.get("energy_score"):
            extra = f" ({jd['energy_score']}/10)"

        pdf.set_font(font_name, "B", 10)
        pdf.cell(0, 6, f"{time_str} {label}{extra}", ln=True)

        if raw:
            pdf.set_font(font_name, "", 9)
            # Многострочный текст
            pdf.multi_cell(0, 5, raw[:2000])
        pdf.ln(2)

    # Сохраняем
    tmp = Path(tempfile.mktemp(suffix=".pdf"))
    pdf.output(str(tmp))

    doc = FSInputFile(str(tmp), filename=f"diary_{user_id}.pdf")
    await message.answer_document(doc, caption=f"📋 Экспорт дневника: {len(all_entries)} записей")
    await processing.delete()
    tmp.unlink(missing_ok=True)


# === Голосовое → дневник ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Транскрибирую...")

    text = await transcribe_voice(bot=bot, voice=message.voice, user_id=user_id, bot_source=BOT_SOURCE)

    # Саммаризация длинных голосовых (>5 мин)
    from src.ai.whisper import summarize_long_voice

    duration = message.voice.duration or 0  # type: ignore[union-attr]
    summary = await summarize_long_voice(text, duration, user_id, BOT_SOURCE)
    if summary:
        await processing.edit_text(
            f"📋 <b>Краткое содержание ({duration // 60} мин):</b>\n{summary}\n\n"
            f"🎤 <i>{text[:1000]}{'...' if len(text) > 1000 else ''}</i>\n\n⏳ Анализирую..."
        )
    else:
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

    # Режим «Профиль» — сохраняем описание пользователя
    if get_user_mode(user_id) == Mode.PROFILE:
        await _process_profile_psy(message, user_id, text)
        return

    # Режим «Благодарности» — сохраняем запись
    if get_user_mode(user_id) == Mode.GRATITUDE:
        await _process_gratitude(message, user_id, text)
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
    await obsidian.log_diary(text)

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

    await safe_answer_voice(message, reply, user_id, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, reply)


# === Профиль ===

async def _show_profile_psy(message: Message, user_id: int) -> None:
    """Показать текущий профиль пользователя."""
    user = await get_user(user_id)
    overrides = (user or {}).get("system_prompt_overrides") or ""
    if overrides:
        text = (
            "📋 <b>Мой профиль</b>\n\n"
            f"{overrides}\n\n"
            "━━━━━━━━━━━━━━━\n"
            "Чтобы обновить — просто напиши новый текст.\n"
            "Профиль общий для 🏥 Здоровье и 🧠 Психолог."
        )
    else:
        text = PSY_PROFILE_HELP
    await message.answer(text, reply_markup=main_keyboard())


async def _merge_profile(existing: str, new_text: str, user_id: int) -> str:
    """Слить новые данные с существующим профилем через AI."""
    result = await chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты — редактор профиля пользователя. "
                    "Тебе дан СУЩЕСТВУЮЩИЙ профиль и НОВЫЕ СВЕДЕНИЯ от пользователя.\n\n"
                    "Правила:\n"
                    "1. Объедини информацию: обнови/дополни существующий профиль новыми данными.\n"
                    "2. Если новые данные ПРОТИВОРЕЧАТ старым — используй НОВЫЕ (они актуальнее).\n"
                    "3. Сохрани всю остальную информацию из старого профиля без потерь.\n"
                    "4. Верни ТОЛЬКО итоговый текст профиля, без комментариев и пояснений.\n"
                    "5. Пиши на русском. Формат — свободный текст, структурированный и краткий."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"СУЩЕСТВУЮЩИЙ ПРОФИЛЬ:\n{existing}\n\n"
                    f"НОВЫЕ СВЕДЕНИЯ:\n{new_text}"
                ),
            },
        ],
        task_type="general_chat",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )
    return result.strip()


async def _process_profile_psy(message: Message, user_id: int, text: str) -> None:
    """Сохранение профиля пользователя через AI-мерж с существующими данными."""
    user = await get_user(user_id)
    existing = (user or {}).get("system_prompt_overrides") or ""

    if existing:
        merged = await _merge_profile(existing, text, user_id)
    else:
        merged = text

    await update_user_settings(user_id, merged)
    set_user_mode(user_id, Mode.DIARY)

    await message.answer(
        "✅ Профиль обновлён!\n\n"
        f"<i>{merged[:500]}</i>\n\n"
        "Буду учитывать в терапевтической работе.\n"
        "Профиль общий для 🏥 Здоровье и 🧠 Психолог.",
        reply_markup=main_keyboard(),
    )


async def _process_gratitude(message: Message, user_id: int, text: str) -> None:
    """Сохранить запись благодарности."""
    event = await create_event(
        user_id=user_id,
        event_type="gratitude",
        bot_source=BOT_SOURCE,
        raw_text=text.strip(),
    )

    await store_event_embedding(event["id"], f"Благодарность: {text}", user_id, BOT_SOURCE)

    entries = await get_gratitude_today(user_id)
    count = len(entries)

    if count >= 3:
        lines = "🙏 <b>Благодарности за сегодня:</b>\n\n"
        for i, e in enumerate(entries, 1):
            lines += f"{i}. {e.get('raw_text', '')}\n"
        lines += (
            "\n🌟 <b>Отлично!</b> Ты записал 3 благодарности.\n"
            "Практика благодарности снижает тревогу и повышает удовлетворённость жизнью."
        )
        set_user_mode(user_id, Mode.DIARY)
        await message.answer(lines, reply_markup=main_keyboard())
    else:
        remaining = 3 - count
        await message.answer(
            f"🙏 Записал! Осталось ещё {remaining}. Продолжай.",
            reply_markup=main_keyboard(),
        )
