"""Хэндлеры бота Family — семейный бюджет.

Доступ: Алексей (admin) и жена (wife, permissions.bots includes "family").
Работает с family-проектами через collaborators.
Поддерживает групповые чаты (privacy mode).
"""

import json

import structlog
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, PhotoSize

from src.ai.router import chat
from src.ai.vision import analyze_photo
from src.ai.whisper import transcribe_voice
from src.core.context import save_assistant_reply
from src.db.queries import (
    create_finance,
    get_finance_summary,
    get_projects_by_type,
)
from src.bots.family.keyboard import (
    Mode,
    get_user_mode,
    main_keyboard,
    pop_pending,
    projects_inline,
    set_pending,
    set_user_mode,
)
from src.bots.family.prompts import (
    EXPENSE_PROMPT,
    FAMILY_SYSTEM,
    INCOME_PROMPT,
    RECEIPT_PROMPT,
    REPORT_HEADER,
)

logger = structlog.get_logger()
router = Router()

BOT_SOURCE = "family"


# === Privacy mode: в группах реагируем только на @mention или reply ===

def _is_group(message: Message) -> bool:
    return message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def _is_addressed_to_bot(message: Message, bot_info) -> bool:
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == bot_info.id:
            return True
    text = message.text or message.caption or ""
    if bot_info.username and f"@{bot_info.username}" in text:
        return True
    return False


# === /start ===

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    name = db_user.get("display_name") or message.from_user.first_name  # type: ignore[union-attr]
    await message.answer(
        f"Привет, {name}! 👨‍👩‍👧‍👦\n"
        f"Я твой семейный бухгалтер.\n\n"
        f"💰 Расход — записать трату\n"
        f"💵 Доход — записать доход\n"
        f"📊 Отчёт — сводка за период\n"
        f"📈 Категории — куда уходят деньги\n"
        f"⚙️ Настройки — бюджетные лимиты\n\n"
        f"Также можно просто отправить фото чека!",
        reply_markup=main_keyboard(),
    )


# === Reply-клавиатура ===

@router.message(F.text == "💰 Расход")
async def mode_expense(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.EXPENSE)  # type: ignore[union-attr]
    await message.answer(
        "💰 Режим <b>Расход</b>.\n"
        "Напиши, надиктуй или отправь фото чека.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "💵 Доход")
async def mode_income(message: Message) -> None:
    set_user_mode(message.from_user.id, Mode.INCOME)  # type: ignore[union-attr]
    await message.answer(
        "💵 Режим <b>Доход</b>.\nНапиши или надиктуй доход.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "📊 Отчёт")
async def mode_report(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.REPORT)
    projects = await get_projects_by_type(user_id, "family")

    if not projects:
        await message.answer("Нет семейных проектов.", reply_markup=main_keyboard())
        return

    if len(projects) == 1:
        await _send_report(message, projects[0]["project_id"], projects[0]["name"])
    else:
        await message.answer(
            "Выбери проект для отчёта:",
            reply_markup=projects_inline(projects, action="report"),
        )


@router.message(F.text == "📈 Категории")
async def mode_categories(message: Message, db_user: dict) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.CATEGORIES)
    projects = await get_projects_by_type(user_id, "family")

    if not projects:
        await message.answer("Нет семейных проектов.", reply_markup=main_keyboard())
        return

    if len(projects) == 1:
        await _send_categories(message, projects[0]["project_id"])
    else:
        await message.answer(
            "Выбери проект:",
            reply_markup=projects_inline(projects, action="categories"),
        )


@router.message(F.text == "⚙️ Настройки")
async def mode_settings(message: Message, db_user: dict) -> None:
    set_user_mode(message.from_user.id, Mode.SETTINGS)  # type: ignore[union-attr]
    await message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "Бюджетные лимиты задаются в metadata семейного проекта.\n"
        "Пока управляется через БД. В будущем — через чат.",
        reply_markup=main_keyboard(),
    )


# === Callback: выбор проекта ===

@router.callback_query(F.data.startswith("fam:"))
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
        await callback.answer("Формирую отчёт...")
        if callback.message:
            await _send_report(callback.message, project_id)  # type: ignore[arg-type]
    elif action == "categories":
        await callback.answer("Считаю...")
        if callback.message:
            await _send_categories(callback.message, project_id)  # type: ignore[arg-type]


