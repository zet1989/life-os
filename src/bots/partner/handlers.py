"""Хэндлеры бота Partner — операционный учёт бизнес-партнёрства.

Поддерживает групповые чаты (privacy mode: @mention / reply).
Работает с partnership-проектами через collaborators.
"""

import json
import re

import structlog
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.ai.router import chat
from src.utils.telegram import safe_answer
from src.ai.whisper import transcribe_voice
from src.core.context import save_assistant_reply
from src.db.queries import (
    add_collaborator,
    archive_project,
    create_finance,
    create_project,
    delete_finance,
    get_finance_summary,
    get_projects_by_type,
    get_recent_finances,
)
from src.bots.partner.keyboard import (
    Mode,
    get_user_mode,
    main_keyboard,
    pop_pending,
    projects_inline,
    set_pending,
    set_user_mode,
)
from src.bots.partner.prompts import (
    EXPENSE_PROMPT,
    INCOME_PROMPT,
    PARTNER_SYSTEM,
    REPORT_HEADER,
)

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "partner"


# === Privacy mode: в группах реагируем только на @mention или reply ===

def _is_group(message: Message) -> bool:
    return message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def _is_addressed_to_bot(message: Message, bot_info) -> bool:
    """Проверяет, что сообщение адресовано боту (mention или reply)."""
    # Reply на сообщение бота
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == bot_info.id:
            return True

    # @mention в тексте
    text = message.text or message.caption or ""
    if bot_info.username and f"@{bot_info.username}" in text:
        return True

    return False


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    await message.answer(
        f"Привет, {name}! 🤝\n"
        f"Я бот для учёта партнёрских проектов.\n\n"
        f"📉 Расход — записать расход\n"
        f"📈 Доход — записать доход\n"
        f"📁 Проекты — управление проектами\n"
        f"📊 Отчёт — финансовая сводка",
        reply_markup=main_keyboard(),
    )


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
    project = await create_project(user_id, name, project_type="partnership")
    await message.answer(
        f"✅ Партнёрский проект <b>{project['name']}</b> создан (ID: {project['project_id']}).",
        reply_markup=main_keyboard(),
    )


# === /add_partner <project_id> <telegram_id> ===

@router.message(Command("add_partner"))
async def cmd_add_partner(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").split()
    if len(args) < 3:
        await message.answer(
            "Использование: <code>/add_partner PROJECT_ID TELEGRAM_ID</code>",
            reply_markup=main_keyboard(),
        )
        return

    try:
        project_id = int(args[1])
        partner_id = int(args[2])
    except ValueError:
        await message.answer("ID должны быть числами.", reply_markup=main_keyboard())
        return

    ok = await add_collaborator(project_id, user_id, partner_id)
    if ok:
        await message.answer(
            f"✅ Партнёр {partner_id} добавлен в проект {project_id}.",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(
            "❌ Ошибка: ты не владелец проекта или проект не найден.",
            reply_markup=main_keyboard(),
        )


# === /archive_project ===

@router.message(Command("archive_project"))
async def cmd_archive_project(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    projects = await get_projects_by_type(user_id, "partnership")
    if not projects:
        await message.answer("Нет активных партнёрских проектов.", reply_markup=main_keyboard())
        return

    await message.answer(
        "Выбери проект для архивации:",
        reply_markup=projects_inline(projects, action="archive"),
    )


# === Reply-клавиатура ===

@router.message(F.text == "📉 Расход")
async def mode_expense(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.EXPENSE)  # type: ignore[union-attr]
    await message.answer(
        "📉 Режим <b>Расход</b>.\nНапиши или надиктуй расход.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📈 Доход")
async def mode_income(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.INCOME)  # type: ignore[union-attr]
    await message.answer(
        "📈 Режим <b>Доход</b>.\nНапиши или надиктуй доход.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📁 Проекты")
async def mode_projects(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.PROJECTS)
    projects = await get_projects_by_type(user_id, "partnership")

    if not projects:
        await message.answer(
            "Нет активных партнёрских проектов.\n"
            "Создай: <code>/add_project Название</code>",
            reply_markup=main_keyboard(),
        )
        return

    text = "📁 <b>Партнёрские проекты:</b>\n\n"
    for p in projects:
        collab_count = len(p.get("collaborators") or [])
        text += f"• <b>{p['name']}</b> (ID: {p['project_id']}, партнёров: {collab_count})\n"
    text += "\nКоманды:\n/add_project — создать\n/add_partner — добавить партнёра\n/archive_project — архивировать"

    await message.answer(text, reply_markup=main_keyboard())


@router.message(F.text == "➕ Новый проект")
async def mode_add_project(message: Message, db_user: dict) -> None:
    set_user_mode(message.from_user.id, Mode.ADD_PROJECT)  # type: ignore[union-attr]
    await message.answer(
        "✏️ Напиши название нового партнёрского проекта:",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📊 Отчёт")
async def mode_report(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.REPORT)
    projects = await get_projects_by_type(user_id, "partnership")

    if not projects:
        await message.answer("Нет проектов для отчёта.", reply_markup=main_keyboard())
        return

    await message.answer(
        "Выбери проект для финансового отчёта:",
        reply_markup=projects_inline(projects, action="report"),
    )


# === /last — последние транзакции ===

@router.message(Command("last"))
async def cmd_last_transactions(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    txns = await get_recent_finances(user_id, limit=10)
    if not txns:
        await message.answer("Нет транзакций.", reply_markup=main_keyboard())
        return

    lines = ["📋 <b>Последние 10 транзакций:</b>\n"]
    for tx in txns:
        emoji = "🔴" if tx["transaction_type"] == "expense" else "🟢"
        ts = tx["timestamp"]
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%d.%m %H:%M")
        desc = tx.get("description") or tx.get("category", "")
        lines.append(
            f"{emoji} <code>#{tx['id']}</code> {ts} — {tx['amount']:,.0f} ₽ ({desc})"
        )
    lines.append("\n🗑 Удалить: /del <code>ID</code>")
    await message.answer("\n".join(lines), reply_markup=main_keyboard())


# === /del — удалить транзакцию ===

@router.message(Command("del"))
async def cmd_delete_transaction(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    args = (message.text or "").replace("/del", "").strip()
    if not args or not args.isdigit():
        await message.answer(
            "Использование: /del <ID транзакции>\nУзнать ID: /last",
            reply_markup=main_keyboard(),
        )
        return

    finance_id = int(args)
    ok = await delete_finance(finance_id, user_id)
    if ok:
        await message.answer(f"✅ Транзакция #{finance_id} удалена.", reply_markup=main_keyboard())
    else:
        await message.answer(f"❌ Транзакция #{finance_id} не найдена или нет доступа.", reply_markup=main_keyboard())


# === Callback: выбор проекта ===

@router.callback_query(F.data.startswith("ptr:"))
async def cb_project_action(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")  # type: ignore[union-attr]
    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    action = parts[1]
    project_id = int(parts[2])
    user_id = callback.from_user.id

    if action in ("select_exp", "select_inc"):
        await _attach_finance(callback, user_id, project_id)
    elif action == "report":
        await _send_report(callback, project_id)
    elif action == "archive":
        await _do_archive(callback, user_id, project_id)


async def _attach_finance(callback: CallbackQuery, user_id: int, project_id: int) -> None:
    """Привязать pending расход/доход к проекту."""
    pending = pop_pending(user_id)
    if not pending:
        await callback.answer("Нет текста для привязки")
        return

    text, transaction_type = pending
    prompt = EXPENSE_PROMPT if transaction_type == "expense" else INCOME_PROMPT

    messages = [
        {"role": "system", "content": PARTNER_SYSTEM + "\n\n" + prompt},
        {"role": "user", "content": text},
    ]
    result = await chat(
        messages=messages,
        task_type="financial_parse",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    parsed = _extract_json(result)
    if parsed and "amount" in parsed:
        await create_finance(
            user_id=user_id,
            project_id=project_id,
            transaction_type=transaction_type,
            amount=parsed["amount"],
            category=parsed.get("category", "other"),
            description=parsed.get("description"),
        )
        emoji = "📉" if transaction_type == "expense" else "📈"
        confirm = (
            f"{emoji} Записано: <b>{parsed['amount']:,.0f} ₽</b>\n"
            f"Категория: {parsed.get('category', '—')}\n"
            f"Описание: {parsed.get('description', '—')}"
        )
        await callback.answer("✅ Записано")
        if callback.message:
            await callback.message.answer(confirm, reply_markup=main_keyboard())  # type: ignore[union-attr]
    else:
        await callback.answer("⚠️ Не удалось распарсить")
        if callback.message:
            cleaned = re.sub(r'```json\s*\{.*?\}\s*```', '', result, flags=re.DOTALL).strip()
            cleaned = re.sub(r'\{[^{}]*"amount"\s*:.*?\}', '', cleaned, flags=re.DOTALL).strip()
            await callback.message.answer(cleaned or "⚠️ Не удалось распознать сумму. Попробуй ещё раз.", reply_markup=main_keyboard())  # type: ignore[union-attr]

    await save_assistant_reply(user_id, BOT_SOURCE, result)


async def _send_report(callback: CallbackQuery, project_id: int) -> None:
    """Финансовый отчёт — строго через SQL."""
    summary = await get_finance_summary(project_id, user_id=callback.from_user.id)

    if not summary:
        await callback.answer("Нет финансовых данных")
        if callback.message:
            await callback.message.answer(  # type: ignore[union-attr]
                "📊 По этому проекту пока нет финансовых записей.",
                reply_markup=main_keyboard(),
            )
        return

    text = REPORT_HEADER.format(project_name=f"ID {project_id}")
    income_total = 0.0
    expense_total = 0.0

    for row in summary:
        tt = row.get("transaction_type", "")
        cat = row.get("category", "—")
        total = float(row.get("total", 0))

        if tt == "income":
            income_total += total
            emoji = "📈"
        else:
            expense_total += total
            emoji = "📉"

        text += f"{emoji} {cat}: <b>{total:,.0f} ₽</b>\n"

    profit = income_total - expense_total
    profit_emoji = "✅" if profit >= 0 else "🔴"

    text += f"\n💰 Доходы: <b>{income_total:,.0f} ₽</b>\n"
    text += f"💸 Расходы: <b>{expense_total:,.0f} ₽</b>\n"
    text += f"{profit_emoji} Прибыль: <b>{profit:,.0f} ₽</b>"

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
        await callback.answer("Ошибка: ты не владелец проекта")


# === Голосовое ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
    # Privacy mode
    if _is_group(message):
        bot_info = await bot.get_me()
        if not _is_addressed_to_bot(message, bot_info):
            return

    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Транскрибирую...")
    text = await transcribe_voice(bot=bot, voice=message.voice, user_id=user_id, bot_source=BOT_SOURCE)
    await processing.edit_text(f"🎤 <i>{text}</i>\n\n⏳ Обрабатываю...")
    await _process_input(message, user_id, text)


# === Текст ===

@router.message(F.text)
async def handle_text(message: Message, bot: Bot, db_user: dict) -> None:
    # Privacy mode
    if _is_group(message):
        bot_info = await bot.get_me()
        if not _is_addressed_to_bot(message, bot_info):
            return
        # Убираем @mention из текста
        text = (message.text or "").replace(f"@{bot_info.username}", "").strip()
    else:
        text = message.text or ""

    user_id = message.from_user.id  # type: ignore[union-attr]
    try:
        await message.bot.send_chat_action(user_id, "typing")  # type: ignore[union-attr]
    except Exception:
        pass
    await _process_input(message, user_id, text)


# === Обработка ввода ===

async def _process_input(message: Message, user_id: int, text: str) -> None:
    mode = get_user_mode(user_id)

    if mode == Mode.ADD_PROJECT:
        name = text.strip()
        if not name:
            await message.answer("Название не может быть пустым.", reply_markup=main_keyboard())
            return
        project = await create_project(user_id, name, project_type="partnership")
        set_user_mode(user_id, Mode.EXPENSE)
        await message.answer(
            f"✅ Партнёрский проект <b>{project['name']}</b> создан (ID: {project['project_id']}).",
            reply_markup=main_keyboard(),
        )
        return

    if mode == Mode.PROJECTS:
        # Свободный текст в режиме проектов — игнорируем
        return

    if mode == Mode.REPORT:
        # В режиме отчёта — показываем проекты
        projects = await get_projects_by_type(user_id, "partnership")
        if projects:
            await message.answer(
                "Выбери проект для отчёта:",
                reply_markup=projects_inline(projects, action="report"),
            )
        return

    # Расход / Доход — привязываем к проекту
    transaction_type = "expense" if mode == Mode.EXPENSE else "income"
    projects = await get_projects_by_type(user_id, "partnership")

    if not projects:
        await message.answer(
            "Сначала создай проект: <code>/add_project Название</code>",
            reply_markup=main_keyboard(),
        )
        return

    action = "select_exp" if transaction_type == "expense" else "select_inc"

    if len(projects) == 1:
        # Один проект — привязываем автоматически
        set_pending(user_id, text, transaction_type)
        await _attach_finance_direct(message, user_id, projects[0]["project_id"], text, transaction_type)
    else:
        # Несколько — показываем выбор
        set_pending(user_id, text, transaction_type)
        await message.answer(
            "К какому проекту отнести?",
            reply_markup=projects_inline(projects, action=action),
        )


async def _attach_finance_direct(
    message: Message,
    user_id: int,
    project_id: int,
    text: str,
    transaction_type: str,
) -> None:
    """Привязать расход/доход напрямую (один проект)."""
    pop_pending(user_id)

    prompt = EXPENSE_PROMPT if transaction_type == "expense" else INCOME_PROMPT
    messages = [
        {"role": "system", "content": PARTNER_SYSTEM + "\n\n" + prompt},
        {"role": "user", "content": text},
    ]
    result = await chat(
        messages=messages,
        task_type="financial_parse",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    parsed = _extract_json(result)
    if parsed and "amount" in parsed:
        await create_finance(
            user_id=user_id,
            project_id=project_id,
            transaction_type=transaction_type,
            amount=parsed["amount"],
            category=parsed.get("category", "other"),
            description=parsed.get("description"),
        )
        emoji = "📉" if transaction_type == "expense" else "📈"
        confirm = (
            f"{emoji} Записано: <b>{parsed['amount']:,.0f} ₽</b>\n"
            f"Категория: {parsed.get('category', '—')}\n"
            f"Описание: {parsed.get('description', '—')}"
        )
        await message.answer(confirm, reply_markup=main_keyboard())
    else:
        cleaned = re.sub(r'```json\s*\{.*?\}\s*```', '', result, flags=re.DOTALL).strip()
        cleaned = re.sub(r'\{[^{}]*"amount"\s*:.*?\}', '', cleaned, flags=re.DOTALL).strip()
        await safe_answer(message, cleaned or "⚠️ Не удалось распознать сумму. Попробуй ещё раз.", reply_markup=main_keyboard())

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
