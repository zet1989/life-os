"""Reply- и Inline-клавиатуры бота Family."""

from enum import StrEnum

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

_user_modes: dict[int, "Mode"] = {}

# Временное хранилище pending-текста
_pending_text: dict[int, tuple[str, str]] = {}  # user_id → (text, transaction_type)


class Mode(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    REPORT = "report"
    CATEGORIES = "categories"
    CHARTS = "charts"
    SETTINGS = "settings"
    DEBTS = "debts"
    ADVISOR = "advisor"


def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="💰 Расход"), KeyboardButton(text="💵 Доход")],
        [KeyboardButton(text="📊 Отчёт"), KeyboardButton(text="📈 Категории")],
        [KeyboardButton(text="📉 Графики"), KeyboardButton(text="💳 Долги")],
        [KeyboardButton(text="🧠 Советник"), KeyboardButton(text="⚙️ Настройки")],
    ]
    from src.bots.hub.keyboard import is_unified, MENU_BUTTON_TEXT
    if is_unified():
        rows.append([KeyboardButton(text=MENU_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def projects_inline(projects: list[dict], action: str = "select") -> InlineKeyboardMarkup:
    """Инлайн-кнопки с family-проектами."""
    buttons = []
    for p in projects:
        buttons.append([
            InlineKeyboardButton(
                text=p["name"],
                callback_data=f"fam:{action}:{p['project_id']}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.EXPENSE)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode


def set_pending(user_id: int, text: str, transaction_type: str) -> None:
    _pending_text[user_id] = (text, transaction_type)


def pop_pending(user_id: int) -> tuple[str, str] | None:
    return _pending_text.pop(user_id, None)