async def _attach_finance(callback: CallbackQuery, user_id: int, project_id: int) -> None:
    """Привязать pending расход/доход к проекту."""
    pending = pop_pending(user_id)
    if not pending:
        await callback.answer("Нет текста для привязки")
        return

    text, transaction_type = pending
    prompt = EXPENSE_PROMPT if transaction_type == "expense" else INCOME_PROMPT

    messages = [
        {"role": "system", "content": FAMILY_SYSTEM + "\n\n" + prompt},
        {"role": "user", "content": text},
    ]
    result = await chat(
        messages=messages,
        task_type="family_parse",
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
            category=parsed.get("category", "прочее"),
            description=parsed.get("description"),
        )
        emoji = "💰" if transaction_type == "expense" else "💵"
        confirm = (
            f"{emoji} Записано: <b>{parsed['amount']:,.0f} ₽</b>\n"
            f"Категория: {parsed.get('category', '—')}\n"
            f"Описание: {parsed.get('description', '—')}"
        )
        # Проверка лимитов
        limit_warning = await _check_budget_limit(project_id, parsed.get("category", ""))
        if limit_warning:
            confirm += f"\n\n{limit_warning}"

        await callback.answer("✅ Записано")
        if callback.message:
            await callback.message.answer(confirm, reply_markup=main_keyboard())  # type: ignore[union-attr]
    else:
        await callback.answer("⚠️ Не удалось распарсить")
        if callback.message:
            await callback.message.answer(result, reply_markup=main_keyboard())  # type: ignore[union-attr]

    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Отчёт за период (SQL only) ===

async def _send_report(message: Message, project_id: int, project_name: str = "Семейный бюджет") -> None:
    summary = await get_finance_summary(project_id)

    if not summary:
        await message.answer(
            "📊 Пока нет финансовых записей.",
            reply_markup=main_keyboard(),
        )
        return

    text = REPORT_HEADER.format(period="всё время")
    income_total = 0.0
    expense_total = 0.0

    income_lines = []
    expense_lines = []

    for row in summary:
        tt = row.get("transaction_type", "")
        cat = row.get("category", "—")
        total = float(row.get("total", 0))

        if tt == "income":
            income_total += total
            income_lines.append(f"  💵 {cat}: <b>{total:,.0f} ₽</b>")
        else:
            expense_total += total
            expense_lines.append(f"  💰 {cat}: <b>{total:,.0f} ₽</b>")

    if income_lines:
        text += "<b>Доходы:</b>\n" + "\n".join(income_lines) + "\n\n"
    if expense_lines:
        text += "<b>Расходы:</b>\n" + "\n".join(expense_lines) + "\n\n"

    balance = income_total - expense_total
    balance_emoji = "✅" if balance >= 0 else "🔴"

    text += f"💵 Всего доходов: <b>{income_total:,.0f} ₽</b>\n"
    text += f"💰 Всего расходов: <b>{expense_total:,.0f} ₽</b>\n"
    text += f"{balance_emoji} Баланс: <b>{balance:,.0f} ₽</b>"

    await message.answer(text, reply_markup=main_keyboard())


# === Топ категорий (SQL only) ===

async def _send_categories(message: Message, project_id: int) -> None:
    summary = await get_finance_summary(project_id)

    if not summary:
        await message.answer("📈 Пока нет данных.", reply_markup=main_keyboard())
        return

    # Собираем только расходы, сортируем по убыванию
    expenses = [
        (row.get("category", "—"), float(row.get("total", 0)))
        for row in summary
        if row.get("transaction_type") == "expense"
    ]
    expenses.sort(key=lambda x: x[1], reverse=True)

    if not expenses:
        await message.answer("📈 Расходов пока нет.", reply_markup=main_keyboard())
        return

    total = sum(amt for _, amt in expenses)
    text = "📈 <b>Куда уходят деньги:</b>\n\n"

    medals = ["🥇", "🥈", "🥉"]
    for i, (cat, amt) in enumerate(expenses):
        pct = (amt / total * 100) if total > 0 else 0
        medal = medals[i] if i < 3 else f"{i + 1}."
        text += f"{medal} {cat}: <b>{amt:,.0f} ₽</b> ({pct:.0f}%)\n"

    text += f"\n💰 Всего расходов: <b>{total:,.0f} ₽</b>"

    await message.answer(text, reply_markup=main_keyboard())


# === Проверка бюджетных лимитов ===

