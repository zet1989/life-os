"""Reply-клавиатура и режимы бота Health."""

from enum import StrEnum

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# In-memory store режимов (per-user). При перезапуске сбрасывается — ОК.
_user_modes: dict[int, "Mode"] = {}


class Mode(StrEnum):
    FOOD = "food"
    WORKOUT = "workout"
    DOCTOR = "doctor"
    PROFILE = "profile"
    WATER = "water"
    WEIGHT = "weight"
    WATCH = "watch"


def main_keyboard() -> ReplyKeyboardMarkup:
    """Основная Reply-клавиатура бота Health."""
    rows = [
        [KeyboardButton(text="🍽 Еда"), KeyboardButton(text="🏋️ Тренировка")],
        [KeyboardButton(text="💧 Вода"), KeyboardButton(text="⚖️ Вес")],
        [KeyboardButton(text="🩺 Доктор"), KeyboardButton(text="⌚ Часы")],
        [KeyboardButton(text="� Лекарства"), KeyboardButton(text="�📋 Мой профиль")],
    ]
    from src.bots.hub.keyboard import is_unified, MENU_BUTTON_TEXT
    if is_unified():
        rows.append([KeyboardButton(text=MENU_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.FOOD)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode
