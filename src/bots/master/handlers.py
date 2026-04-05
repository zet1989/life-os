"""Хэндлеры бота Master Intelligence — главный пульт Life OS.

Доступ: только admin (Алексей). Это центр управления всей экосистемой.
Хранитель Видения: перед каждым ответом — goals в system prompt.
Финансовая панорама: агрегация ВСЕХ финансов (SQL only).
Перекрёстный RAG: доступ ко всем ботам.
"""

import json

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from src.ai.rag import rag_answer, search, store_event_embedding
from src.ai.router import chat
from src.ai.whisper import transcribe_voice
from src.core.context import build_messages, save_assistant_reply
from src.db.queries import (
    create_event,
    create_goal,
    get_active_goals,
    get_finance_summary,
    get_user_projects,
    update_goal,
)
from src.bots.master.keyboard import (
    Mode,
    get_user_mode,
    main_keyboard,
    set_user_mode,
)
from src.bots.master.prompts import (
    AUDIT_PROMPT,
    GOAL_ADD_PROMPT,
    MASTER_SYSTEM,
    PANORAMA_HEADER,
    PROACTIVE_PROMPT,
    VISION_CONTEXT,
)

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "master"


# === Хранитель Видения: goals → system prompt ===

async def _system_with_vision(user_id: int) -> str:
    """Добавить активные цели в system prompt."""
    goals = await get_active_goals(user_id)

    if not goals:
        return MASTER_SYSTEM + "\n\nУ пользователя пока нет целей."

    goals_text = ""
    for g in goals:
        emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}.get(g["type"], "📌")
        progress = g.get("progress_pct", 0)
        goals_text += f"{emoji} [{g['type']}] {g['title']} — {progress}%\n"

    return MASTER_SYSTEM + VISION_CONTEXT.format(goals=goals_text)


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
    else:
        await message.answer(result, reply_markup=main_keyboard())


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
        else:
            await message.answer(result, reply_markup=main_keyboard())
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

    await message.answer(result, reply_markup=main_keyboard())
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