async def _check_budget_limit(project_id: int, category: str) -> str | None:
    """Проверить, не превышен ли лимит по категории.

    Лимиты хранятся в projects.metadata.limits: {"продукты": 40000, ...}
    """
    from src.db.queries import get_project

    proj = await get_project(project_id)
    if not proj:
        return None

    limits = (proj.get("metadata") or {}).get("limits", {})
    limit = limits.get(category)
    if limit is None:
        return None

    # Текущая сумма расходов по категории (за текущий месяц приблизительно — весь период)
    summary = await get_finance_summary(project_id)
    current = 0.0
    for row in summary:
        if row.get("transaction_type") == "expense" and row.get("category") == category:
            current = float(row.get("total", 0))
            break

    if current >= limit:
        return f"🔴 <b>Лимит превышен!</b> {category}: {current:,.0f} / {limit:,.0f} ₽"
    elif current >= limit * 0.8:
        return f"⚠️ <b>Приближение к лимиту!</b> {category}: {current:,.0f} / {limit:,.0f} ₽"

    return None


# === Фото (чеки) ===

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, db_user: dict) -> None:
    if _is_group(message):
        bot_info = await bot.get_me()
        if not _is_addressed_to_bot(message, bot_info):
            return

    user_id = message.from_user.id  # type: ignore[union-attr]
    processing = await message.answer("⏳ Распознаю чек...")

    photo: PhotoSize = message.photo[-1]  # type: ignore[index]
    result = await analyze_photo(
        bot=bot,
        photo=photo,
        prompt=RECEIPT_PROMPT,
        task_type="family_receipt",
        user_id=user_id,
        bot_source=BOT_SOURCE,
    )

    parsed = _extract_json(result)
    if parsed and "amount" in parsed:
        # Привязываем к family-проекту
        projects = await get_projects_by_type(user_id, "family")
        if projects:
            project_id = projects[0]["project_id"]
            await create_finance(
                user_id=user_id,
                project_id=project_id,
                transaction_type="expense",
                amount=parsed["amount"],
                category=parsed.get("category", "продукты"),
                description=parsed.get("description", parsed.get("shop", "")),
            )
            confirm = (
                f"🧾 Чек распознан!\n"
                f"💰 Сумма: <b>{parsed['amount']:,.0f} ₽</b>\n"
                f"Категория: {parsed.get('category', '—')}\n"
                f"Магазин: {parsed.get('shop', '—')}"
            )
            limit_warning = await _check_budget_limit(project_id, parsed.get("category", ""))
            if limit_warning:
                confirm += f"\n\n{limit_warning}"
            await processing.edit_text(confirm)
        else:
            await processing.edit_text("Нет семейных проектов для записи расхода.")
    else:
        await processing.edit_text(result)

    await save_assistant_reply(user_id, BOT_SOURCE, result)


# === Голосовое ===

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, db_user: dict) -> None:
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
    if _is_group(message):
        bot_info = await bot.get_me()
        if not _is_addressed_to_bot(message, bot_info):
            return
        text = (message.text or "").replace(f"@{bot_info.username}", "").strip()
    else:
        text = message.text or ""

    user_id = message.from_user.id  # type: ignore[union-attr]
    await _process_input(message, user_id, text)


# === Обработка ввода ===

async def _process_input(message: Message, user_id: int, text: str) -> None:
    mode = get_user_mode(user_id)

    if mode in (Mode.SETTINGS, Mode.REPORT, Mode.CATEGORIES):
        return

    transaction_type = "expense" if mode == Mode.EXPENSE else "income"
    projects = await get_projects_by_type(user_id, "family")

    if not projects:
        await message.answer(
            "Нет семейных проектов. Попроси админа создать.",
            reply_markup=main_keyboard(),
        )
        return

    if len(projects) == 1:
        set_pending(user_id, text, transaction_type)
        await _attach_finance_direct(message, user_id, projects[0]["project_id"], text, transaction_type)
    else:
        action = "select_exp" if transaction_type == "expense" else "select_inc"
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
        {"role": "system", "content": FAMILY_SYSTEM + "\n\n" + prompt},
        {"role": "user", "content": text},
    ]
    result = await chat(
        messages=messages,
        task_type="family_parse",
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
            category=parsed.get("category", "прочее"),
            description=parsed.get("description"),
        )
        emoji = "💰" if transaction_type == "expense" else "💵"
        confirm = (
            f"{emoji} Записано: <b>{parsed['amount']:,.0f} ₽</b>\n"
            f"Категория: {parsed.get('category', '—')}\n"
            f"Описание: {parsed.get('description', '—')}"
        )
        limit_warning = await _check_budget_limit(project_id, parsed.get("category", ""))
        if limit_warning:
            confirm += f"\n\n{limit_warning}"
        await message.answer(confirm, reply_markup=main_keyboard())
    else:
        await message.answer(result, reply_markup=main_keyboard())

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
