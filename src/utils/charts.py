"""Генерация PNG-графиков трендов через matplotlib.

Отправка прямо в Telegram-чат: КБЖУ, расходы, прогресс целей.
"""

import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import structlog

from src.db.queries import get_active_goals, get_expense_data, get_finance_data

logger = structlog.get_logger()


async def finance_trend_chart(user_id: int, project_id: int | None = None) -> Path | None:
    """Тренд расходов/доходов по дням."""
    rows = await get_finance_data(user_id, project_id)
    if not rows:
        return None

    daily_income: dict[str, float] = defaultdict(float)
    daily_expense: dict[str, float] = defaultdict(float)

    for row in rows:
        day = str(row["timestamp"])[:10]
        if row["transaction_type"] == "income":
            daily_income[day] += float(row["amount"])
        else:
            daily_expense[day] += float(row["amount"])

    all_days = sorted(set(daily_income.keys()) | set(daily_expense.keys()))
    dates = [datetime.strptime(d, "%Y-%m-%d") for d in all_days]
    incomes = [daily_income.get(d, 0) for d in all_days]
    expenses = [daily_expense.get(d, 0) for d in all_days]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(dates, incomes, color="#2ecc71", alpha=0.8, label="Доход")
    ax.bar(dates, [-e for e in expenses], color="#e74c3c", alpha=0.8, label="Расход")
    ax.axhline(y=0, color="gray", linewidth=0.5)
    ax.set_title("Тренд доходов и расходов", fontsize=14)
    ax.set_ylabel("₽")
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    fig.autofmt_xdate()
    plt.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="finance-trend-", delete=False)
    fig.savefig(tmp.name, dpi=150)
    plt.close(fig)

    return Path(tmp.name)


async def goals_progress_chart(user_id: int) -> Path | None:
    """Вертикальная диаграмма прогресса целей."""
    goals = await get_active_goals(user_id)
    if not goals:
        return None

    titles = [g["title"][:25] for g in goals]
    progress = [g.get("progress_pct", 0) for g in goals]

    colors = []
    for g in goals:
        t = g.get("type", "")
        if t == "dream":
            colors.append("#9b59b6")
        elif t == "yearly_goal":
            colors.append("#3498db")
        else:
            colors.append("#2ecc71")

    fig, ax = plt.subplots(figsize=(8, max(3, len(goals) * 0.7)))
    bars = ax.barh(titles, progress, color=colors, alpha=0.85)

    for bar, pct in zip(bars, progress):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{pct}%", va="center", fontsize=10)

    ax.set_xlim(0, 110)
    ax.set_xlabel("Прогресс %")
    ax.set_title("Прогресс целей", fontsize=14)
    ax.invert_yaxis()
    plt.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="goals-progress-", delete=False)
    fig.savefig(tmp.name, dpi=150)
    plt.close(fig)

    return Path(tmp.name)


async def expense_categories_pie(user_id: int, project_id: int | None = None) -> Path | None:
    """Круговая диаграмма расходов по категориям."""
    rows = await get_expense_data(user_id, project_id)
    if not rows:
        return None

    by_cat: dict[str, float] = defaultdict(float)
    for row in rows:
        by_cat[row.get("category", "прочее")] += float(row["amount"])

    # Топ-8, остальное → «Прочее»
    sorted_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
    labels = []
    sizes = []
    for cat, amt in sorted_cats[:8]:
        labels.append(cat)
        sizes.append(amt)
    rest = sum(amt for _, amt in sorted_cats[8:])
    if rest > 0:
        labels.append("Прочее")
        sizes.append(rest)

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
    ax.set_title("Расходы по категориям", fontsize=14)
    plt.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="expense-pie-", delete=False)
    fig.savefig(tmp.name, dpi=150)
    plt.close(fig)

    return Path(tmp.name)
