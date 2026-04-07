"""Хэндлеры бота Master Intelligence — главный пульт Life OS.

Доступ: только admin (Алексей). Это центр управления всей экосистемой.
Хранитель Видения: перед каждым ответом — goals в system prompt.
Кросс-бот контекст: видит историю ВСЕХ ботов.
Управление промптами и моделями.
"""

import calendar as cal_module
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from src.utils.telegram import safe_answer, safe_edit

from src.ai.rag import rag_answer, search, store_event_embedding
from src.ai.router import chat, get_model_config
from src.ai.whisper import transcribe_voice
from src.core.context import build_messages, save_assistant_reply
from src.db.queries import (
    complete_task,
    create_event,
    create_goal,
    create_task,
    delete_task,
    get_active_goals,
    get_cross_bot_summary,
    get_finance_summary,
    get_obsidian_today_tasks,
    get_overdue_tasks,
    get_project,
    get_task_by_id,
    get_tasks_by_date,
    get_today_tasks,
    get_user_projects,
    get_week_tasks,
    reschedule_task,
    uncomplete_task,
    update_goal,
    update_project_metadata,
)
from src.bots.master.keyboard import (
    Mode,
    get_user_mode,
    main_keyboard,
    pop_pending_prompt_project,
    set_pending_prompt_project,
    set_user_mode,
)
from src.bots.master.prompts import (
    AUDIT_PROMPT,
    EVENING_REVIEW_HEADER,
    GOAL_ADD_PROMPT,
    MASTER_SYSTEM,
    PANORAMA_HEADER,
    PROACTIVE_PROMPT,
    TASK_PARSE_PROMPT,
    VISION_CONTEXT,
)
from src.integrations.obsidian.writer import obsidian

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "master"
MSK = ZoneInfo("Europe/Moscow")

BOT_LABELS = {
    "health": "🏥 Здоровье",
    "assets": "🏠 Дом/Авто",
    "business": "💼 Бизнес",
    "family": "👨‍👩‍👧‍👦 Семья",
    "psychology": "🧠 Психология",
    "partner": "🤝 Партнёр",
    "mentor": "📈 Ментор",
}


# === Хранитель Видения: goals + кросс-бот контекст → system prompt ===

async def _system_with_vision(user_id: int) -> str:
    """Добавить активные цели и кросс-бот контекст в system prompt."""
    now_str = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
    base = MASTER_SYSTEM + f"\n\nТекущее время: {now_str}"

    goals = await get_active_goals(user_id)

    if not goals:
        base += "\n\nУ пользователя пока нет целей."
    else:
        goals_text = ""
        for g in goals:
            emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}.get(g["type"], "📌")
            progress = g.get("progress_pct", 0)
            goals_text += f"{emoji} [{g['type']}] {g['title']} — {progress}%\n"
        base += VISION_CONTEXT.format(goals=goals_text)

    # Кросс-бот контекст — последние события из ВСЕХ ботов
    events = await get_cross_bot_summary(user_id, days=7)
    if events:
        cross_lines = []
        for ev in events[:20]:
            bot = BOT_LABELS.get(ev["bot_source"], ev["bot_source"])
            et = ev.get("event_type", "")
            raw = (ev.get("raw_text") or "")[:80]
            jd = ev.get("json_data") or {}
            ts = ev.get("timestamp", "")
            if hasattr(ts, "strftime"):
                ts = ts.strftime("%d.%m %H:%M")
            detail = jd.get("description") or jd.get("title") or raw
            cross_lines.append(f"[{ts}] {bot} | {et}: {detail}")
        base += "\n\n📡 ПОСЛЕДНИЕ СОБЫТИЯ ИЗ ВСЕХ БОТОВ:\n" + "\n".join(cross_lines)

    return base


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    await message.answer(
        f"Привет, {name} 🧠\n\n"
        f"Я — <b>Master Intelligence</b>, твой главный пульт управления Life OS.\n\n"
        f"📝 Дневник — записать мысли\n"
        f"🎯 Цели и Мечты — управление целями\n"
        f"⚙️ Проекты — обзор проектов\n"
        f"📊 Сводный отчёт — аудит жизни\n"
        f"💰 Финансовая панорама — все финансы\n\n"
        f"Или просто напиши — я сверю с твоими целями.",
        reply_markup=main_keyboard(),
    )


# === /export ===

@router.message(Command("export"))
async def cmd_export(message: Message, db_user: dict) -> None:
    from src.utils.export import export_user_data

    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Экспортирую данные...")

    path = await export_user_data(user_id)
    doc = FSInputFile(str(path), filename=f"life-os-export-{user_id}.json")
    await message.answer_document(doc, caption="📦 Экспорт данных Life OS")

    # Удаляем временный файл
    path.unlink(missing_ok=True)
    await processing.delete()


# === /status ===

@router.message(Command("status"))
async def cmd_status(message: Message, db_user: dict) -> None:
    from src.core.health import get_status

    status = await get_status()
    checks = status["checks"]
    emoji = "✅" if status["ok"] else "🔴"

    text = f"{emoji} <b>Статус Life OS</b>\n\n"
    for name, ok in checks.items():
        text += f"{'✅' if ok else '❌'} {name}\n"

    await message.answer(text, reply_markup=main_keyboard())


# === /charts ===

@router.message(Command("charts"))
async def cmd_charts(message: Message, db_user: dict) -> None:
    from src.utils.charts import expense_categories_pie, finance_trend_chart, goals_progress_chart

    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Генерирую графики...")
    sent = False

    trend = await finance_trend_chart(user_id)
    if trend:
        await message.answer_photo(FSInputFile(str(trend)), caption="📈 Тренд доходов/расходов")
        trend.unlink(missing_ok=True)
        sent = True

    goals_chart = await goals_progress_chart(user_id)
    if goals_chart:
        await message.answer_photo(FSInputFile(str(goals_chart)), caption="🎯 Прогресс целей")
        goals_chart.unlink(missing_ok=True)
        sent = True

    pie = await expense_categories_pie(user_id)
    if pie:
        await message.answer_photo(FSInputFile(str(pie)), caption="📊 Расходы по категориям")
        pie.unlink(missing_ok=True)
        sent = True

    if not sent:
        await processing.edit_text("Недостаточно данных для графиков.")
    else:
        await processing.delete()


# === Дневник ===

@router.message(F.text == "📝 Дневник")
async def mode_diary(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.DIARY)  # type: ignore[union-attr]
    await message.answer(
        "📝 Режим <b>Дневник</b>.\nПиши или отправь голосовое — всё сохраню и проанализирую.",
        reply_markup=main_keyboard(),
    )


# === Цели и Мечты ===

@router.message(F.text == "🎯 Цели и Мечты")
async def mode_goals(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.GOALS)
    goals = await get_active_goals(user_id)

    if not goals:
        await message.answer(
            "🎯 У тебя пока нет целей.\n"
            "Напиши новую цель или мечту — я добавлю.\n\n"
            "Пример: <i>Мечта: объездить 30 стран до 40 лет</i>",
            reply_markup=main_keyboard(),
        )
        return

    text = "🎯 <b>Цели и Мечты:</b>\n\n"
    for g in goals:
        emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}.get(g["type"], "📌")
        progress = g.get("progress_pct", 0)
        bar = _progress_bar(progress)
        text += f"{emoji} <b>{g['title']}</b>\n   {bar} {progress}%\n"

    text += "\n<i>Напиши новую цель — я добавлю.</i>"
    await message.answer(text, reply_markup=main_keyboard())


def _progress_bar(pct: int, length: int = 10) -> str:
    filled = round(pct / 100 * length)
    return "▓" * filled + "░" * (length - filled)


# === Inline-календарь ===

