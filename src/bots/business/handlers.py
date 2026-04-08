"""Хэндлеры бота Business — мульти-проектный бизнес-ассистент."""

import json

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.ai.rag import rag_answer, store_event_embedding
from src.ai.router import chat
from src.ai.whisper import transcribe_voice
from src.config import settings
from src.core.context import build_messages, save_assistant_reply
from src.utils.telegram import safe_answer, safe_answer_voice
from src.db.queries import (
    archive_project,
    create_event,
    create_finance,
    create_project,
    get_finance_summary,
    get_project,
    get_project_events,
    get_projects_by_type,
    get_active_work_session,
    start_work_session,
    stop_work_session,
    get_work_stats,
    get_work_sessions,
)
from src.bots.business.keyboard import (
    Mode,
    get_user_mode,
    main_keyboard,
    pop_pending,
    projects_inline,
    set_keyboard_user,
    set_pending,
    set_user_mode,
)
from src.bots.business.prompts import (
    IDEA_PROMPT,
    REPORT_HEADER,
    TASK_PROMPT,
    build_business_system,
)
from src.integrations.obsidian.writer import obsidian

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "business"


# --- Middleware: устанавливает user_id для keyboard (скрытие таймера) ---

@router.message.middleware()
async def _set_kb_user_mw(handler, event, data):
    if event.from_user:
        set_keyboard_user(event.from_user.id)
    return await handler(event, data)


@router.callback_query.middleware()
async def _set_kb_user_cb_mw(handler, event, data):
    if event.from_user:
        set_keyboard_user(event.from_user.id)
    return await handler(event, data)


async def _get_project_system(project_id: int) -> str:
    """Собрать system prompt c учётом per-project промпта из metadata."""
    proj = await get_project(project_id)
    if proj:
        meta = proj.get("metadata") or {}
        return build_business_system(
            project_name=proj.get("name"),
            project_prompt=meta.get("system_prompt"),
        )
    return build_business_system()


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    text = (
        f"Привет, {name}! 💼\n"
        f"Я твой бизнес-ассистент.\n\n"
        f"💡 Идея — запиши бизнес-идею\n"
        f"📋 Задача — поставь задачу по проекту\n"
        f"📁 Проекты — управление проектами\n"
        f"📊 Отчёт — финансовая сводка"
    )
    if _is_timer_allowed(user_id):
        text += "\n⏱ Таймер — учёт рабочего времени"
    await message.answer(text, reply_markup=main_keyboard())


# === /add_project <name> ===

@router.message(Command("add_project"))
async def cmd_add_project(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "Использование: <code>/add_project Название проекта</code>",
            reply_markup=main_keyboard(),
        )
        return

    name = args[1].strip()
    project = await create_project(user_id, name, project_type="solo")
    await message.answer(
        f"✅ Проект <b>{project['name']}</b> создан (ID: {project['project_id']}).",
        reply_markup=main_keyboard(),
    )


# === /archive_project ===

@router.message(Command("archive_project"))
async def cmd_archive_project(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    projects = await get_projects_by_type(user_id, "solo")
    if not projects:
        await message.answer("У тебя нет активных проектов.", reply_markup=main_keyboard())
        return

    await message.answer(
        "Выбери проект для архивации:",
        reply_markup=projects_inline(projects, action="archive"),
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


# === Reply-клавиатура ===

@router.message(F.text == "💡 Идея")
async def mode_idea(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.IDEA)  # type: ignore[union-attr]
    await message.answer(
        "💡 Режим <b>Идея</b>.\nНапиши или надиктуй бизнес-идею.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📋 Задача")
async def mode_task(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.TASK)  # type: ignore[union-attr]
    await message.answer(
        "📋 Режим <b>Задача</b>.\nОпиши задачу — я структурирую.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📁 Проекты")
async def mode_projects(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROJECTS)
    projects = await get_projects_by_type(user_id, "solo")

    if not projects:
        await message.answer(
            "У тебя нет активных проектов.\n"
            "Создай: <code>/add_project Название</code>",
            reply_markup=main_keyboard(),
        )
        return

    text = "📁 <b>Активные проекты:</b>\n\n"
    for p in projects:
        text += f"• <b>{p['name']}</b> (ID: {p['project_id']})\n"
    text += "\nКоманды:\n/add_project — создать\n/archive_project — архивировать"

    await message.answer(text, reply_markup=main_keyboard())


@router.message(F.text == "➕ Новый проект")
async def mode_add_project(message: Message, db_user: dict) -> None:
    set_user_mode(message.from_user.id, Mode.ADD_PROJECT)  # type: ignore[union-attr]
    await message.answer(
        "✏️ Напиши название нового проекта:",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📊 Отчёт")
async def mode_report(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.REPORT)
    projects = await get_projects_by_type(user_id, "solo")

    if not projects:
        await message.answer("Нет проектов для отчёта.", reply_markup=main_keyboard())
        return

    await message.answer(
        "Выбери проект для финансового отчёта:",
        reply_markup=projects_inline(projects, action="report"),
    )


# === Callback: выбор проекта ===

@router.callback_query(F.data.startswith("biz:"))
async def cb_project_action(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")  # type: ignore[union-attr]
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    action = parts[1]
    project_id = int(parts[2])
    user_id = callback.from_user.id

    if action == "select":
        await _attach_to_project(callback, user_id, project_id)
    elif action == "report":
        await _send_report(callback, project_id)
    elif action == "archive":
        await _do_archive(callback, user_id, project_id)


async def _attach_to_project(callback: CallbackQuery, user_id: int, project_id: int) -> None:
    """Привязать pending идею/задачу к проекту."""
    text = pop_pending(user_id)
    if not text:
        await callback.answer("Нет текста для привязки")
        return

    mode = get_user_mode(user_id)
    if mode == Mode.TASK:
        system = TASK_PROMPT
        event_type = "business_task"
        task_type = "business_strategy"
    else:
        system = IDEA_PROMPT
        event_type = "business_task"
        task_type = "business_strategy"

    base_system = await _get_project_system(project_id)
    messages = [
        {"role": "system", "content": base_system + "\n\n" + system},
        {"role": "user", "content": text},
    ]
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

    # RAG embedding
    await store_event_embedding(event["id"], text, user_id=user_id, bot_source=BOT_SOURCE)
    await obsidian.log_idea(text, source="business")

    # Обновить Project README в Obsidian
    proj = await get_project(project_id)
    if proj:
        fin = await get_finance_summary(project_id)
        evts = await get_project_events(project_id, limit=10)
        await obsidian.update_project_readme(proj, fin, evts)

    await callback.answer("✅ Сохранено")
    if callback.message:
        await callback.message.answer(result, reply_markup=main_keyboard())  # type: ignore[union-attr]
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _send_report(callback: CallbackQuery, project_id: int) -> None:
    """Финансовый отчёт — строго через SQL."""
    summary = await get_finance_summary(project_id)

    if not summary:
        await callback.answer("Нет финансовых данных")
        if callback.message:
            await callback.message.answer(  # type: ignore[union-attr]
                "📊 По этому проекту пока нет финансовых записей.",
                reply_markup=main_keyboard(),
            )
        return

    # Формируем текстовый отчёт из SQL-данных
    text = REPORT_HEADER.format(project_name=f"ID {project_id}")
    income_total = 0.0
    expense_total = 0.0

    for row in summary:
        tt = row.get("transaction_type", "")
        cat = row.get("category", "—")
        total = row.get("total", 0)

        if tt == "income":
            income_total += total
            emoji = "📈"
        else:
            expense_total += total
            emoji = "📉"

        text += f"{emoji} {cat}: <b>{total:,.0f} ₽</b>\n"

    text += f"\n💰 Доходы: <b>{income_total:,.0f} ₽</b>\n"
    text += f"💸 Расходы: <b>{expense_total:,.0f} ₽</b>\n"
    text += f"📊 Баланс: <b>{income_total - expense_total:,.0f} ₽</b>"

    await callback.answer("Отчёт готов")
    if callback.message:
        await callback.message.answer(text, reply_markup=main_keyboard())  # type: ignore[union-attr]


async def _do_archive(callback: CallbackQuery, user_id: int, project_id: int) -> None:
    """Архивировать проект."""
    ok = await archive_project(project_id, user_id)
    if ok:
        await callback.answer("✅ Проект архивирован")
        if callback.message:
            await callback.message.answer(  # type: ignore[union-attr]
                f"🗄 Проект ID {project_id} архивирован.",
                reply_markup=main_keyboard(),
            )
    else:
        await callback.answer("Ошибка архивации")


# === ⏱ Таймер — учёт рабочего времени (только admin) ===

def _to_msk(dt):
    """Конвертировать datetime в московское время для отображения."""
    from zoneinfo import ZoneInfo
    if dt and hasattr(dt, "astimezone"):
        return dt.astimezone(ZoneInfo("Europe/Moscow"))
    return dt


def _is_timer_allowed(user_id: int) -> bool:
    return user_id == settings.admin_user_id


@router.message(F.text == "⏱ Таймер")
async def mode_timer(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    if not _is_timer_allowed(user_id):
        await message.answer("Эта функция недоступна.", reply_markup=main_keyboard())
        return
    set_user_mode(user_id, Mode.TIMER)
    active = await get_active_work_session(user_id)

    if active:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        start_msk = _to_msk(active["start_time"])
        start_str = start_msk.strftime("%H:%M") if hasattr(start_msk, "strftime") else str(start_msk)
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        elapsed = int((now - active["start_time"]).total_seconds() // 60)
        elapsed_h, elapsed_m = divmod(max(elapsed, 0), 60)
        await message.answer(
            f"⏱ <b>Таймер запущен</b> с {start_str}\n"
            f"⏳ Прошло: {elapsed_h}ч {elapsed_m}мин\n\n"
            f"⏹ Остановить: /stop",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(
            "⏱ <b>Учёт рабочего времени</b>\n\n"
            "▶️ Начать: /work\n"
            "⏹ Закончить: /stop\n"
            "📊 Статистика: /workstats\n\n"
            "Данные доступны психологу и доктору.",
            reply_markup=main_keyboard(),
        )


@router.message(Command("work"))
async def cmd_work_start(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    if not _is_timer_allowed(user_id):
        return
    session = await start_work_session(user_id)
    start_msk = _to_msk(session["start_time"])
    start_str = start_msk.strftime("%H:%M") if hasattr(start_msk, "strftime") else str(start_msk)
    await message.answer(
        f"▶️ <b>Работа начата</b> в {start_str}\n\n"
        f"Когда закончишь — нажми /stop",
        reply_markup=main_keyboard(),
    )


@router.message(Command("stop"))
async def cmd_work_stop(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    if not _is_timer_allowed(user_id):
        return
    session = await stop_work_session(user_id)
    if not session:
        await message.answer(
            "❌ Нет активного таймера.\nНачать: /work",
            reply_markup=main_keyboard(),
        )
        return

    dur = session.get("duration_minutes") or 0
    h, m = divmod(dur, 60)
    start_msk = _to_msk(session["start_time"])
    end_msk = _to_msk(session["end_time"])
    start_str = start_msk.strftime("%H:%M") if hasattr(start_msk, "strftime") else str(start_msk)
    end_str = end_msk.strftime("%H:%M") if hasattr(end_msk, "strftime") else str(end_msk)

    await message.answer(
        f"⏹ <b>Работа завершена</b>\n\n"
        f"🕐 {start_str} → {end_str}\n"
        f"⏱ Длительность: <b>{h}ч {m}мин</b>",
        reply_markup=main_keyboard(),
    )


@router.message(Command("workstats"))
async def cmd_workstats(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    if not _is_timer_allowed(user_id):
        return

    week = await get_work_stats(user_id, days=7)
    month = await get_work_stats(user_id, days=30)
    sessions = await get_work_sessions(user_id, days=7)

    if week["sessions"] == 0 and month["sessions"] == 0:
        await message.answer(
            "📊 Нет данных о рабочем времени.\nНачни с /work",
            reply_markup=main_keyboard(),
        )
        return

    text = "📊 <b>Статистика рабочего времени</b>\n\n"

    # Недельная
    w_total_h, w_total_m = divmod(int(week["total_minutes"]), 60)
    w_avg_h, w_avg_m = divmod(int(week["avg_minutes"]), 60)
    text += (
        f"📅 <b>Неделя:</b>\n"
        f"  Сессий: {week['sessions']}, рабочих дней: {week['work_days']}\n"
        f"  Всего: <b>{w_total_h}ч {w_total_m}мин</b>\n"
        f"  Среднее: {w_avg_h}ч {w_avg_m}мин/сессия\n\n"
    )

    # Месячная
    m_total_h, m_total_m = divmod(int(month["total_minutes"]), 60)
    m_avg_h, m_avg_m = divmod(int(month["avg_minutes"]), 60)
    text += (
        f"📆 <b>Месяц:</b>\n"
        f"  Сессий: {month['sessions']}, рабочих дней: {month['work_days']}\n"
        f"  Всего: <b>{m_total_h}ч {m_total_m}мин</b>\n"
        f"  Среднее: {m_avg_h}ч {m_avg_m}мин/сессия\n\n"
    )

    # Последние сессии
    if sessions:
        text += "🕐 <b>Последние сессии:</b>\n"
        for s in sessions[:7]:
            st_msk = _to_msk(s["start_time"])
            dur = s.get("duration_minutes") or 0
            dh, dm = divmod(dur, 60)
            st_str = st_msk.strftime("%d.%m %H:%M") if hasattr(st_msk, "strftime") else str(st_msk)
            text += f"  [{st_str}] {dh}ч {dm}мин\n"

    await message.answer(text, reply_markup=main_keyboard())


# === Голосовое ===

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
            f"📋 <b>Краткое содержание:</b>\n{summary}\n\n⏳ Обрабатываю..."
        )
    else:
        await processing.edit_text(f"🎤 <i>{text}</i>\n\n⏳ Обрабатываю...")
    await _process_input(message, user_id, text)


# === Текст ===

@router.message(F.text)
async def handle_text(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    text = message.text or ""
    await _process_input(message, user_id, text)


# === Обработка ввода ===

async def _process_input(message: Message, user_id: int, text: str) -> None:
    mode = get_user_mode(user_id)

    # Режим таймера — подсказка
    if mode == Mode.TIMER:
        await message.answer(
            "⏱ Используй /work и /stop для управления таймером.",
            reply_markup=main_keyboard(),
        )
        return

    # Режим «Новый проект» — создаём проект из текста
    if mode == Mode.ADD_PROJECT:
        name = text.strip()
        if not name:
            await message.answer("Название не может быть пустым.", reply_markup=main_keyboard())
            return
        project = await create_project(user_id, name, project_type="solo")
        set_user_mode(user_id, Mode.IDEA)
        await message.answer(
            f"✅ Проект <b>{project['name']}</b> создан (ID: {project['project_id']}).",
            reply_markup=main_keyboard(),
        )
        return

    # Режим «Проекты» / «Отчёт» — свободный текст как RAG-запрос
    if mode in (Mode.PROJECTS, Mode.REPORT):
        await _process_question(message, user_id, text)
        return

    # Идея / Задача — сначала выбрать проект
    projects = await get_projects_by_type(user_id, "solo")

    if not projects:
        await message.answer(
            "Сначала создай проект: <code>/add_project Название</code>",
            reply_markup=main_keyboard(),
        )
        return

    if len(projects) == 1:
        # Один проект — привязываем автоматически
        set_pending(user_id, text)
        # Эмулируем callback
        await _attach_to_project_direct(message, user_id, projects[0]["project_id"], text)
    else:
        # Несколько — показываем выбор
        set_pending(user_id, text)
        await message.answer(
            "К какому проекту отнести?",
            reply_markup=projects_inline(projects, action="select"),
        )


async def _attach_to_project_direct(
    message: Message, user_id: int, project_id: int, text: str,
) -> None:
    """Привязать идею/задачу напрямую (один проект)."""
    pop_pending(user_id)  # очищаем pending

    mode = get_user_mode(user_id)
    system = TASK_PROMPT if mode == Mode.TASK else IDEA_PROMPT

    base_system = await _get_project_system(project_id)
    messages = [
        {"role": "system", "content": base_system + "\n\n" + system},
        {"role": "user", "content": text},
    ]
    result = await chat(messages=messages, task_type="business_strategy", user_id=user_id, bot_source=BOT_SOURCE)

    json_data = _extract_json(result)
    event = await create_event(
        user_id=user_id,
        event_type="business_task",
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
        project_id=project_id,
    )

    await store_event_embedding(event["id"], text, user_id=user_id, bot_source=BOT_SOURCE)
    await obsidian.log_idea(text, source="business")

    # Обновить Project README в Obsidian
    proj = await get_project(project_id)
    if proj:
        fin = await get_finance_summary(project_id)
        evts = await get_project_events(project_id, limit=10)
        await obsidian.update_project_readme(proj, fin, evts)

    await safe_answer_voice(message, result, user_id, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _process_question(message: Message, user_id: int, query: str) -> None:
    """RAG-поиск по бизнес-идеям."""
    result = await rag_answer(
        query=query,
        user_id=user_id,
        system_prompt=(
            "Ты бизнес-ассистент. Отвечай на вопрос пользователя "
            "по его ранее записанным идеям, задачам и заметкам. "
            "Если данных нет — скажи об этом."
        ),
        top_k=5,
        bot_source=BOT_SOURCE,
    )
    await safe_answer_voice(message, result, user_id, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


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
