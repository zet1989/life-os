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


def main_keyboard() -> ReplyKeyboardMarkup:
    """Основная Reply-клавиатура бота Health."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍽 Еда"), KeyboardButton(text="🏋️ Тренировка")],
            [KeyboardButton(text="💧 Вода"), KeyboardButton(text="⚖️ Вес")],
            [KeyboardButton(text="🩺 Доктор"), KeyboardButton(text="📋 Мой профиль")],
        ],
        resize_keyboard=True,
    )


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.FOOD)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode
