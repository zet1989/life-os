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
from aiogram.types import CallbackQuery, FSInputFile, Message, PhotoSize
from src.utils.telegram import safe_answer, safe_edit

from src.ai.router import chat
from src.ai.vision import analyze_photo
from src.ai.whisper import transcribe_voice
from src.core.context import save_assistant_reply
from src.db.queries import (
    create_finance,
    create_project,
    delete_finance,
    get_finance_summary,
    get_finances_for_export,
    get_month_finance_by_category,
    get_projects_by_type,
    get_recent_finances,
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


async def _ensure_family_project(user_id: int) -> list[dict]:
    """Получить семейные проекты, создать если нет ни одного."""
    projects = await get_projects_by_type(user_id, "family")
    if not projects:
        proj = await create_project(
            user_id, "Семейный бюджет", project_type="family",
        )
        logger.info("auto_created_family_project", user_id=user_id, project_id=proj["project_id"])
        projects = [proj]
    return projects


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
    projects = await _ensure_family_project(user_id)

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
    projects = await _ensure_family_project(user_id)

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


# === 📉 Графики ===

@router.message(F.text == "📉 Графики")
async def mode_charts(message: Message, db_user: dict) -> None:
    from src.utils.charts import balance_trend_chart, expense_categories_pie, weekly_expense_chart

    user_id = message.from_user.id  # type: ignore[union-attr]
    set_user_mode(user_id, Mode.CHARTS)
    projects = await _ensure_family_project(user_id)
    project_id = projects[0]["project_id"]

    processing = await message.answer("📉 Генерирую графики...")

    charts_sent = 0

    # 1. Расходы по неделям
    chart_path = await weekly_expense_chart(project_id)
    if chart_path:
        await message.answer_photo(FSInputFile(str(chart_path)), caption="📊 Расходы и доходы по неделям")
        chart_path.unlink(missing_ok=True)
        charts_sent += 1

    # 2. Тренд баланса
    chart_path = await balance_trend_chart(user_id, project_id)
    if chart_path:
        await message.answer_photo(FSInputFile(str(chart_path)), caption="📈 Тренд баланса")
        chart_path.unlink(missing_ok=True)
        charts_sent += 1

    # 3. Расходы по категориям (pie)
    chart_path = await expense_categories_pie(user_id, project_id)
    if chart_path:
        await message.answer_photo(FSInputFile(str(chart_path)), caption="🥧 Расходы по категориям")
        chart_path.unlink(missing_ok=True)
        charts_sent += 1

    if charts_sent == 0:
        await processing.edit_text("📉 Недостаточно данных для графиков. Добавьте расходы и доходы.")
    else:
        await processing.delete()



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
            "Использование: /del <ID транзакции>\n"
            "Узнать ID: /last",
            reply_markup=main_keyboard(),
        )
        return

    finance_id = int(args)
    ok = await delete_finance(finance_id, user_id)
    if ok:
        await message.answer(f"✅ Транзакция #{finance_id} удалена.", reply_markup=main_keyboard())
    else:
        await message.answer(f"❌ Транзакция #{finance_id} не найдена или нет доступа.", reply_markup=main_keyboard())


# === /export_csv — экспорт финансов в CSV ===

@router.message(Command("export_csv"))
async def cmd_export_csv(message: Message, db_user: dict) -> None:
    """Скачать все финансовые записи в CSV."""
    import csv
    import tempfile
    from pathlib import Path

    user_id = message.from_user.id  # type: ignore[union-attr]
    rows = await get_finances_for_export(user_id)

    if not rows:
        await message.answer("Нет финансовых записей для экспорта.", reply_markup=main_keyboard())
        return

    # Генерируем CSV
    tmp = Path(tempfile.mktemp(suffix=".csv"))
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["ID", "Дата", "Тип", "Сумма", "Категория", "Описание", "Проект"])
        for r in rows:
            ts = r["timestamp"]
            date_str = ts.strftime("%d.%m.%Y %H:%M") if hasattr(ts, "strftime") else str(ts)
            tx_type = "Доход" if r["transaction_type"] == "income" else "Расход"
            writer.writerow([
                r["id"],
                date_str,
                tx_type,
                f"{float(r['amount']):.2f}",
                r.get("category", ""),
                r.get("description", ""),
                r.get("project_name", ""),
            ])

    doc = FSInputFile(str(tmp), filename=f"finances_{user_id}.csv")
    await message.answer_document(doc, caption=f"📊 Экспорт финансов: {len(rows)} записей")
    tmp.unlink(missing_ok=True)


# === /budget — план vs факт по бюджету ===

