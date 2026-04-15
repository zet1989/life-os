"""Хэндлеры бота Mentor — стратегический AI бизнес-коуч.

Работает с partnership-проектами через collaborators.
Оба партнёра видят одни и те же проекты.
"""

import json

import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.ai.rag import rag_answer, search, store_event_embedding
from src.ai.router import chat
from src.utils.telegram import safe_answer
from src.ai.whisper import transcribe_voice
from src.core.context import save_assistant_reply
from src.db.queries import (
    create_event,
    get_finance_summary,
    get_project,
    get_project_events,
    get_projects_by_type,
)
from src.bots.mentor.keyboard import (
    Mode,
    get_user_mode,
    main_keyboard,
    pop_pending,
    projects_inline,
    set_pending,
    set_user_mode,
)
from src.bots.mentor.prompts import (
    ASK_PROMPT,
    DISCUSSION_PROMPT,
    IDEA_COMPARE_PROMPT,
    IDEA_PROMPT,
    MENTOR_SYSTEM,
    REPORT_HEADER,
    REPORT_PROMPT,
    STRATEGY_PROMPT,
)
from src.integrations.obsidian.writer import obsidian

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "mentor"


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    await message.answer(
        f"Привет, {name}! 🧠\n"
        f"Я твой бизнес-ментор.\n\n"
        f"💡 Идея — запиши и получи анализ\n"
        f"🎙 Обсуждение — отправь аудио встречи\n"
        f"📊 Аналитика — финансовая стратегия\n"
        f"📁 Проекты — список проектов\n"
        f"❓ Спросить — поиск по базе знаний",
        reply_markup=main_keyboard(),
    )


# === Reply-клавиатура ===

@router.message(F.text == "💡 Идея")
async def mode_idea(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.IDEA)  # type: ignore[union-attr]
    await message.answer(
        "💡 Режим <b>Идея</b>.\n"
        "Напиши или надиктуй бизнес-идею — я проанализирую потенциал "
        "и сопоставлю с прошлыми записями.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🎙 Обсуждение")
async def mode_discussion(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.DISCUSSION)  # type: ignore[union-attr]
    await message.answer(
        "🎙 Режим <b>Обсуждение</b>.\n"
        "Отправь аудиозапись встречи/созвона — я сделаю саммари, "
        "выделю решения и экшен-айтемы.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📊 Аналитика")
async def mode_analytics(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.ANALYTICS)
    projects = await get_projects_by_type(user_id, "partnership")

    if not projects:
        await message.answer("Нет партнёрских проектов.", reply_markup=main_keyboard())
        return

    await message.answer(
        "📊 Выбери проект для финансовой стратегии:",
        reply_markup=projects_inline(projects, action="analytics"),
    )


@router.message(F.text == "📁 Проекты")
async def mode_projects(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROJECTS)
    projects = await get_projects_by_type(user_id, "partnership")

    if not projects:
        await message.answer(
            "Нет активных партнёрских проектов.\n"
            "Создай через бота Partner: <code>/add_project</code>",
            reply_markup=main_keyboard(),
        )
        return

    text = "📁 <b>Партнёрские проекты:</b>\n\n"
    for p in projects:
        text += f"• <b>{p['name']}</b> (ID: {p['project_id']})\n"
    text += "\n📊 Для отчёта за период — нажми проект:"

    await message.answer(
        text,
        reply_markup=projects_inline(projects, action="report"),
    )


@router.message(F.text == "❓ Спросить")
async def mode_ask(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.ASK)  # type: ignore[union-attr]
    await message.answer(
        "❓ Режим <b>Спросить</b>.\n"
        "Задай вопрос — я найду ответ в базе идей, обсуждений и решений.",
        reply_markup=main_keyboard(),
    )


# === Callback: выбор проекта ===

@router.callback_query(F.data.startswith("mnt:"))
async def cb_project_action(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")  # type: ignore[union-attr]
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    action = parts[1]
    project_id = int(parts[2])
    user_id = callback.from_user.id

    if action == "select":
        await _attach_idea_to_project(callback, user_id, project_id)
    elif action == "select_disc":
        await _attach_discussion_to_project(callback, user_id, project_id)
    elif action == "analytics":
        await _send_strategy(callback, user_id, project_id)
    elif action == "report":
        await _send_report(callback, user_id, project_id)


# === Привязка идеи к проекту ===

async def _attach_idea_to_project(
    callback: CallbackQuery, user_id: int, project_id: int,
) -> None:
    text = pop_pending(user_id)
    if not text:
        await callback.answer("Нет текста для привязки")
        return

    await callback.answer("⏳ Анализирую...")

    # 1. Ищем похожие идеи в RAG (по project_id)
    similar = await search(query=text, user_id=user_id, top_k=3, project_id=project_id)
    context_text = "\n".join(
        f"- {r.get('raw_text', '')[:200]}" for r in similar if r.get("raw_text")
    )

    # 2. Если есть похожие — сопоставляем
    if context_text:
        compare_prompt = IDEA_COMPARE_PROMPT.format(context=context_text, idea=text)
        messages = [
            {"role": "system", "content": MENTOR_SYSTEM},
            {"role": "user", "content": compare_prompt},
        ]
    else:
        messages = [
            {"role": "system", "content": MENTOR_SYSTEM + "\n\n" + IDEA_PROMPT},
            {"role": "user", "content": text},
        ]

    result = await chat(
        messages=messages,
        task_type="mentor_idea",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    # 3. Сохраняем в events + RAG
    json_data = _extract_json(result)
    event = await create_event(
        user_id=user_id,
        event_type="business_idea",
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
        project_id=project_id,
    )
    await store_event_embedding(event["id"], text, user_id=user_id, bot_source=BOT_SOURCE)
    await obsidian.log_idea(text, source="mentor")

    # Обновить Project README в Obsidian
    proj = await get_project(project_id)
    if proj:
        fin = await get_finance_summary(project_id)
        evts = await get_project_events(project_id, limit=10)
        await obsidian.update_project_readme(proj, fin, evts)

    if callback.message:
        await callback.message.answer(result, reply_markup=main_keyboard())  # type: ignore[union-attr]
    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Привязка обсуждения к проекту ===

async def _attach_discussion_to_project(
    callback: CallbackQuery, user_id: int, project_id: int,
) -> None:
    transcript = pop_pending(user_id)
    if not transcript:
        await callback.answer("Нет транскрипции")
        return

    await callback.answer("⏳ Анализирую обсуждение...")

    prompt = DISCUSSION_PROMPT.format(transcript=transcript)
    messages = [
        {"role": "system", "content": MENTOR_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    result = await chat(
        messages=messages,
        task_type="mentor_discussion",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    # Сохраняем транскрипцию + анализ
    event = await create_event(
        user_id=user_id,
        event_type="discussion",
        bot_source=BOT_SOURCE,
        raw_text=transcript,
        json_data={"analysis": result[:2000]},
        project_id=project_id,
    )
    await store_event_embedding(event["id"], transcript, user_id=user_id, bot_source=BOT_SOURCE)

    # Обновить Project README в Obsidian
    proj = await get_project(project_id)
    if proj:
        fin = await get_finance_summary(project_id)
        evts = await get_project_events(project_id, limit=10)
        await obsidian.update_project_readme(proj, fin, evts)
        # Создать Meeting Note в Obsidian
        await obsidian.log_meeting_note(
            project_name=proj.get("name", "Unknown"),
            transcript=transcript,
            analysis=result,
        )

    if callback.message:
        await callback.message.answer(result, reply_markup=main_keyboard())  # type: ignore[union-attr]
    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Финансовая стратегия ===

async def _send_strategy(
    callback: CallbackQuery, user_id: int, project_id: int,
) -> None:
    await callback.answer("⏳ Анализирую финансы...")

    summary = await get_finance_summary(project_id)
    if not summary:
        if callback.message:
            await callback.message.answer(  # type: ignore[union-attr]
                "📊 По этому проекту пока нет финансовых данных.",
                reply_markup=main_keyboard(),
            )
        return

    # Формируем текст из SQL-данных для LLM
    finance_lines = []
    income_total = 0.0
    expense_total = 0.0
    for row in summary:
        tt = row.get("transaction_type", "")
        cat = row.get("category", "—")
        total = float(row.get("total", 0))
        if tt == "income":
            income_total += total
        else:
            expense_total += total
        finance_lines.append(f"{tt}: {cat} = {total:,.0f} ₽")

    finance_lines.append(f"\nИТОГО доходы: {income_total:,.0f} ₽")
    finance_lines.append(f"ИТОГО расходы: {expense_total:,.0f} ₽")
    finance_lines.append(f"ПРИБЫЛЬ: {income_total - expense_total:,.0f} ₽")

    finance_data = "\n".join(finance_lines)

    prompt = STRATEGY_PROMPT.format(finance_data=finance_data)
    messages = [
        {"role": "system", "content": MENTOR_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    result = await chat(
        messages=messages,
        task_type="mentor_strategy",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    if callback.message:
        await callback.message.answer(result, reply_markup=main_keyboard())  # type: ignore[union-attr]
    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Отчёт за период ===

async def _send_report(
    callback: CallbackQuery, user_id: int, project_id: int,
) -> None:
    await callback.answer("⏳ Формирую отчёт...")

    # 1. Финансы из SQL
    summary = await get_finance_summary(project_id)
    if summary:
        finance_lines = []
        income_total = 0.0
        expense_total = 0.0
        for row in summary:
            tt = row.get("transaction_type", "")
            cat = row.get("category", "—")
            total = float(row.get("total", 0))
            if tt == "income":
                income_total += total
            else:
                expense_total += total
            finance_lines.append(f"{tt}: {cat} = {total:,.0f} ₽")
        finance_lines.append(f"\nДоходы: {income_total:,.0f} ₽")
        finance_lines.append(f"Расходы: {expense_total:,.0f} ₽")
        finance_lines.append(f"Прибыль: {income_total - expense_total:,.0f} ₽")
        finance_data = "\n".join(finance_lines)
    else:
        finance_data = "Финансовых данных нет."

    # 2. Ключевые записи из RAG
    rag_results = await search(
        query="ключевые решения идеи обсуждения",
        user_id=user_id,
        top_k=5,
        project_id=project_id,
    )
    rag_context = "\n".join(
        f"- [{r.get('event_type', '')}] {r.get('raw_text', '')[:200]}"
        for r in rag_results if r.get("raw_text")
    ) or "Записей нет."

    # 3. LLM генерирует отчёт
    prompt = REPORT_PROMPT.format(finance_data=finance_data, rag_context=rag_context)
    messages = [
        {"role": "system", "content": MENTOR_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    result = await chat(
        messages=messages,
        task_type="mentor_report",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    if callback.message:
        await callback.message.answer(result, reply_markup=main_keyboard())  # type: ignore[union-attr]
    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Голосовое ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    mode = get_user_mode(user_id)

    processing = await message.answer("⏳ Транскрибирую...")
    transcript = await transcribe_voice(
        bot=bot, voice=message.voice, user_id=user_id, bot_source=BOT_SOURCE,
    )

    if mode == Mode.DISCUSSION:
        await processing.edit_text(
            f"🎤 Транскрипция ({len(transcript)} символов)\n\n"
            f"<i>{transcript[:300]}{'...' if len(transcript) > 300 else ''}</i>\n\n"
            f"Выбери проект для привязки:"
        )
        set_pending(user_id, transcript)
        projects = await get_projects_by_type(user_id, "partnership")
        if projects:
            await message.answer(
                "К какому проекту отнести обсуждение?",
                reply_markup=projects_inline(projects, action="select_disc"),
            )
        else:
            await message.answer("Нет партнёрских проектов.", reply_markup=main_keyboard())
    else:
        # Идея или вопрос — обрабатываем как текст
        await processing.edit_text(f"🎤 <i>{transcript}</i>\n\n⏳ Обрабатываю...")
        await _process_input(message, user_id, transcript)


# === Текст ===

@router.message(F.text)
async def handle_text(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    text = message.text or ""
    try:
        await message.bot.send_chat_action(user_id, "typing")  # type: ignore[union-attr]
    except Exception:
        pass
    await _process_input(message, user_id, text)


# === Обработка ввода ===

async def _process_input(message: Message, user_id: int, text: str) -> None:
    mode = get_user_mode(user_id)

    if mode == Mode.ASK:
        await _process_question(message, user_id, text)
        return

    if mode in (Mode.PROJECTS, Mode.ANALYTICS):
        # В этих режимах текст — это вопрос
        await _process_question(message, user_id, text)
        return

    if mode == Mode.DISCUSSION:
        # Текстовое сообщение в режиме обсуждения — обрабатываем как заметку
        set_pending(user_id, text)
        projects = await get_projects_by_type(user_id, "partnership")
        if projects:
            await message.answer(
                "К какому проекту отнести?",
                reply_markup=projects_inline(projects, action="select_disc"),
            )
        else:
            await message.answer("Нет партнёрских проектов.", reply_markup=main_keyboard())
        return

    # Режим IDEA — привязываем к проекту
    projects = await get_projects_by_type(user_id, "partnership")
    if not projects:
        await message.answer(
            "Нет партнёрских проектов.\n"
            "Создай через бота Partner: <code>/add_project</code>",
            reply_markup=main_keyboard(),
        )
        return

    if len(projects) == 1:
        set_pending(user_id, text)
        await _attach_idea_direct(message, user_id, projects[0]["project_id"], text)
    else:
        set_pending(user_id, text)
        await message.answer(
            "К какому проекту отнести идею?",
            reply_markup=projects_inline(projects, action="select"),
        )


async def _attach_idea_direct(
    message: Message, user_id: int, project_id: int, text: str,
) -> None:
    """Привязать идею напрямую (один проект)."""
    pop_pending(user_id)

    # Ищем похожие
    similar = await search(query=text, user_id=user_id, top_k=3, project_id=project_id)
    context_text = "\n".join(
        f"- {r.get('raw_text', '')[:200]}" for r in similar if r.get("raw_text")
    )

    if context_text:
        compare_prompt = IDEA_COMPARE_PROMPT.format(context=context_text, idea=text)
        messages = [
            {"role": "system", "content": MENTOR_SYSTEM},
            {"role": "user", "content": compare_prompt},
        ]
    else:
        messages = [
            {"role": "system", "content": MENTOR_SYSTEM + "\n\n" + IDEA_PROMPT},
            {"role": "user", "content": text},
        ]

    result = await chat(
        messages=messages,
        task_type="mentor_idea",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    json_data = _extract_json(result)
    event = await create_event(
        user_id=user_id,
        event_type="business_idea",
        bot_source=BOT_SOURCE,
        raw_text=text,
        json_data=json_data,
        project_id=project_id,
    )
    await store_event_embedding(event["id"], text, user_id=user_id, bot_source=BOT_SOURCE)

    # Обновить Project README в Obsidian
    proj = await get_project(project_id)
    if proj:
        fin = await get_finance_summary(project_id)
        evts = await get_project_events(project_id, limit=10)
        await obsidian.update_project_readme(proj, fin, evts)

    await safe_answer(message, result, reply_markup=main_keyboard())
    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _process_question(message: Message, user_id: int, query: str) -> None:
    """RAG-поиск по идеям, обсуждениям, решениям."""
    result = await rag_answer(
        query=query,
        user_id=user_id,
        system_prompt=(
            MENTOR_SYSTEM + "\n\n"
            "Отвечай на вопрос пользователя по базе знаний (идеи, обсуждения, решения). "
            "Если данных нет — скажи об этом."
        ),
        top_k=5,
        bot_source=BOT_SOURCE,
    )
    await safe_answer(message, result, reply_markup=main_keyboard())
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