_DAY_ABBR = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _build_calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """Построить inline-клавиатуру-календарь для выбора даты."""
    rows: list[list[InlineKeyboardButton]] = []

    # Заголовок с навигацией
    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1

    rows.append([
        InlineKeyboardButton(text="◀", callback_data=f"cal:{prev_y}:{prev_m}"),
        InlineKeyboardButton(text=f"{_MONTH_NAMES[month]} {year}", callback_data="cal:noop"),
        InlineKeyboardButton(text="▶", callback_data=f"cal:{next_y}:{next_m}"),
    ])

    # Дни недели
    rows.append([InlineKeyboardButton(text=d, callback_data="cal:noop") for d in _DAY_ABBR])

    # Дни месяца
    cal = cal_module.monthcalendar(year, month)
    today = datetime.now(MSK).date()
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal:noop"))
            else:
                d = datetime(year, month, day).date()
                label = f"·{day}·" if d == today else str(day)
                row.append(InlineKeyboardButton(
                    text=label,
                    callback_data=f"cal_day:{d.isoformat()}",
                ))
        rows.append(row)

    # Кнопка «Назад к задачам»
    rows.append([InlineKeyboardButton(text="📋 Задачи на сегодня", callback_data="cal:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# === Кнопки быстрого доступа ===

@router.message(F.text == "➕ Цель")
async def btn_add_goal(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.GOALS)
    await message.answer(
        "✏️ Напиши цель или мечту — я добавлю.\n\n"
        "Пример: <i>Мечта: объездить 30 стран до 40 лет</i>",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📊 Графики")
async def btn_charts(message: Message, db_user: dict) -> None:
    await cmd_charts(message, db_user)


@router.message(F.text == "ℹ️ Статус")
async def btn_status(message: Message, db_user: dict) -> None:
    await cmd_status(message, db_user)


# === Задачи (Планировщик) ===

PRIORITY_EMOJI = {"low": "⬜", "normal": "🔵", "high": "🟠", "urgent": "🔴"}


def _format_task_line(t: dict) -> str:
    """Форматировать одну строку задачи."""
    check = "✅" if t["is_done"] else "⬜"
    time_str = t["due_time"].strftime("%H:%M") if t.get("due_time") else ""
    time_part = f"{time_str} — " if time_str else ""
    prio = PRIORITY_EMOJI.get(t.get("priority", "normal"), "")
    proj = f" [📁 {t['project_name']}]" if t.get("project_name") else ""
    return f"{check} {time_part}{t['task_text']}{proj} {prio}"


def _tasks_inline_keyboard(tasks: list[dict]) -> InlineKeyboardMarkup:
    """Inline-кнопки для переключения задач done/undone."""
    buttons = []
    for t in tasks:
        if t["is_done"]:
            buttons.append([InlineKeyboardButton(
                text=f"↩️ {t['task_text'][:30]}",
                callback_data=f"task_undo:{t['id']}",
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text=f"✅ {t['task_text'][:30]}",
                callback_data=f"task_done:{t['id']}",
            )])
    buttons.append([
        InlineKeyboardButton(text="➕ Добавить", callback_data="task_add"),
        InlineKeyboardButton(text="🔄 Просрочено", callback_data="task_overdue"),
        InlineKeyboardButton(text="📅 Другой день", callback_data="cal:open"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text == "📋 Задачи")
async def mode_tasks(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.TASKS)
    await _show_today_tasks(message, user_id)


async def _show_today_tasks(message: Message, user_id: int, edit: bool = False) -> None:
    """Показать задачи на сегодня (Telegram + Obsidian)."""
    today = datetime.now(MSK).strftime("%d.%m.%Y")
    tasks = await get_today_tasks(user_id)
    overdue = await get_overdue_tasks(user_id)
    obs_tasks = await get_obsidian_today_tasks(user_id)

    text = f"📋 <b>Задачи на {today}</b>\n\n"

    if not tasks and not overdue and not obs_tasks:
        text += "Задач на сегодня нет. Добавь через ➕ или напиши текст.\n"
        text += "\nКоманды:\n/task <текст> — быстро добавить\n/week — задачи на неделю"
        if edit:
            await safe_edit(message, text)
        else:
            await safe_answer(message, text, reply_markup=main_keyboard())
        return

    if overdue:
        text += f"🔴 <b>Просрочено: {len(overdue)}</b>\n\n"

    done_count = sum(1 for t in tasks if t["is_done"])
    total = len(tasks)
    text += f"Выполнено: {done_count}/{total}\n\n"

    for t in tasks:
        text += _format_task_line(t) + "\n"

    # Obsidian-задачи (не дублируются с основными)
    task_texts = {t["task_text"].strip().lower() for t in tasks}
    obs_unique = [ot for ot in obs_tasks if ot["task_text"].strip().lower() not in task_texts]
    if obs_unique:
        text += f"\n📝 <b>Из Obsidian:</b>\n"
        for ot in obs_unique:
            check = "✅" if ot["is_done"] else "⬜"
            time_str = ot["due_time"].strftime("%H:%M") if ot.get("due_time") else ""
            time_part = f"{time_str} — " if time_str else ""
            src = ot.get("source_file", "")
            src_short = src.split("/")[-1] if src else ""
            src_part = f" 📂 {src_short}" if src_short else ""
            text += f"{check} {time_part}{ot['task_text']}{src_part}\n"

    keyboard = _tasks_inline_keyboard(tasks)

    if edit:
        await safe_edit(message, text, reply_markup=keyboard)
    else:
        await safe_answer(message, text, reply_markup=keyboard)


# --- Inline callbacks для задач ---

@router.callback_query(F.data.startswith("task_done:"))
async def cb_task_done(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    task = await get_task_by_id(task_id, user_id)
    await complete_task(task_id, user_id)
    if task:
        due = task["due_date"].isoformat() if task.get("due_date") else None
        await obsidian.complete_task_in_md(task["task_text"], due_date=due)
    await callback.answer("✅ Выполнено!")
    await _show_today_tasks(callback.message, user_id, edit=True)  # type: ignore[arg-type]


@router.callback_query(F.data.startswith("task_undo:"))
async def cb_task_undo(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    task = await get_task_by_id(task_id, user_id)
    await uncomplete_task(task_id, user_id)
    if task:
        due = task["due_date"].isoformat() if task.get("due_date") else None
        await obsidian.uncomplete_task_in_md(task["task_text"], due_date=due)
    await callback.answer("↩️ Вернул в работу")
    await _show_today_tasks(callback.message, user_id, edit=True)  # type: ignore[arg-type]


@router.callback_query(F.data == "task_add")
async def cb_task_add(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    set_user_mode(user_id, Mode.ADD_TASK)
    await callback.answer()
    await callback.message.answer(  # type: ignore[union-attr]
        "✏️ Напиши задачу. Можно с датой и временем:\n\n"
        "<i>Созвон по поставкам леса завтра в 14:30</i>\n"
        "<i>Сдать отчёт до пятницы</i>\n"
        "<i>Купить продукты</i>",
        reply_markup=main_keyboard(),
    )


@router.callback_query(F.data == "task_overdue")
async def cb_task_overdue(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    overdue = await get_overdue_tasks(user_id)
    await callback.answer()

    if not overdue:
        await callback.message.answer("✅ Просроченных задач нет!")  # type: ignore[union-attr]
        return

    text = "🔴 <b>Просроченные задачи:</b>\n\n"
    buttons = []
    for t in overdue:
        date_str = t["due_date"].strftime("%d.%m") if t.get("due_date") else ""
        text += f"⬜ [{date_str}] {t['task_text']}\n"
        tomorrow = (datetime.now(MSK) + timedelta(days=1)).strftime("%Y-%m-%d")
        buttons.append([
            InlineKeyboardButton(
                text=f"📅 {t['task_text'][:20]}→завтра",
                callback_data=f"task_reschedule:{t['id']}:{tomorrow}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"task_delete:{t['id']}",
            ),
        ])

    # Кнопка «Все→завтра» одним нажатием
    if len(overdue) > 1:
        buttons.append([InlineKeyboardButton(
            text="🔄 Все→завтра",
            callback_data="task_reschedule_all_overdue",
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer(text, reply_markup=keyboard)  # type: ignore[union-attr]


@router.callback_query(F.data == "task_reschedule_all_overdue")
async def cb_reschedule_all_overdue(callback: CallbackQuery) -> None:
    """Перенести ВСЕ просроченные задачи на завтра."""
    user_id = callback.from_user.id
    overdue = await get_overdue_tasks(user_id)
    tomorrow = (datetime.now(MSK) + timedelta(days=1)).strftime("%Y-%m-%d")
    count = 0
    for t in overdue:
        await reschedule_task(t["id"], user_id, tomorrow)
        count += 1
    await callback.answer(f"📅 Перенесено: {count} задач")
    await _show_today_tasks(callback.message, user_id, edit=True)  # type: ignore[arg-type]


# --- Inline-календарь callbacks ---

@router.callback_query(F.data == "cal:open")
async def cb_calendar_open(callback: CallbackQuery) -> None:
    """Открыть inline-календарь на текущий месяц."""
    now = datetime.now(MSK)
    keyboard = _build_calendar_keyboard(now.year, now.month)
    await callback.answer()
    await safe_edit(callback.message, "📅 Выбери дату:", reply_markup=keyboard)


@router.callback_query(F.data == "cal:noop")
async def cb_calendar_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "cal:back")
async def cb_calendar_back(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    await callback.answer()
    await _show_today_tasks(callback.message, user_id, edit=True)  # type: ignore[arg-type]


@router.callback_query(F.data.regexp(r"^cal:\d{4}:\d{1,2}$"))
async def cb_calendar_navigate(callback: CallbackQuery) -> None:
    """Навигация по месяцам в inline-календаре."""
    parts = callback.data.split(":")  # type: ignore[union-attr]
    year, month = int(parts[1]), int(parts[2])
    keyboard = _build_calendar_keyboard(year, month)
    await callback.answer()
    await safe_edit(callback.message, "📅 Выбери дату:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("cal_day:"))
async def cb_calendar_day(callback: CallbackQuery) -> None:
    """Показать задачи на выбранную дату."""
    user_id = callback.from_user.id
    date_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    tasks = await get_tasks_by_date(user_id, date_str)

    display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    text = f"📅 <b>Задачи на {display}</b>\n\n"

    if not tasks:
        text += "Задач нет."
    else:
        done_count = sum(1 for t in tasks if t["is_done"])
        text += f"Выполнено: {done_count}/{len(tasks)}\n\n"
        for t in tasks:
            text += _format_task_line(t) + "\n"

    # Кнопки: назад к календарю и к задачам
    d = datetime.strptime(date_str, "%Y-%m-%d")
    buttons = [
        [InlineKeyboardButton(text="◀ Календарь", callback_data=f"cal:{d.year}:{d.month}")],
        [InlineKeyboardButton(text="📋 Задачи на сегодня", callback_data="cal:back")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.answer()
    await safe_edit(callback.message, text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("task_reschedule:"))
async def cb_task_reschedule(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    parts = callback.data.split(":")  # type: ignore[union-attr]
    task_id = int(parts[1])
    new_date = parts[2]
    await reschedule_task(task_id, user_id, new_date)
    await callback.answer("📅 Перенесено!")
    await _show_today_tasks(callback.message, user_id, edit=True)  # type: ignore[arg-type]


@router.callback_query(F.data.startswith("task_delete:"))
async def cb_task_delete(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await delete_task(task_id, user_id)
    await callback.answer("🗑 Удалено")
    await _show_today_tasks(callback.message, user_id, edit=True)  # type: ignore[arg-type]


# --- Команды задач ---

@router.message(Command("task"))
async def cmd_task(message: Message, db_user: dict) -> None:
    """Быстрое добавление задачи: /task Созвон завтра в 14:30."""
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/task", "", 1).strip()

    if not args:
        await message.answer(
            "Использование:\n"
            "<code>/task Созвон по поставкам завтра в 14:30</code>\n"
            "<code>/task Купить продукты</code>",
        )
        return

    await _parse_and_create_task(message, user_id, args)


@router.message(Command("week"))
async def cmd_week(message: Message, db_user: dict) -> None:
    """Задачи на неделю."""
    user_id = message.from_user.id  # type: ignore[union-attr]
    tasks = await get_week_tasks(user_id)

    if not tasks:
        await message.answer("📅 На этой неделе задач нет.", reply_markup=main_keyboard())
        return

    text = "📅 <b>Задачи на неделю:</b>\n\n"
    current_date = None
    day_names = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}

    for t in tasks:
        d = t.get("due_date")
        if d and d != current_date:
            current_date = d
            day_name = day_names.get(d.weekday(), "")
            text += f"\n<b>{d.strftime('%d.%m')} {day_name}</b>\n"
        text += f"  {_format_task_line(t)}\n"

    await safe_answer(message, text, reply_markup=main_keyboard())


@router.message(Command("done"))
async def cmd_done(message: Message, db_user: dict) -> None:
    """Отметить задачу выполненной: /done 5."""
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/done", "", 1).strip()

    try:
        task_id = int(args)
    except ValueError:
        await message.answer("Использование: <code>/done ID</code>")
        return

    task = await get_task_by_id(task_id, user_id)
    ok = await complete_task(task_id, user_id)
    if ok:
        if task:
            due = task["due_date"].isoformat() if task.get("due_date") else None
            await obsidian.complete_task_in_md(task["task_text"], due_date=due)
        await message.answer("✅ Задача выполнена!", reply_markup=main_keyboard())
    else:
        await message.answer("Задача не найдена или нет доступа.")


# === /weekly — еженедельный обзор (GTD-стиль) ===

@router.message(Command("weekly"))
async def cmd_weekly(message: Message, db_user: dict) -> None:
    """Еженедельный обзор: задачи, цели, финансы за неделю."""
    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Формирую еженедельный обзор...")

    from src.db.queries import get_week_summary

    summary = await get_week_summary(user_id)
    goals = await get_active_goals(user_id)
    overdue = await get_overdue_tasks(user_id)

    text = "📋 <b>ЕЖЕНЕДЕЛЬНЫЙ ОБЗОР (GTD)</b>\n\n"

    # Задачи за неделю
    text += f"✅ Выполнено за неделю: <b>{summary['completed']}</b>\n"
    text += f"➕ Создано за неделю: <b>{summary['created']}</b>\n"
    if overdue:
        text += f"🔴 Просрочено: <b>{len(overdue)}</b>\n"
    text += "\n"

    # Цели
    if goals:
        text += "🎯 <b>Прогресс по целям:</b>\n"
        for g in goals:
            pct = g.get("progress_pct", 0)
            bar = _progress_bar(pct, 8)
            emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}.get(g["type"], "📌")
            text += f"  {emoji} {g['title']} {bar} {pct}%\n"
        text += "\n"

    # Финансы за неделю
    text += f"💰 <b>Финансы за неделю:</b>\n"
    text += f"  💵 Доход: <b>{summary['week_income']:,.0f} ₽</b>\n"
    text += f"  💸 Расход: <b>{summary['week_expense']:,.0f} ₽</b>\n"
    balance = summary["week_income"] - summary["week_expense"]
    b_emoji = "✅" if balance >= 0 else "🔴"
    text += f"  {b_emoji} Баланс: <b>{balance:,.0f} ₽</b>\n\n"

    # Просроченные задачи
    if overdue:
        text += "🔴 <b>Требуют решения:</b>\n"
        for t in overdue[:5]:
            d = t["due_date"].strftime("%d.%m") if t.get("due_date") else ""
            text += f"  ⚠️ [{d}] {t['task_text']}\n"
        text += "\n"

    text += "💡 <i>Советы: пересмотри просроченные, спланируй следующую неделю, обнови прогресс целей.</i>"

    await processing.edit_text(text)


# === /repeat — создать повторяющуюся задачу ===

@router.message(Command("repeat"))
async def cmd_repeat(message: Message, db_user: dict) -> None:
    """/repeat daily Зарядка 07:00 — повторяющаяся задача."""
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/repeat", "", 1).strip()

    if not args:
        await message.answer(
            "Использование:\n"
            "<code>/repeat daily Зарядка в 07:00</code>\n"
            "<code>/repeat weekly Обзор недели</code>\n"
            "<code>/repeat monthly Оплата аренды</code>\n"
            "<code>/repeat weekdays Стендап 09:30</code>\n\n"
            "Типы: daily, weekly, monthly, weekdays",
            reply_markup=main_keyboard(),
        )
        return

    parts = args.split(maxsplit=1)
    rec_type = parts[0].lower()
    valid = {"daily", "weekly", "monthly", "weekdays"}
    if rec_type not in valid:
        await message.answer(
            f"❌ Неизвестный тип: {rec_type}\n"
            f"Допустимые: {', '.join(valid)}",
            reply_markup=main_keyboard(),
        )
        return

    task_text = parts[1] if len(parts) > 1 else ""
    if not task_text:
        await message.answer("Укажи текст задачи после типа повторения.")
        return

    today = datetime.now(MSK).strftime("%Y-%m-%d")
    prompt = TASK_PARSE_PROMPT.format(text=task_text, today=today)
    result = await chat(
        messages=[
            {"role": "system", "content": MASTER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        task_type="master_goal",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )
    parsed = _extract_json(result)
    if parsed and "task" in parsed:
        task = await create_task(
            user_id=user_id,
            task_text=parsed["task"],
            due_date=parsed.get("due_date", today),
            due_time=parsed.get("due_time"),
            priority=parsed.get("priority", "normal"),
            recurrence=rec_type,
        )
        rec_label = {
            "daily": "каждый день",
            "weekly": "каждую неделю",
            "monthly": "каждый месяц",
            "weekdays": "по будням",
        }
        await message.answer(
            f"🔄 Повторяющаяся задача: <b>{parsed['task']}</b>\n"
            f"📅 Начало: {task.get('due_date', today)}\n"
            f"🔁 Повтор: {rec_label.get(rec_type, rec_type)}",
            reply_markup=main_keyboard(),
        )
    else:
        await safe_answer(message, result, reply_markup=main_keyboard())


async def _parse_and_create_task(message: Message, user_id: int, text: str) -> None:
    """Парсинг текста задачи через LLM и создание."""
    today = datetime.now(MSK).strftime("%Y-%m-%d")

    try:
        prompt = TASK_PARSE_PROMPT.format(text=text, today=today)
        result = await chat(
            messages=[
                {"role": "system", "content": MASTER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="master_goal",
            user_id=user_id,
            bot_source=BOT_SOURCE,
        )
        parsed = _extract_json(result)
    except Exception as exc:
        logger.error("task_parse_llm_error", error=str(exc))
        parsed = None

    try:
        if not parsed or "task_text" not in parsed:
            # Fallback: создать задачу как есть на сегодня
            task = await create_task(
                user_id=user_id,
                task_text=text[:200],
                due_date=today,
            )
            await message.answer(
                f"📋 Задача добавлена: <b>{text[:200]}</b>\n📅 Сегодня",
                reply_markup=main_keyboard(),
            )
            return

        due_date = parsed.get("due_date") or today
        due_time = parsed.get("due_time")
        priority = parsed.get("priority", "normal")
        task_text = parsed["task_text"]

        task = await create_task(
            user_id=user_id,
            task_text=task_text,
            due_date=due_date,
            due_time=due_time,
            priority=priority,
        )
        await obsidian.log_task_to_daily(task_text, due_time or "", priority)

        prio_emoji = PRIORITY_EMOJI.get(priority, "")
        time_str = f" ⏰ {due_time}" if due_time else ""
        date_display = datetime.strptime(due_date, "%Y-%m-%d").strftime("%d.%m.%Y")

        await message.answer(
            f"📋 Задача добавлена: <b>{task_text}</b>\n"
            f"📅 {date_display}{time_str} {prio_emoji}",
            reply_markup=main_keyboard(),
        )
        set_user_mode(user_id, Mode.TASKS)
    except Exception as exc:
        logger.error("task_create_error", error=str(exc), user_id=user_id)
        await safe_answer(message, f"❌ Ошибка создания задачи: {exc}")


# === AI Панель — модели, бесплатные лимиты, маршрутизация ===

@router.message(F.text == "🤖 AI Панель")
async def mode_ai_panel(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.AI_PANEL)

    task_types = [
        "meal_photo", "doctor_consult", "daily_summary", "workout_parse",
        "psychology_diary", "psychology_habit",
        "family_parse", "family_receipt",
        "general_chat", "master_audit", "master_goal", "master_talk",
        "business_strategy",
    ]

    lines = []
    for tt in task_types:
        cfg = await get_model_config(tt)
        model = cfg.get("model", "gpt-4o-mini")
        lines.append(f"<code>{tt}</code> → <b>{model}</b>")

    models_text = "\n".join(lines)

    text = (
        f"🤖 <b>AI Панель</b>\n\n"
        f"📡 <b>Маршрутизация моделей:</b>\n{models_text}\n\n"
        f"Модели управляются через таблицу <code>model_routing</code> в БД."
    )

    await message.answer(text, reply_markup=main_keyboard())


# === Промпты проектов ===

@router.message(F.text == "📋 Промпты")
async def mode_prompts(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROMPTS)
    projects = await get_user_projects(user_id)

    if not projects:
        await message.answer("Нет проектов.", reply_markup=main_keyboard())
        return

    text = "📋 <b>Промпты проектов:</b>\n\n"
    for p in projects:
        meta = p.get("metadata") or {}
        prompt = meta.get("system_prompt")
        pid = p["project_id"]
        if prompt:
            short = prompt[:120] + ("…" if len(prompt) > 120 else "")
            text += f"<b>{p['name']}</b> (id={pid})\n📝 <i>{short}</i>\n\n"
        else:
            text += f"<b>{p['name']}</b> (id={pid})\n⬜ промпт не задан\n\n"

    text += (
        "Команды:\n"
        "<code>/set_prompt ID текст</code> — задать промпт\n"
        "<code>/clear_prompt ID</code> — убрать промпт"
    )
    await message.answer(text, reply_markup=main_keyboard())


@router.message(Command("set_prompt"))
async def cmd_set_prompt(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/set_prompt", "", 1).strip()

    if not args or " " not in args:
        await message.answer(
            "Использование:\n<code>/set_prompt ID текст промпта</code>\n\n"
            "Нажми 📋 Промпты — чтобы увидеть ID проектов.",
            reply_markup=main_keyboard(),
        )
        return

    first_space = args.index(" ")
    try:
        project_id = int(args[:first_space])
    except ValueError:
        await message.answer("Первый аргумент — числовой ID проекта.")
        return

    prompt_text = args[first_space + 1:].strip()
    if not prompt_text:
        await message.answer("Текст промпта не может быть пустым.")
        return

    proj = await get_project(project_id)
    if not proj or proj.get("owner_id") != user_id:
        await message.answer("Проект не найден или нет доступа.")
        return

    meta = dict(proj.get("metadata") or {})
    meta["system_prompt"] = prompt_text
    await update_project_metadata(project_id, user_id, meta)

    await message.answer(
        f"✅ Промпт для <b>{proj['name']}</b> обновлён:\n\n<i>{prompt_text[:200]}</i>",
        reply_markup=main_keyboard(),
    )


@router.message(Command("clear_prompt"))
async def cmd_clear_prompt(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/clear_prompt", "", 1).strip()

    try:
        project_id = int(args)
    except ValueError:
        await message.answer(
            "Использование: <code>/clear_prompt ID</code>",
            reply_markup=main_keyboard(),
        )
        return

    proj = await get_project(project_id)
    if not proj or proj.get("owner_id") != user_id:
        await message.answer("Проект не найден или нет доступа.")
        return

    meta = dict(proj.get("metadata") or {})
    meta.pop("system_prompt", None)
    await update_project_metadata(project_id, user_id, meta)

    await message.answer(
        f"🗑 Промпт для <b>{proj['name']}</b> удалён.",
        reply_markup=main_keyboard(),
    )


# === Проекты ===

@router.message(F.text == "⚙️ Проекты")
async def mode_projects(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROJECTS)
    projects = await get_user_projects(user_id)

    if not projects:
        await message.answer("⚙️ Нет активных проектов.", reply_markup=main_keyboard())
        return

    text = "⚙️ <b>Проекты:</b>\n\n"
    type_emoji = {
        "solo": "🏠",
        "partnership": "🤝",
        "family": "👨‍👩‍👧‍👦",
        "asset": "🏗️",
    }
    for p in projects:
        emoji = type_emoji.get(p["type"], "📁")
        collabs = len(p.get("collaborators") or [])
        collab_text = f" (+{collabs} участн.)" if collabs else ""
        text += f"{emoji} <b>{p['name']}</b> [{p['type']}]{collab_text}\n"

    await message.answer(text, reply_markup=main_keyboard())


# === Сводный отчёт (аудит) ===

@router.message(F.text == "📊 Сводный отчёт")
async def mode_report(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.REPORT)
    processing = await message.answer("⏳ Собираю данные для аудита...")

    # Финансы по всем проектам
    finances_text = await _collect_all_finances(user_id)

    # Цели
    goals = await get_active_goals(user_id)
    goals_text = ""
    for g in goals:
        goals_text += f"- [{g['type']}] {g['title']} — {g.get('progress_pct', 0)}%\n"
    if not goals_text:
        goals_text = "Целей нет."

    # Дневник (RAG — последние записи)
    diary_entries = await search(
        query="дневник настроение записи",
        user_id=user_id,
        top_k=10,
        bot_source=BOT_SOURCE,
    )
    diary_text = ""
    for d in diary_entries:
        diary_text += f"[{d.get('timestamp', '')}] {d.get('raw_text', '')[:100]}\n"
    if not diary_text:
        diary_text = "Записей нет."

    # LLM анализ
    prompt = AUDIT_PROMPT.format(
        finances=finances_text,
        goals=goals_text,
        diary=diary_text,
    )
    system = await _system_with_vision(user_id)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    result = await chat(
        messages=messages,
        task_type="master_audit",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    await processing.edit_text(f"📊 <b>Сводный отчёт</b>\n\n{result}")
    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Финансовая панорама (SQL only) ===

@router.message(F.text == "💰 Финансовая панорама")
async def mode_panorama(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PANORAMA)
    processing = await message.answer("⏳ Собираю финансовую панораму...")

    text = PANORAMA_HEADER
    projects = await get_user_projects(user_id)

    if not projects:
        await processing.edit_text(text + "Нет проектов с финансами.")
        return

    grand_income = 0.0
    grand_expense = 0.0

    type_emoji = {
        "solo": "🏠",
        "partnership": "🤝",
        "family": "👨‍👩‍👧‍👦",
        "asset": "🏗️",
    }

    for proj in projects:
        summary = await get_finance_summary(proj["project_id"])
        if not summary:
            continue

        emoji = type_emoji.get(proj["type"], "📁")
        text += f"\n{emoji} <b>{proj['name']}</b>\n"

        proj_income = 0.0
        proj_expense = 0.0

        for row in summary:
            total = float(row.get("total", 0))
            if row.get("transaction_type") == "income":
                proj_income += total
            else:
                proj_expense += total

        text += f"  💵 Доход: {proj_income:,.0f} ₽\n"
        text += f"  💰 Расход: {proj_expense:,.0f} ₽\n"
        balance = proj_income - proj_expense
        b_emoji = "✅" if balance >= 0 else "🔴"
        text += f"  {b_emoji} Баланс: {balance:,.0f} ₽\n"

        grand_income += proj_income
        grand_expense += proj_expense

    # Итого
    grand_balance = grand_income - grand_expense
    g_emoji = "✅" if grand_balance >= 0 else "🔴"
    text += (
        f"\n{'━' * 25}\n"
        f"<b>ИТОГО ПО ВСЕЙ ЖИЗНИ:</b>\n"
        f"💵 Доход: <b>{grand_income:,.0f} ₽</b>\n"
        f"💰 Расход: <b>{grand_expense:,.0f} ₽</b>\n"
        f"{g_emoji} Баланс: <b>{grand_balance:,.0f} ₽</b>"
    )

    await processing.edit_text(text)


# === /add_goal ===

@router.message(Command("add_goal"))
async def cmd_add_goal(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/add_goal", "").strip()

    if not args:
        await message.answer(
            "Использование:\n"
            "/add_goal Мечта: объездить 30 стран\n"
            "/add_goal Цель: выучить Python до конца года\n"
            "/add_goal Привычка: бегать 3 раза в неделю",
        )
        return

    # LLM парсинг типа цели
    prompt = GOAL_ADD_PROMPT.format(text=args)
    result = await chat(
        messages=[
            {"role": "system", "content": MASTER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        task_type="master_goal",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    parsed = _extract_json(result)
    if parsed and "title" in parsed:
        goal_type = parsed.get("type", "yearly_goal")
        await create_goal(
            user_id=user_id,
            goal_type=goal_type,
            title=parsed["title"],
            description=parsed.get("description", ""),
        )

        emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}.get(goal_type, "📌")
        await message.answer(
            f"{emoji} Цель добавлена: <b>{parsed['title']}</b>\n"
            f"Тип: {goal_type}",
            reply_markup=main_keyboard(),
        )
        # Обновить Goals Dashboard в Obsidian
        goals = await get_active_goals(user_id)
        await obsidian.update_goals_dashboard(goals)
    else:
        await safe_answer(message, result, reply_markup=main_keyboard())


# === /progress — обновить прогресс цели ===

@router.message(Command("progress"))
async def cmd_progress(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/progress", "").strip()

    if not args:
        await message.answer(
            "Использование: /progress <ID цели> <процент>\n"
            "Пример: /progress 1 50",
        )
        return

    parts = args.split()
    if len(parts) < 2:
        await message.answer("Укажи ID цели и процент. Пример: /progress 1 50")
        return

    goal_id = int(parts[0])
    pct = min(100, max(0, int(parts[1])))

    update_data: dict = {"progress_pct": pct}
    if pct >= 100:
        from datetime import datetime, timezone
        update_data["status"] = "achieved"
        update_data["achieved_at"] = datetime.now(timezone.utc)

    await update_goal(goal_id, user_id, **update_data)

    # Обновить Goals Dashboard в Obsidian
    goals = await get_active_goals(user_id)
    await obsidian.update_goals_dashboard(goals)

    emoji = "🎉" if pct >= 100 else "📈"
    await message.answer(
        f"{emoji} Прогресс обновлён: <b>{pct}%</b>",
        reply_markup=main_keyboard(),
    )


# === Голосовое ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Транскрибирую...")
    text = await transcribe_voice(bot=bot, voice=message.voice, user_id=user_id, bot_source=BOT_SOURCE)
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

    if mode == Mode.ADD_TASK:
        # Добавление задачи через текст
        set_user_mode(user_id, Mode.TASKS)
        await _parse_and_create_task(message, user_id, text)
        return

    if mode == Mode.GOALS:
        # Добавление цели через текст
        prompt = GOAL_ADD_PROMPT.format(text=text)
        result = await chat(
            messages=[
                {"role": "system", "content": MASTER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="master_goal",
            user_id=user_id,
            bot_source=BOT_SOURCE,
        )
        parsed = _extract_json(result)
        if parsed and "title" in parsed:
            goal_type = parsed.get("type", "yearly_goal")
            await create_goal(
                user_id=user_id,
                goal_type=goal_type,
                title=parsed["title"],
                description=parsed.get("description", ""),
            )
            emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}.get(goal_type, "📌")
            await message.answer(
                f"{emoji} Добавлено: <b>{parsed['title']}</b>",
                reply_markup=main_keyboard(),
            )
            # Обновить Goals Dashboard в Obsidian
            goals_list = await get_active_goals(user_id)
            await obsidian.update_goals_dashboard(goals_list)
        else:
            await safe_answer(message, result, reply_markup=main_keyboard())
        return

    if mode == Mode.DIARY:
        # Запись в дневник + анализ
        event = await create_event(
            user_id=user_id,
            event_type="diary",
            bot_source=BOT_SOURCE,
            raw_text=text,
        )
        await store_event_embedding(event["id"], text, user_id, BOT_SOURCE)

    # Проактивный режим: сверяем с целями
    system = await _system_with_vision(user_id)
    messages = await build_messages(
        user_id=user_id,
        bot_source=BOT_SOURCE,
        system_prompt=system,
        user_text=text,
    )
    result = await chat(
        messages=messages,
        task_type="master_talk",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    await safe_answer(message, result, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Вспомогательные ===

async def _collect_all_finances(user_id: int) -> str:
    """Собрать текстовый отчёт по всем проектам для LLM-аудита."""
    projects = await get_user_projects(user_id)
    lines = []

    for proj in projects:
        summary = await get_finance_summary(proj["project_id"])
        if not summary:
            continue

        income = sum(float(r["total"]) for r in summary if r["transaction_type"] == "income")
        expense = sum(float(r["total"]) for r in summary if r["transaction_type"] == "expense")
        lines.append(f"{proj['name']} [{proj['type']}]: доход {income:,.0f} ₽, расход {expense:,.0f} ₽")

    return "\n".join(lines) if lines else "Финансовых данных нет."


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