@router.message(Command("budget"))
async def cmd_budget(message: Message, db_user: dict) -> None:
    """Бюджет на месяц: план vs факт по категориям."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    user_id = message.from_user.id  # type: ignore[union-attr]
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    projects = await _ensure_family_project(user_id)
    project = projects[0]
    project_id = project["project_id"]

    # Лимиты из metadata
    from src.db.queries import get_project
    proj = await get_project(project_id)
    limits = (proj.get("metadata") or {}).get("limits", {})

    # Факт за текущий месяц
    facts = await get_month_finance_by_category(project_id, now.year, now.month)
    expense_facts: dict[str, float] = {}
    total_income = 0.0
    total_expense = 0.0
    for r in facts:
        amount = float(r["total"])
        if r["transaction_type"] == "expense":
            expense_facts[r["category"]] = amount
            total_expense += amount
        else:
            total_income += amount

    month_names = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    text = f"📋 <b>Бюджет: {month_names[now.month]} {now.year}</b>\n\n"

    if limits:
        text += "📊 <b>План vs Факт (расходы):</b>\n\n"
        total_plan = sum(limits.values())
        for cat, plan in sorted(limits.items(), key=lambda x: x[1], reverse=True):
            fact = expense_facts.get(cat, 0)
            pct = round(fact / plan * 100) if plan > 0 else 0
            if pct >= 100:
                bar_emoji = "🔴"
            elif pct >= 80:
                bar_emoji = "🟡"
            else:
                bar_emoji = "🟢"
            filled = min(10, round(pct / 10))
            bar = "▓" * filled + "░" * (10 - filled)
            text += f"{bar_emoji} <b>{cat}</b>\n"
            text += f"   {bar} {fact:,.0f} / {plan:,.0f} ₽ ({pct}%)\n"

        text += f"\n📊 Итого план: <b>{total_plan:,.0f} ₽</b>\n"
        text += f"💸 Итого факт: <b>{total_expense:,.0f} ₽</b>\n"
        remaining = total_plan - total_expense
        r_emoji = "✅" if remaining >= 0 else "🔴"
        text += f"{r_emoji} Остаток: <b>{remaining:,.0f} ₽</b>\n"
    else:
        text += "⚠️ Лимиты бюджета не заданы.\n\n"
        if expense_facts:
            text += "<b>Факт расходов за месяц:</b>\n"
            for cat, amt in sorted(expense_facts.items(), key=lambda x: x[1], reverse=True):
                text += f"  💰 {cat}: <b>{amt:,.0f} ₽</b>\n"

        text += (
            "\n💡 Чтобы задать бюджет, обнови metadata проекта:\n"
            '<code>{"limits": {"продукты": 40000, "транспорт": 15000}}</code>'
        )

    text += f"\n💵 Доход за месяц: <b>{total_income:,.0f} ₽</b>"
    text += f"\n💰 Расход за месяц: <b>{total_expense:,.0f} ₽</b>"
    balance = total_income - total_expense
    b_emoji = "✅" if balance >= 0 else "🔴"
    text += f"\n{b_emoji} Баланс: <b>{balance:,.0f} ₽</b>"

    await message.answer(text, reply_markup=main_keyboard())


# === /forecast — прогноз расходов на конец месяца ===

@router.message(Command("forecast"))
async def cmd_forecast(message: Message, db_user: dict) -> None:
    """Прогноз расходов до конца месяца на основе текущего темпа."""
    from calendar import monthrange
    from datetime import datetime
    from zoneinfo import ZoneInfo

    user_id = message.from_user.id  # type: ignore[union-attr]
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    day_of_month = now.day
    days_in_month = monthrange(now.year, now.month)[1]
    days_remaining = days_in_month - day_of_month

    projects = await _ensure_family_project(user_id)
    project_id = projects[0]["project_id"]

    facts = await get_month_finance_by_category(project_id, now.year, now.month)

    total_expense = 0.0
    total_income = 0.0
    cat_expenses: dict[str, float] = {}
    for r in facts:
        amount = float(r["total"])
        if r["transaction_type"] == "expense":
            total_expense += amount
            cat_expenses[r["category"]] = amount
        else:
            total_income += amount

    if total_expense == 0 and total_income == 0:
        await message.answer(
            "📈 Нет данных за текущий месяц для прогноза.",
            reply_markup=main_keyboard(),
        )
        return

    # Средний расход в день и прогноз
    daily_avg = total_expense / max(day_of_month, 1)
    projected_total = total_expense + daily_avg * days_remaining

    month_names = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]

    text = (
        f"📈 <b>Прогноз расходов: {month_names[now.month]} {now.year}</b>\n\n"
        f"📅 День {day_of_month} из {days_in_month} (осталось {days_remaining})\n\n"
        f"💸 Потрачено: <b>{total_expense:,.0f} ₽</b>\n"
        f"📊 Средний темп: <b>{daily_avg:,.0f} ₽/день</b>\n"
        f"🔮 Прогноз на месяц: <b>{projected_total:,.0f} ₽</b>\n"
    )

    # Сравнение с бюджетными лимитами
    from src.db.queries import get_project
    proj = await get_project(project_id)
    limits = (proj.get("metadata") or {}).get("limits", {})
    if limits:
        total_limit = sum(limits.values())
        diff = total_limit - projected_total
        if diff >= 0:
            text += f"\n✅ Вписываетесь в бюджет ({total_limit:,.0f} ₽), запас <b>{diff:,.0f} ₽</b>"
        else:
            text += f"\n🔴 Перерасход! Бюджет {total_limit:,.0f} ₽, превышение <b>{-diff:,.0f} ₽</b>"

        # Прогноз по категориям с превышением
        overruns = []
        for cat, limit in sorted(limits.items()):
            fact = cat_expenses.get(cat, 0)
            cat_daily = fact / max(day_of_month, 1)
            cat_projected = fact + cat_daily * days_remaining
            if cat_projected > limit:
                overruns.append(
                    f"  🔴 {cat}: {cat_projected:,.0f} / {limit:,.0f} ₽ "
                    f"(+{cat_projected - limit:,.0f})"
                )
        if overruns:
            text += "\n\n⚠️ <b>Категории с превышением:</b>\n" + "\n".join(overruns)
    else:
        text += "\n💡 Задайте бюджетные лимиты через /budget для сравнения с планом."

    if total_income > 0:
        projected_balance = total_income - projected_total
        b_emoji = "✅" if projected_balance >= 0 else "🔴"
        text += f"\n\n💵 Доход: <b>{total_income:,.0f} ₽</b>"
        text += f"\n{b_emoji} Прогноз баланса: <b>{projected_balance:,.0f} ₽</b>"

    await message.answer(text, reply_markup=main_keyboard())


# === /history — историческая аналитика ===

@router.message(Command("history"))
async def cmd_history(message: Message, db_user: dict) -> None:
    """Сравнение расходов за несколько месяцев."""
    from src.db.queries import get_monthly_totals

    user_id = message.from_user.id  # type: ignore[union-attr]
    projects = await _ensure_family_project(user_id)
    project_id = projects[0]["project_id"]

    rows = await get_monthly_totals(project_id, months=6)

    if not rows:
        await message.answer(
            "📊 Недостаточно данных для аналитики.\n"
            "Нужны расходы хотя бы за 1 месяц.",
            reply_markup=main_keyboard(),
        )
        return

    month_names = [
        "", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
    ]

    # Собираем данные по месяцам
    months_data: dict[str, dict[str, float]] = {}
    for r in rows:
        key = f"{month_names[r['month']]} {r['year']}"
        if key not in months_data:
            months_data[key] = {"expense": 0, "income": 0}
        months_data[key][r["transaction_type"]] += float(r["total"])

    text = "📊 <b>Историческая аналитика (до 6 мес)</b>\n\n"

    prev_expense = None
    for month_label, data in months_data.items():
        expense = data["expense"]
        income = data["income"]
        balance = income - expense
        b_emoji = "✅" if balance >= 0 else "🔴"

        text += f"<b>{month_label}:</b>\n"
        text += f"  💸 Расход: {expense:,.0f} ₽"
        if prev_expense is not None and prev_expense > 0:
            change = ((expense - prev_expense) / prev_expense) * 100
            c_emoji = "📈" if change > 0 else "📉"
            text += f"  {c_emoji} {change:+.0f}%"
        text += f"\n  💵 Доход: {income:,.0f} ₽\n"
        text += f"  {b_emoji} Баланс: {balance:,.0f} ₽\n\n"
        prev_expense = expense

    # Итоги
    total_exp = sum(d["expense"] for d in months_data.values())
    total_inc = sum(d["income"] for d in months_data.values())
    n_months = len(months_data)
    avg_exp = total_exp / n_months if n_months > 0 else 0
    avg_inc = total_inc / n_months if n_months > 0 else 0

    text += (
        f"📈 <b>Средние значения:</b>\n"
        f"  💸 Расход/мес: {avg_exp:,.0f} ₽\n"
        f"  💵 Доход/мес: {avg_inc:,.0f} ₽"
    )

    await message.answer(text, reply_markup=main_keyboard())


# === Callback: выбор проекта ===

@router.callback_query(F.data.startswith("fam:"))
async def cb_project_select(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")  # type: ignore[union-attr]
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
        projects = await _ensure_family_project(user_id)
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
        await safe_edit(processing, result)

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

    if mode in (Mode.SETTINGS, Mode.REPORT, Mode.CATEGORIES, Mode.CHARTS):
        return

    transaction_type = "expense" if mode == Mode.EXPENSE else "income"
    projects = await _ensure_family_project(user_id)

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
